"""`sim/run_policy.py`: a stub policy stands in for the ACT model, so these tests need no weights and no network."""
from __future__ import annotations

import json

import numpy as np
import pytest

from sim import layout, run_policy
from smartseed_robot.act import ACT_START_FALLBACK, TASK, LeRobotActPolicy
from smartseed_robot.robot import IMAGE_SHAPE, JOINTS

ACT_START = json.loads((run_policy.CONFIG_DIR / "poses.json").read_text())["act_start"]


class Stub:
    """Records every observation it is fed; returns `action(robot, step)` or holds the present state."""

    def __init__(self, action=None):
        self.observations, self.resets, self.action, self.robot = [], 0, action, None

    def reset(self):
        self.resets += 1

    def step(self, observation):
        n = len(self.observations)
        self.observations.append({k: np.array(v) for k, v in observation.items()})
        if self.action is not None:
            return self.action(self.robot, n)
        return dict(zip(JOINTS, map(float, observation["observation.state"])))


def episode(stub, duration_s=1.0, color="black", jitter=0.0, seed=0, record=False):
    robot = run_policy.make_robot(ACT_START)
    stub.robot = robot
    try:
        return run_policy.run_episode(robot, stub, color, duration_s=duration_s, jitter=jitter,
                                      rng=np.random.default_rng(seed), record=record), robot
    finally:
        robot.close()


def test_the_policy_is_fed_exactly_the_keys_shapes_dtypes_and_units_the_real_loop_feeds():
    stub = Stub()
    episode(stub)
    obs = stub.observations[0]
    assert set(obs) == {"observation.state", "observation.images.top", "observation.images.wrist"}
    assert obs["observation.state"].shape == (6,) and obs["observation.state"].dtype == np.float32
    for cam in ("top", "wrist"):  # HWC uint8 RGB 480x640, the frame the real cameras hand to lerobot
        image = obs[f"observation.images.{cam}"]
        assert image.shape == IMAGE_SHAPE and image.dtype == np.uint8
        assert image.std() > 5  # a rendered scene, not a blank frame
    # degrees (lerobot use_degrees) with the gripper on 0-100, in JOINTS order, at the taught act_start
    assert obs["observation.state"] == pytest.approx([ACT_START[j] for j in JOINTS], abs=0.5)


def test_the_sim_arm_starts_at_the_act_start_pose_and_the_policy_is_reset_once():
    stub = Stub()
    episode(stub)
    assert stub.resets == 1
    assert run_policy.load_act_start() == ACT_START
    assert list(ACT_START_FALLBACK) == list(JOINTS)


def test_the_loop_runs_at_30_fps_of_simulated_time_for_the_duration():
    stub = Stub()
    result, robot = episode(stub, duration_s=1.5)
    assert len(stub.observations) == 45 and result.steps == 45
    assert result.sim_seconds == pytest.approx(45 / 30, abs=1e-6)


def test_policy_actions_reach_the_sim_joints():
    goal = {**ACT_START, "shoulder_pan": ACT_START["shoulder_pan"] + 12.0, "gripper": 40.0}
    stub = Stub(lambda robot, n: goal)
    result, robot = episode(stub, duration_s=1.5)
    last = stub.observations[-1]["observation.state"]
    assert last[JOINTS.index("shoulder_pan")] == pytest.approx(goal["shoulder_pan"], abs=1.5)
    assert last[JOINTS.index("gripper")] > 30.0
    assert result.final_gripper == pytest.approx(last[JOINTS.index("gripper")], abs=3.0)


def test_an_idle_policy_does_not_lift_a_seed():
    result, _ = episode(Stub(), duration_s=1.0)
    assert not result.success and result.max_lift_mm < 1.0


def test_a_seed_lifted_by_more_than_3_cm_is_a_success_and_the_max_lift_is_reported():
    def lift(robot, n):
        if n == 5:
            adr = robot._model.joint("seed_black_1_free").qposadr[0]
            robot._data.qpos[adr + 2] += 0.05  # any seed of the colour counts
        return ACT_START

    result, _ = episode(Stub(lift), duration_s=1.0)
    assert result.success and result.max_lift_mm > 30.0
    assert not result.in_jaws  # it was moved by hand, far from the tool frame


def test_a_lift_below_3_cm_is_not_a_success():
    rest = [0.0]

    def lift(robot, n):
        adr = robot._model.joint("seed_black_0_free").qposadr[0]
        if n == 0:
            rest[:] = [robot._data.qpos[adr + 2]]
        if n >= 5:  # held 2.5 cm above its resting height before the step's physics
            robot._data.qpos[adr + 2] = rest[0] + 0.025
            robot._data.qvel[:] = 0
        return ACT_START

    result, _ = episode(Stub(lift), duration_s=1.0)
    assert not result.success and 10.0 < result.max_lift_mm < 30.0


def test_only_seeds_of_the_requested_colour_count():
    def lift_white(robot, n):
        if n == 5:
            adr = robot._model.joint("seed_white_0_free").qposadr[0]
            robot._data.qpos[adr + 2] += 0.05
        return ACT_START

    result, _ = episode(Stub(lift_white), duration_s=1.0, color="black")
    assert not result.success


def test_a_seed_between_the_jaws_at_the_end_is_reported_as_in_the_jaws():
    def carry(robot, n):
        adr = robot._model.joint("seed_black_0_free").qposadr[0]  # held at the tool frame by hand every step
        tool = robot._data.site_xpos[robot._model.site("gripperframe").id]
        robot._data.qpos[adr:adr + 3] = tool + [0.0, 0.0, 0.002]
        robot._data.qvel[:] = 0
        return ACT_START

    result, _ = episode(Stub(carry), duration_s=0.5)
    assert result.in_jaws


def test_jitter_moves_every_seed_of_the_colour_within_bounds_and_is_reproducible():
    robot_a, robot_b = run_policy.make_robot(ACT_START), run_policy.make_robot(ACT_START)
    try:
        rng = np.random.default_rng(3)
        run_policy.jitter_seeds(robot_a, "white", 0.01, rng)
        run_policy.jitter_seeds(robot_b, "white", 0.01, np.random.default_rng(3))
        nominal = layout.seed_positions("white")
        for i in range(4):
            qa = run_policy.seed_xyz(robot_a, "white", i)
            qb = run_policy.seed_xyz(robot_b, "white", i)
            assert qa == pytest.approx(qb)
            delta = qa[:2] - np.array(nominal[i][:2])
            assert 0 < np.abs(delta).max() <= 0.01 + 1e-9
    finally:
        robot_a.close(), robot_b.close()


def test_recording_keeps_a_side_by_side_top_and_wrist_frame_per_step():
    result, _ = episode(Stub(), duration_s=0.5, record=True)
    assert len(result.frames) == 15
    assert result.frames[0].shape == (IMAGE_SHAPE[0], 2 * IMAGE_SHAPE[1], 3)


def test_policy_names_and_media_paths_come_from_the_repo_and_checkpoint():
    assert run_policy.policy_name("RafaelJaime/act-smartseed-d1-c100-80k") == "d1-c100-80k"
    assert run_policy.policy_name("RafaelJaime/act-smartseed-d2-c50", "040000") == "d2-c50-040000"


def test_the_policy_is_loaded_through_the_backend_resolver_and_lerobot_wrapper():
    calls = []
    sentinel = object()

    def resolver(repo, checkpoint):
        calls.append(("resolve", repo, checkpoint))
        return "local/spec"

    def factory(spec, device):
        calls.append(("load", spec, device))
        return sentinel

    assert run_policy.load_policy("R/act", "010000", "cpu", resolver=resolver, factory=factory) is sentinel
    assert calls == [("resolve", "R/act", "010000"), ("load", "local/spec", "cpu")]
    assert TASK == "grasp the seed below the gripper" and LeRobotActPolicy  # the wrapper act.py runs


def test_cli_defaults():
    args = run_policy.parse_args(["--repo", "R/x", "--color", "white"])
    assert (args.duration, args.episodes, args.checkpoint, args.color) == (10.0, 10, None, "white")


def test_the_png_strip_stacks_top_over_wrist_for_each_picked_frame(tmp_path):
    import imageio.v2 as imageio

    result, _ = episode(Stub(), duration_s=0.5, record=True)
    out = tmp_path / "strip.png"
    run_policy.save_strip(result.frames[:6], out)
    strip = imageio.imread(str(out))
    assert strip.shape == (2 * 160, 6 * 214, 3)


def test_the_closest_approach_of_the_tool_to_a_seed_of_the_colour_is_reported():
    idle, _ = episode(Stub(), duration_s=0.5)
    assert idle.min_tool_seed_mm > 50.0  # act_start hovers well away from the box

    def carry(robot, n):
        adr = robot._model.joint("seed_black_0_free").qposadr[0]
        robot._data.qpos[adr:adr + 3] = robot._data.site_xpos[robot._model.site("gripperframe").id] + [0, 0, 0.002]
        robot._data.qvel[:] = 0
        return ACT_START

    near, _ = episode(Stub(carry), duration_s=0.5)
    assert near.min_tool_seed_mm < 20.0
