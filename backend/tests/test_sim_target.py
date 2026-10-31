"""T5g, goal-conditioned ACT: `sim/add_target.py` writes the target seed position into a dataset as
`observation.environment_state`, and `eval.py` / `run_policy.py` feed the same input to a policy that declares it.

Hardware-free and network-free: the converter tests build a tiny dataset with a fake rollout (no physics, blank frames),
the eval tests use a stub policy.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from sim import add_target, eval as sim_eval, make_dataset as md, run_policy
from smartseed_robot.act import ENV_STATE_KEY
from smartseed_robot.robot import IMAGE_SHAPE, JOINTS
from smartseed_robot.sim_robot import SimRobot

FEATURE = "observation.environment_state"


# -- the target position ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("color", ["black", "white"])
def test_the_target_is_the_seed_the_planner_aims_at_in_the_base_frame(color):
    for attempt in range(6):
        p = md.sample_params(color, 0, attempt, 0, md.LAYOUTS["narrow"])
        xy = add_target.target_xy(p)
        assert xy.shape == (2,)
        assert xy == pytest.approx(p.seed_xyz(p.target)[:2], abs=1e-12)  # what plan_actions aims at (plus the aim error)
        robot = SimRobot()
        try:
            md.apply_scene(robot, p)
            live = run_policy.seed_xyz(robot, color, p.target)[:2]
        finally:
            robot.close()
        assert xy == pytest.approx(live, abs=1e-3)  # and where the twin really puts that seed


def test_the_seed_xy_is_a_position_in_metres_in_front_of_the_arm():
    xy = np.array([add_target.target_xy(md.sample_params("black", 0, a, 0, md.LAYOUTS["narrow"])) for a in range(20)])
    assert np.all(np.abs(xy) < 0.6) and np.all(np.abs(xy) > 0.0)


# -- the noise -------------------------------------------------------------------------------------------------
def test_zero_sigma_gives_the_exact_target():
    assert np.array_equal(run_policy.target_noise(np.random.default_rng(3), 0.0), np.zeros(2))


def test_the_noise_is_deterministic_per_key_and_scales_with_sigma():
    a = run_policy.target_noise(add_target.episode_rng(7, "black"), 4.0)
    assert np.array_equal(a, run_policy.target_noise(add_target.episode_rng(7, "black"), 4.0))
    assert not np.array_equal(a, run_policy.target_noise(add_target.episode_rng(8, "black"), 4.0))
    assert not np.array_equal(a, run_policy.target_noise(add_target.episode_rng(7, "white"), 4.0))
    assert run_policy.target_noise(add_target.episode_rng(7, "black"), 8.0) == pytest.approx(2 * a, abs=1e-12)


def test_the_noise_std_is_sigma_millimetres_per_axis_in_metres():
    draws = np.array([run_policy.target_noise(add_target.episode_rng(i, "black"), 4.0) for i in range(4000)])
    assert draws.std(axis=0) == pytest.approx([0.004, 0.004], rel=0.05)
    assert abs(draws.mean()) < 0.0004


# -- the converter ---------------------------------------------------------------------------------------------
def fake_rollout(frames=5):
    def run(params, kin=None):
        actions = np.tile(np.linspace(0, 1, frames, dtype=np.float32)[:, None], (1, 6))
        img = np.zeros((frames, *IMAGE_SHAPE), dtype=np.uint8)
        return md.Rollout(actions=actions, states=actions + 0.5, top=img, wrist=img.copy(), success=True,
                          info={"lift_mm": 100.0, "peak_lift_mm": 100.0})
    return run


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("src") / "smartseed-sim-grasp-black-vtest"
    md.build_dataset(root, "black", episodes=3, seed=0, rollout=fake_rollout(), repo_id="local/src", layout_mode="narrow")
    return root


@pytest.fixture(scope="module")
def converted(source, tmp_path_factory):
    out = tmp_path_factory.mktemp("dst") / "smartseed-sim-grasp-black-vtest-target"
    summary = add_target.add_target(source, out, "black", sigma_mm=4.0, layout_mode="narrow")
    return out, summary


def test_the_converter_adds_a_float32_xy_feature_and_keeps_everything_else(source, converted):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    out, summary = converted
    src = LeRobotDataset("local/src", root=source)
    ds = LeRobotDataset("local/dst", root=out)
    assert summary == {"episodes": 3, "frames": 15, "sigma_mm": 4.0}
    assert ds.meta.total_episodes == src.meta.total_episodes == 3 and ds.meta.total_frames == src.meta.total_frames == 15
    assert ds.features[FEATURE]["dtype"] == "float32" and list(ds.features[FEATURE]["shape"]) == [2]
    assert set(ds.features) - set(src.features) == {FEATURE}
    for key in ("action", "observation.state", "observation.images.top", "observation.images.wrist"):
        assert ds.features[key] == src.features[key]
    a, b = src[2], ds[2]
    assert b[FEATURE].shape == (2,) and str(b[FEATURE].dtype) == "torch.float32"
    assert np.array_equal(a["action"].numpy(), b["action"].numpy())
    assert np.array_equal(a["observation.state"].numpy(), b["observation.state"].numpy())
    assert tuple(b["observation.images.top"].shape) == tuple(a["observation.images.top"].shape)
    assert not (out / "data").samefile(source / "data")
    assert len(list((out / "videos").rglob("*.mp4"))) == len(list((source / "videos").rglob("*.mp4"))) > 0


def test_the_value_is_the_noisy_target_of_the_logged_scene_and_constant_over_each_episode(source, converted):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    out, _ = converted
    ds = LeRobotDataset("local/dst", root=out)
    scenes = md.logged_scenes(md._read_log(source), "narrow")
    assert len(scenes) == 3
    frames = ds.hf_dataset.to_pandas()
    for ep, p in enumerate(scenes):
        rows = np.stack(frames[frames.episode_index == ep][FEATURE].to_numpy())
        want = add_target.target_xy(p) + run_policy.target_noise(add_target.episode_rng(ep, "black"), 4.0)
        assert rows.shape == (5, 2) and (rows == rows[0]).all()
        assert rows[0] == pytest.approx(want, abs=1e-6)
    sidecar = json.loads((out / "target_noise.json").read_text())
    assert sidecar["sigma_mm"] == 4.0 and sidecar["frame"] == "robot base frame, metres" and sidecar["color"] == "black"
    rows = [json.loads(line) for line in (out / "sim_targets.jsonl").read_text().splitlines()]
    assert [r["episode_index"] for r in rows] == [0, 1, 2]
    assert rows[1]["target_xy"] == pytest.approx(add_target.target_xy(scenes[1]), abs=1e-9)


def test_sigma_zero_writes_the_exact_target(source, tmp_path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    out = tmp_path / "exact"
    add_target.add_target(source, out, "black", sigma_mm=0.0, layout_mode="narrow")
    p = md.logged_scenes(md._read_log(source), "narrow")[0]
    assert LeRobotDataset("local/exact", root=out)[0][FEATURE].numpy() == pytest.approx(add_target.target_xy(p), abs=1e-6)


def test_stats_cover_the_new_feature_globally_and_per_episode(converted):
    import pandas as pd

    out, _ = converted
    stats = json.loads((out / "meta" / "stats.json").read_text())
    assert {"action", "observation.state", "observation.images.top"} <= set(stats)
    s = stats[FEATURE]
    assert set(s) >= {"min", "max", "mean", "std", "count"}
    assert len(s["mean"]) == 2 and s["count"] == [15] and all(sd > 0 for sd in s["std"])
    frames = pd.concat(pd.read_parquet(f) for f in sorted((out / "data").glob("*/*.parquet")))
    values = np.stack(frames[FEATURE].to_numpy())
    assert s["mean"] == pytest.approx(values.mean(axis=0), abs=1e-6)
    assert s["min"] == pytest.approx(values.min(axis=0), abs=1e-6) and s["max"] == pytest.approx(values.max(axis=0), abs=1e-6)
    episodes = pd.concat(pd.read_parquet(f) for f in sorted((out / "meta" / "episodes").glob("*/*.parquet")))
    assert len(episodes) == 3
    for ep, row in episodes.reset_index(drop=True).iterrows():
        mine = np.stack(frames[frames.episode_index == ep][FEATURE].to_numpy())
        assert row[f"stats/{FEATURE}/mean"] == pytest.approx(mine[0], abs=1e-6)
        assert row[f"stats/{FEATURE}/std"] == pytest.approx([0, 0], abs=1e-4)  # constant; float32 rounding in lerobot's std
        assert list(row[f"stats/{FEATURE}/count"]) == [5]
        assert "stats/observation.state/mean" in row  # the old per-episode stats survive


def test_the_converted_dataset_still_supports_lerobots_own_tools(converted, tmp_path):
    from lerobot.datasets.dataset_tools import delete_episodes
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    out, _ = converted
    kept = delete_episodes(LeRobotDataset("local/dst", root=out), [1], output_dir=tmp_path / "pruned", repo_id="local/pruned")
    assert kept.meta.total_episodes == 2 and kept[0][FEATURE].shape == (2,)


def test_the_card_names_the_feature_frame_units_noise_and_source(converted):
    card = (converted[0] / "README.md").read_text()
    for needle in ("observation.environment_state", "robot base frame", "metres", "4 mm", "smartseed-sim-grasp-black-vtest",
                   "BraboRobots", "simulat"):
        assert needle in card


def test_a_log_that_does_not_match_the_dataset_is_refused(source, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    import shutil

    for item in source.iterdir():
        (shutil.copytree if item.is_dir() else shutil.copy)(item, broken / item.name)
    lines = (broken / md.LOG_NAME).read_text().splitlines()
    (broken / md.LOG_NAME).write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(ValueError, match="3 episodes.*2"):
        add_target.add_target(broken, tmp_path / "out", "black", layout_mode="narrow")
    assert not (tmp_path / "out").exists()


def test_an_existing_output_is_never_overwritten(source, converted):
    with pytest.raises(FileExistsError):
        add_target.add_target(source, converted[0], "black", layout_mode="narrow")


# -- eval and run_policy ---------------------------------------------------------------------------------------
class Spy:
    """Records every observation; holds the present state."""

    def __init__(self, wants=None):
        if wants is not None:
            self.wants_environment_state = wants
        self.seen = []

    def reset(self):
        self.seen = []

    def step(self, observation):
        self.seen.append({k: np.array(v) for k, v in observation.items()})
        return dict(zip(JOINTS, map(float, observation["observation.state"])))


@pytest.fixture(scope="module")
def scene(kin):
    return sim_eval.heldout_scenes("black", 1, kin=kin, layout_mode="narrow")[0]


def test_a_policy_without_an_environment_state_input_sees_the_observation_as_before(scene):
    spy = Spy()
    sim_eval.run_scene(spy, scene, duration_s=0.2)
    assert spy.seen and all(ENV_STATE_KEY not in o for o in spy.seen)
    assert set(spy.seen[0]) == {"observation.state", "observation.images.top", "observation.images.wrist"}
    off = Spy(wants=False)
    sim_eval.run_scene(off, scene, duration_s=0.2, target_noise_mm=4.0)
    assert all(ENV_STATE_KEY not in o for o in off.seen)


def test_a_policy_that_declares_the_input_gets_the_true_target_every_step(scene):
    spy = Spy(wants=True)
    sim_eval.run_scene(spy, scene, duration_s=0.2)
    assert len(spy.seen) == 6
    for o in spy.seen:
        assert o[ENV_STATE_KEY].shape == (2,) and o[ENV_STATE_KEY].dtype == np.float32
        assert o[ENV_STATE_KEY] == pytest.approx(add_target.target_xy(scene), abs=1e-6)


def test_the_eval_noise_is_drawn_once_per_episode_seeded_and_configurable(scene):
    def run(sigma):
        spy = Spy(wants=True)
        sim_eval.run_scene(spy, scene, duration_s=0.2, target_noise_mm=sigma)
        return np.stack([o[ENV_STATE_KEY] for o in spy.seen])

    a, b, c = run(4.0), run(4.0), run(8.0)
    truth = add_target.target_xy(scene)
    assert (a == a[0]).all() and np.array_equal(a, b)  # one draw, reproducible
    assert not np.allclose(a[0], truth, atol=1e-6)
    assert (c[0] - truth) == pytest.approx(2 * (a[0] - truth), abs=1e-6)
    assert np.abs(a[0] - truth).max() < 0.03


def test_evaluate_passes_the_noise_to_every_scene(scene):
    spy = Spy(wants=True)
    sim_eval.evaluate(spy, "black", [scene], duration_s=0.2, target_noise_mm=4.0)
    assert not np.allclose(spy.seen[0][ENV_STATE_KEY], add_target.target_xy(scene), atol=1e-6)


def test_the_cli_has_a_target_noise_option_defaulting_to_the_true_target():
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "black"]).target_noise_mm == 0.0
    assert sim_eval.parse_args(["--repo", "x/y", "--color", "black", "--target-noise-mm", "4"]).target_noise_mm == 4.0
    assert run_policy.parse_args(["--repo", "x/y"]).target_noise_mm == 0.0
    assert run_policy.parse_args(["--repo", "x/y", "--target-seed", "2"]).target_seed == 2


def test_run_policy_feeds_the_live_position_of_the_chosen_seed():
    robot = SimRobot()
    spy = Spy(wants=True)
    try:
        run_policy.run_episode(robot, spy, "black", duration_s=0.1, target_seed=1)
        want = run_policy.seed_xyz(robot, "black", 1)[:2]
    finally:
        robot.close()
    assert spy.seen[0][ENV_STATE_KEY] == pytest.approx(want, abs=1e-4)


def test_a_goal_conditioned_policy_needs_to_be_told_which_seed():
    robot = SimRobot()
    try:
        with pytest.raises(ValueError, match="target"):
            run_policy.run_episode(robot, Spy(wants=True), "black", duration_s=0.1)
    finally:
        robot.close()


# -- the backend policy ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("env", [True, False])
def test_the_backend_act_policy_declares_and_consumes_the_environment_state(env, tmp_path):
    import torch
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies import make_pre_post_processors
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy

    from smartseed_robot.act import LeRobotActPolicy

    inputs = {"observation.state": PolicyFeature(FeatureType.STATE, (6,)),
              "observation.images.top": PolicyFeature(FeatureType.VISUAL, (3, 480, 640))}
    if env:
        inputs[ENV_STATE_KEY] = PolicyFeature(FeatureType.ENV, (2,))
    output = {"action": PolicyFeature(FeatureType.ACTION, (6,))}
    cfg = ACTConfig(input_features=inputs, output_features=output, pretrained_backbone_weights=None, device="cpu",
                    chunk_size=4, n_action_steps=4, dim_model=32, n_heads=2, dim_feedforward=64, n_encoder_layers=1,
                    n_decoder_layers=1, latent_dim=4, n_vae_encoder_layers=1, push_to_hub=False)
    stats = {k: {s: torch.zeros(v.shape) + (1.0 if s in ("std", "max") else 0.0) for s in ("mean", "std", "min", "max")}
             for k, v in (inputs | output).items()}
    pre, post = make_pre_post_processors(policy_cfg=cfg, dataset_stats=stats)
    ACTPolicy(cfg).save_pretrained(tmp_path), pre.save_pretrained(tmp_path), post.save_pretrained(tmp_path)

    policy = LeRobotActPolicy(str(tmp_path), "cpu")
    assert policy.wants_environment_state is env
    obs = {"observation.state": np.zeros(6, np.float32), "observation.images.top": np.zeros((480, 640, 3), np.uint8)}
    if env:
        with pytest.raises(ValueError, match=ENV_STATE_KEY):
            policy.step(dict(obs))
        obs[ENV_STATE_KEY] = np.array([0.2, -0.1], np.float32)
    assert set(policy.step(obs)) == set(JOINTS)
