"""`sim/eval.py`: success rate of a policy on held-out scenes drawn by the dataset generator. A stub policy stands in
for the ACT model, so these tests need no weights and no network."""
from __future__ import annotations

import numpy as np
import pytest

from sim import eval as sim_eval, layout, make_dataset as md
from smartseed_robot.robot import JOINTS


class Stub:
    """Holds the present state, or runs `act(robot, step, params)` (a way to move things by hand)."""

    def __init__(self, act=None):
        self.act, self.n, self.robot, self.params, self.states = act, 0, None, None, []

    def reset(self):
        self.n = 0

    def step(self, observation):
        self.states.append(np.array(observation["observation.state"]))
        self.n += 1
        if self.act is not None:
            self.act(self.robot, self.n, self.params)
        return dict(zip(JOINTS, map(float, observation["observation.state"])))


@pytest.fixture(scope="module")
def scenes(kin):
    return sim_eval.heldout_scenes("white", 3, kin=kin)


def test_held_out_scenes_come_from_a_seed_the_datasets_never_used(scenes):
    assert sim_eval.HELDOUT_SEED != 0  # the v2 datasets were generated with seed 0
    assert {p.seed for p in scenes} == {sim_eval.HELDOUT_SEED}
    trained = [md.sample_params("white", 0, a) for a in range(60)]
    for p in scenes:
        assert all(p.tray != t.tray or p.white != t.white for t in trained)


def test_held_out_scenes_are_reproducible_and_all_of_them_are_plannable(scenes, kin):
    again = sim_eval.heldout_scenes("white", 3, kin=kin)
    assert again == scenes
    assert len({p.attempt for p in scenes}) == 3
    for p in scenes:  # the scripted planner can grasp in each: a demonstration of it exists
        actions, _ = md.plan_actions(kin, p)
        assert len(actions) >= md.MIN_FRAMES


def test_an_idle_policy_fails_every_held_out_scene(scenes):
    stub = Stub()
    summary = sim_eval.evaluate(stub, "white", scenes, duration_s=1.0)
    assert summary.episodes == 3 and summary.successes == 0 and summary.success_rate == 0.0


def test_the_scene_is_the_generated_one_and_the_arm_starts_at_the_planned_start_pose(scenes, kin):
    p = scenes[0]
    seen = {}

    def look(robot, n, params):
        if n == 1:
            seen["tray"] = robot._model.body_pos[robot._model.body("tray").id][:2].copy()
            seen["seed"] = robot._data.qpos[robot._model.joint(f"seed_white_{p.target}_free").qposadr[0]:][:2].copy()

    stub = Stub(look)
    sim_eval.run_scene(stub, p, duration_s=0.5, on_robot=lambda robot: setattr(stub, "robot", robot))
    start = md.plan_actions(kin, p)[0][0]
    assert stub.states[0] == pytest.approx(start, abs=0.5)
    assert seen["tray"] == pytest.approx(p.tray.center, abs=1e-9)
    assert seen["seed"] == pytest.approx(p.seed_xy("white", p.target), abs=1e-3)


def test_lifting_the_target_seed_by_more_than_3_cm_is_a_success(scenes):
    def lift(robot, n, params):
        if n == 3:
            adr = robot._model.joint(f"seed_white_{params.target}_free").qposadr[0]
            robot._data.qpos[adr + 2] += 0.05

    stub = Stub(lift)
    stub.params = scenes[0]
    result = sim_eval.run_scene(stub, scenes[0], duration_s=1.0, on_robot=lambda robot: setattr(stub, "robot", robot))
    assert result.success and result.max_lift_mm > 30.0


def test_summary_counts_and_formats_the_rate():
    s = sim_eval.Summary(color="black", episodes=20, successes=3, held=2, max_lift_mm=[0.0] * 17 + [31.0, 40.0, 50.0],
                         closest_mm=[10.0] * 20)
    assert s.success_rate == pytest.approx(0.15)
    assert "3/20" in s.line() and "15" in s.line()


def test_only_the_first_episodes_are_filmed(scenes, tmp_path):
    video = tmp_path / "eval.mp4"
    sim_eval.evaluate(Stub(), "white", scenes, duration_s=0.5, video=video, video_episodes=2)
    assert video.exists() and video.stat().st_size > 0
    import imageio.v2 as imageio

    n = sum(1 for _ in imageio.get_reader(str(video)))
    assert n == 2 * 15  # 0.5 s at 30 fps, two episodes


def test_the_cli_defaults_to_20_episodes_the_final_model_and_the_eval_folder():
    args = sim_eval.parse_args(["--repo", "x/y", "--color", "black"])
    assert args.episodes == 20 and args.checkpoint is None
    assert args.out_dir.endswith("sim/out/eval")
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "white", "--checkpoint", "020000"]).checkpoint == "020000"


def test_the_policy_sees_the_very_frames_the_dataset_generator_recorded_for_the_same_scene(scenes):
    """Diagnosis of T5: eval and dataset share the observation path (keys, size, RGB order, units, start pose, camera
    and light jitter), so the first observation of an eval episode is byte-identical to frame 0 of the demonstration."""
    p = scenes[0]
    seen = {}

    class Spy(Stub):
        def step(self, observation):
            seen.setdefault("obs", {k: np.array(v) for k, v in observation.items()})
            return super().step(observation)

    sim_eval.run_scene(Spy(), p, duration_s=0.1)
    demo = md.simulate_episode(p)
    assert np.array_equal(seen["obs"]["observation.images.top"], demo.top[0])
    assert np.array_equal(seen["obs"]["observation.images.wrist"], demo.wrist[0])
    assert np.array_equal(seen["obs"]["observation.state"], demo.states[0])


def test_the_eval_draws_held_out_scenes_from_the_same_layout_mode_as_the_dataset(kin):
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "black"]).layout == "wide"
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "black", "--layout", "narrow"]).layout == "narrow"
    narrow = sim_eval.heldout_scenes("black", 2, kin=kin, layout_mode="narrow")
    assert [p.seed for p in narrow] == [sim_eval.HELDOUT_SEED] * 2
    for p in narrow:
        assert abs(p.tray.yaw_deg) <= md.NARROW.anchor_yaw_deg  # a narrow-mode scene, not a wide one
        assert max(abs(p.tray.center[0] - layout.TRAY_CENTER[0]),
                   abs(p.tray.center[1] - layout.TRAY_CENTER[1])) <= md.NARROW.anchor_jitter_m
        assert md.plan_actions(kin, p)[0].shape[0] >= md.MIN_FRAMES
    assert narrow != sim_eval.heldout_scenes("black", 2, kin=kin)


def test_the_planner_ceiling_counts_scripted_successes_on_held_out_scenes_of_the_layout(kin):
    seen = []

    renders = []

    def rollout(params, kin=None, *, render=True):
        seen.append(params)
        renders.append(render)
        ok = params.attempt != 1
        return md.Rollout(np.zeros((1, 6), np.float32), np.zeros((1, 6), np.float32), np.zeros((1, 1, 1, 3), np.uint8),
                          np.zeros((1, 1, 1, 3), np.uint8), success=ok, valid=True)

    res = sim_eval.planner_ceiling("black", 3, layout_mode="narrow", rollout=rollout, kin=kin)
    assert res == {"episodes": 3, "successes": 2, "valid": 3, "kept": 2, "success_rate": pytest.approx(2 / 3),
                   "kept_rate": pytest.approx(2 / 3)}
    assert seen == sim_eval.heldout_scenes("black", 3, kin=kin, layout_mode="narrow")  # same scenes the policy gets
    assert renders == [False] * 3  # physics only: no frames are rendered (100 episodes of frames filled a 24 GB Mac)


def test_the_ceiling_keeps_no_frames_and_an_unrendered_rollout_allocates_none(kin):
    p = sim_eval.heldout_scenes("black", 1, kin=kin, layout_mode="narrow")[0]
    run = md.simulate_episode(p, kin, render=False)
    assert run.top.nbytes + run.wrist.nbytes < 1_000_000  # not (300, 480, 640, 3) twice
    held = []

    def rollout(params, kin=None, *, render=True):
        r = md.simulate_episode(params, kin, render=render)
        held.append(r)
        return r

    sim_eval.planner_ceiling("black", 1, layout_mode="narrow", rollout=rollout, kin=kin)
    assert sum(r.top.nbytes + r.wrist.nbytes for r in held) < 1_000_000
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "black", "--planner"]).planner is True
