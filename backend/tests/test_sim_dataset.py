"""`sim/make_dataset.py`: scripted demonstrations of the twin recorded as LeRobotDatasets with the real schema.

Hardware-free and network-free. The tests that need physics use the real scene without rendering; the dataset tests
inject a tiny fake rollout so no episode has to be simulated.
"""
from __future__ import annotations

import json
import math

import mujoco
import numpy as np
import pytest

from sim import layout, make_dataset as md
from smartseed_robot.robot import ARM_JOINTS, IMAGE_SHAPE, JOINTS
from smartseed_robot.sim_robot import SimRobot

REAL = json.loads((md.CONFIG_DIR / "real_features.json").read_text())
ACT_START = json.loads((md.CONFIG_DIR / "poses.json").read_text())["act_start"]
R = md.RANDOM


# -- schema ---------------------------------------------------------------------------------------------------
def test_features_match_the_real_datasets_key_for_key():
    for key, real in REAL["features"].items():
        sim = md.FEATURES[key]
        assert sim["dtype"] == real["dtype"], key
        assert list(sim["shape"]) == list(real["shape"]), key
        assert sim["names"] == real["names"], key
    assert set(md.FEATURES) == set(REAL["features"])
    assert md.FPS == REAL["fps"] == 30
    assert md.TASK == REAL["task"] == "grasp the seed below the gripper"
    assert md.ROBOT_TYPE == REAL["robot_type"]
    assert REAL["features"]["observation.state"]["names"] == [f"{j}.pos" for j in JOINTS]


# -- randomisation --------------------------------------------------------------------------------------------
def test_params_are_reproducible_by_seed_and_differ_across_attempts():
    a, b = md.sample_params("black", seed=7, attempt=3), md.sample_params("black", seed=7, attempt=3)
    assert a == b
    assert md.sample_params("black", seed=7, attempt=4) != a
    assert md.sample_params("black", seed=8, attempt=3) != a
    assert md.sample_params("white", seed=7, attempt=3) != a


@pytest.mark.parametrize("color", ["black", "white"])
def test_every_random_parameter_stays_inside_its_documented_bound(color):
    for attempt in range(300):
        p = md.sample_params(color, seed=1, attempt=attempt)
        assert R.seeds_min <= len(p.present) <= R.seeds_max and len(set(p.present)) == len(p.present)
        assert all(0 <= i < layout.SEEDS_PER_BOX for i in p.present)
        assert p.target in p.present
        assert np.abs(p.seed_offsets).max() <= R.seed_jitter_m + 1e-12
        assert np.abs(p.box_shift).max() <= R.box_shift_m + 1e-12
        assert abs(p.box_yaw_deg) <= R.box_yaw_deg + 1e-12
        assert np.abs(p.top_cam_shift).max() <= R.top_cam_shift_m + 1e-12
        assert np.abs(p.top_cam_rot_deg).max() <= R.cam_rot_deg + 1e-12
        assert np.abs(p.wrist_cam_shift).max() <= R.wrist_cam_shift_m + 1e-12
        assert R.light_scale[0] <= p.light_scale <= R.light_scale[1]
        assert np.linalg.norm(p.light_tilt_deg) <= R.light_tilt_deg + 1e-9
        assert np.abs(p.colour_gain).max() <= R.colour_jitter + 1e-12
        assert md.MIN_FRAMES <= p.total_frames <= md.MAX_FRAMES
        assert np.abs(np.asarray(p.start_noise_deg)).max() <= max(R.start_noise_deg.values()) + 1e-12


def test_every_random_parameter_actually_varies():
    ps = [md.sample_params("white", seed=0, attempt=i) for i in range(60)]
    assert len({len(p.present) for p in ps}) == 3
    assert len({p.target for p in ps}) > 1
    for field in ("seed_offsets", "box_shift", "box_yaw_deg", "top_cam_shift", "light_scale", "colour_gain",
                  "wrist_cam_shift"):
        values = {np.asarray(getattr(p, field)).tobytes() for p in ps}
        assert len(values) > 30, field
    lengths = {p.total_frames for p in ps}  # most episodes run to the 300 frame cap, like the real ones
    assert 300 in lengths and len(lengths) > 5


def test_scene_randomisation_moves_the_box_and_hides_the_seeds_that_are_not_present():
    robot = SimRobot(initial=ACT_START)
    try:
        p = md.sample_params("black", seed=0, attempt=0)
        before = robot._model.geom_pos.copy(), robot._model.light_diffuse.copy(), robot._model.cam_pos.copy()
        md.apply_scene(robot, p)
        assert not np.allclose(robot._model.geom_pos, before[0])
        assert not np.allclose(robot._model.cam_pos, before[2])
        # the planner's idea of each present seed is where the seed really is
        for i in p.present:
            adr = robot._model.joint(f"seed_black_{i}_free").qposadr[0]
            assert np.allclose(robot._data.qpos[adr:adr + 2], p.seed_xyz(i)[:2], atol=1e-9)
        for i in set(range(layout.SEEDS_PER_BOX)) - set(p.present):
            adr = robot._model.joint(f"seed_black_{i}_free").qposadr[0]
            assert np.linalg.norm(robot._data.qpos[adr:adr + 2]) > 1.0  # parked far away from the scene
    finally:
        robot.close()


def test_box_pose_jitter_is_a_rigid_move_of_the_box_and_its_seeds():
    p = md.sample_params("white", seed=3, attempt=2)
    box = layout.WHITE_BOX
    moved = md.shifted_box(box, p)
    assert moved.center == pytest.approx(tuple(np.add(box.center, p.box_shift)))
    c, s = math.cos(math.radians(p.box_yaw_deg)), math.sin(math.radians(p.box_yaw_deg))
    for i in p.present:
        nominal = np.array(layout.seed_board_positions("white")[i]) - box.center
        expected = np.add(box.center, p.box_shift) + np.array([c * nominal[0] - s * nominal[1],
                                                               s * nominal[0] + c * nominal[1]]) + p.seed_offsets[i]
        assert np.allclose(layout.to_board(p.seed_xyz(i)[:2]), expected, atol=1e-9)


# -- the motion -----------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def planned(kin):
    return md.plan_actions(kin, md.sample_params("black", seed=0, attempt=1))


def test_the_plan_is_a_float32_trajectory_in_the_real_units_and_length(planned):
    actions, phases = planned
    assert actions.dtype == np.float32 and actions.ndim == 2 and actions.shape[1] == 6
    assert md.MIN_FRAMES <= len(actions) <= md.MAX_FRAMES
    assert np.isfinite(actions).all()
    assert phases["frames"] == len(actions)


def test_the_plan_starts_at_the_taught_act_start_and_ends_folded_at_rest(planned):
    actions, _ = planned
    start = np.array([ACT_START[j] for j in JOINTS])
    noise = np.array([R.start_noise_deg[j] for j in JOINTS]) + 1.0  # + the smooth teleop wobble
    assert np.all(np.abs(actions[0] - start) <= noise)
    end = actions[-1]
    assert end[1] < -95 and end[2] > 90 and -105 < end[3] < -75  # the real episodes end folded: lift -103, elbow 97, wrist -96
    assert end[5] < 7.5  # the leader still squeezes the seed
    assert np.abs(np.diff(actions[-10:], axis=0)).max() < 0.5  # and rests there


def test_the_gripper_opens_before_the_descent_and_closes_on_the_seed(planned):
    actions, phases = planned
    g = actions[:, 5]
    assert g.max() > 15.0  # the real teleop opens to 20-30
    assert phases["open"] < phases["descend_start"] < phases["close_start"] < phases["lift_start"] < phases["retract_start"]
    assert g[phases["descend_start"]] > 12.0 and g[phases["close_start"]] > 12.0
    assert g[phases["lift_start"]:].max() < 8.0


def test_the_arm_moves_within_what_a_follower_and_a_human_can_do(planned):
    actions, _ = planned
    step = np.abs(np.diff(actions, axis=0))
    assert step.max() < 7.5  # below the follower's 8 degree per step clamp, so the state tracks the command
    jerk = np.abs(np.diff(actions, n=3, axis=0))
    assert jerk[:, :5].max() < 3.0  # eased, no steps


def test_the_descent_reaches_the_seed_centre_height(kin):
    p = md.sample_params("white", seed=5, attempt=0)
    actions, phases = md.plan_actions(kin, p)
    tool = kin.tool_xyz(dict(zip(JOINTS, map(float, actions[phases["close_start"]]))))
    seed = p.seed_xyz(p.target)
    assert abs(tool[2] - (seed[2] + md.TOOL_Z_OFFSET)) < 0.004
    assert np.linalg.norm(np.array(tool[:2]) - seed[:2]) < 0.03  # beside the seed, within one jaw length


def test_two_plans_of_the_same_params_are_identical(kin):
    p = md.sample_params("white", seed=5, attempt=0)
    assert np.array_equal(md.plan_actions(kin, p)[0], md.plan_actions(kin, p)[0])


def test_unreachable_seeds_are_reported_not_planned(kin):
    far = md.sample_params("black", seed=0, attempt=0)
    with pytest.raises(md.Unreachable):
        md.plan_actions(kin, far, force_seed_xyz=np.array([0.9, 0.0, 0.0]))


# -- success --------------------------------------------------------------------------------------------------
def test_an_episode_succeeds_only_if_the_seed_rose_over_3_cm_and_is_still_in_the_jaws():
    rest = np.array([0.15, -0.13, 0.0])
    held = rest + [0.0, 0.0, 0.29]  # carried to the folded rest pose
    assert md.episode_success(rest, held, held + [0.004, 0.0, 0.0], peak_lift=0.29)
    assert not md.episode_success(rest, held, held + [0.0, 0.0, 0.10], peak_lift=0.29)  # dropped on the way
    assert not md.episode_success(rest, rest + [0, 0, 0.02], rest + [0, 0, 0.02], peak_lift=0.02)  # never lifted 3 cm
    assert not md.episode_success(rest, rest, held, peak_lift=0.0)


# -- dataset I/O ----------------------------------------------------------------------------------------------
def fake_rollout(frames=4, ok=lambda params: True):
    """A rollout with no physics: constant joints, blank 480x640 frames."""
    def run(params, kin=None):
        n = frames
        actions = np.tile(np.linspace(0, 1, n, dtype=np.float32)[:, None], (1, 6))
        img = np.zeros((n, *IMAGE_SHAPE), dtype=np.uint8)
        return md.Rollout(actions=actions, states=actions + 0.5, top=img, wrist=img.copy(), success=ok(params),
                          info={"lift_mm": 100.0, "peak_lift_mm": 100.0})
    return run


def test_an_episode_round_trips_through_lerobotdataset(tmp_path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = tmp_path / "ds"
    summary = md.build_dataset(root, "black", episodes=2, seed=0, rollout=fake_rollout(5), repo_id="local/sim-black")
    assert summary["saved"] == 2
    ds = LeRobotDataset("local/sim-black", root=root)
    assert ds.meta.total_episodes == 2 and ds.meta.total_frames == 10
    assert ds.fps == 30 and ds.meta.robot_type == REAL["robot_type"]
    assert ds.meta.info["codebase_version"] == REAL["codebase_version"]
    assert ds.meta.tasks.index.tolist() == [md.TASK]
    for key, real in REAL["features"].items():
        assert ds.features[key]["dtype"] == real["dtype"] and list(ds.features[key]["shape"]) == list(real["shape"])
    item = ds[0]
    assert item["observation.state"].shape == (6,) and item["action"].shape == (6,)
    assert tuple(item["observation.images.top"].shape) == (3, *IMAGE_SHAPE[:2])
    assert tuple(item["observation.images.wrist"].shape) == (3, *IMAGE_SHAPE[:2])
    assert ds.meta.info["features"]["observation.images.top"]["info"]["video.fps"] == 30
    assert float(item["observation.state"][0]) == pytest.approx(0.5, abs=1e-5)


def test_failed_episodes_are_discarded_and_counted(tmp_path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    verdict = {0: False, 1: True, 2: False, 3: True}
    root = tmp_path / "ds"
    summary = md.build_dataset(root, "white", episodes=2, seed=0, repo_id="local/sim-white",
                               rollout=fake_rollout(3, ok=lambda p: verdict[md.attempt_of(p)]))
    assert summary["saved"] == 2 and summary["attempts"] == 4 and summary["failed"] == 2
    assert summary["success_rate"] == pytest.approx(0.5)
    assert LeRobotDataset("local/sim-white", root=root).meta.total_episodes == 2
    log = [json.loads(l) for l in (root / md.LOG_NAME).read_text().splitlines()]
    assert [(r["attempt"], r["ok"]) for r in log] == [(0, False), (1, True), (2, False), (3, True)]
    assert all("seed" in r and "target" in r for r in log)


def test_generation_resumes_where_it_stopped_with_the_same_attempts(tmp_path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    seen = []

    def spy(params, kin=None):
        seen.append(params)
        return fake_rollout(3)(params)

    root = tmp_path / "ds"
    md.build_dataset(root, "black", episodes=2, seed=4, repo_id="local/x", rollout=spy)
    summary = md.build_dataset(root, "black", episodes=3, seed=4, repo_id="local/x", rollout=spy)
    assert summary["saved"] == 3 and summary["resumed_from"] == 2
    assert LeRobotDataset("local/x", root=root).meta.total_episodes == 3
    assert seen == [md.sample_params("black", 4, a) for a in range(3)]  # one pass of the same stream
    assert md.build_dataset(root, "black", episodes=3, seed=4, repo_id="local/x", rollout=spy)["saved"] == 3
    assert len(seen) == 3  # nothing left to do


def test_an_attempt_that_raises_unreachable_is_skipped_and_recorded(tmp_path):
    def run(params, kin=None):
        if md.attempt_of(params) == 0:
            raise md.Unreachable("black seed 3")
        return fake_rollout(3)(params)

    root = tmp_path / "ds"
    summary = md.build_dataset(root, "black", episodes=1, seed=0, repo_id="local/y", rollout=run)
    assert summary["saved"] == 1 and summary["unreachable"] == 1
    first = json.loads((root / md.LOG_NAME).read_text().splitlines()[0])
    assert first["ok"] is False and first["reason"].startswith("unreachable")


def test_the_dataset_card_names_the_generator_and_says_it_is_simulated():
    card = md.dataset_card("black", "RafaelJaime/smartseed-sim-grasp-black", commit="abc1234",
                           stats={"episodes": 100, "frames": 28000, "attempts": 140, "success_rate": 0.71})
    assert "simulated" in card.lower() and "abc1234" in card
    assert "https://github.com/alvaromoli13/Robotluces" in card
    assert "BraboRobots" in card.split("---")[1]  # in the YAML tags
    assert "grasp the seed below the gripper" in card
    assert "smartseed-grasp-d1-clean" in card
