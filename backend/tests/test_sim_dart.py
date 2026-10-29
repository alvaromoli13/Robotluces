"""T5e: DART recovery demos. Smooth noise on the executed joints, the recorded action stays the expert's target."""
from __future__ import annotations

import json

import numpy as np
import pytest

from sim import eval as sim_eval, make_dataset as md
from smartseed_robot.robot import IMAGE_SHAPE

from test_sim_dataset import reachable


def test_the_cli_takes_a_dart_noise_in_degrees_and_defaults_to_off():
    assert md.parse_args(["--color", "black"]).dart_noise == 0.0
    assert md.parse_args(["--color", "black", "--dart-noise", "2.5"]).dart_noise == 2.5
    assert sim_eval.parse_args(["--planner", "--color", "black"]).dart_noise == 0.0
    assert sim_eval.parse_args(["--planner", "--color", "black", "--dart-noise", "3"]).dart_noise == 3.0


def test_the_dart_datasets_have_their_own_name_and_the_default_names_are_unchanged():
    assert md.dataset_name("black", "narrow", dart=True) == "smartseed-sim-grasp-black-v5-dart"
    assert md.dataset_name("white", "narrow") == "smartseed-sim-grasp-white-v3-narrow"
    assert md.dataset_name("white") == "smartseed-sim-grasp-white-v2"


@pytest.fixture(scope="module")
def planned(kin):
    return reachable(kin, "black", 3, 2)


def test_the_noise_is_smooth_bounded_and_confined_to_the_arm_joints_of_the_approach(planned):
    p, actions, marks = planned
    amp = 3.0
    noise = md.dart_offsets(p.wobble_seed, marks, len(actions), amp)
    assert noise.shape == (len(actions), 5)
    assert np.abs(noise).max() <= 2 * amp + 1e-9  # bounded
    assert np.abs(noise).max() > 0.5 * amp  # and not silent
    assert np.abs(np.diff(noise, axis=0)).max() < 0.25 * amp  # a smooth path, not a fresh draw per frame
    live = np.abs(noise).sum(axis=1) > 0
    assert live[marks["transit"]: marks["descend_start"] + 1].any()  # applied in the approach and the descent
    assert not live[: marks["transit"]].any()  # never while idle
    assert not live[marks["settle"]:].any()  # the end of the descent, the close, the lift and the fold-back are the plan
    assert np.array_equal(noise, md.dart_offsets(p.wobble_seed, marks, len(actions), amp))  # reproducible
    assert not np.array_equal(noise, md.dart_offsets(p.wobble_seed + 1, marks, len(actions), amp))


def test_the_noise_is_temporally_correlated(planned):
    p, actions, marks = planned
    noise = md.dart_offsets(p.wobble_seed, marks, len(actions), 3.0)
    a = noise[marks["transit"] + 20: marks["descend_start"] - 5, :]
    x = a - a.mean(axis=0)
    lag1 = (x[1:] * x[:-1]).sum() / (x * x).sum()
    assert lag1 > 0.9  # white noise would sit near 0


def test_no_noise_means_zero_offsets(planned):
    p, actions, marks = planned
    assert not md.dart_offsets(p.wobble_seed, marks, len(actions), 0.0).any()


def test_with_noise_the_recorded_action_is_the_plan_and_differs_from_the_executed_command(kin, planned):
    p, plan, marks = planned
    run = md.simulate_episode(p, kin, render=False, dart_noise_deg=3.0)
    assert np.array_equal(run.actions, plan)  # the recorded target is the nominal expert waypoint
    assert run.commands is not None and run.commands.shape == run.actions.shape
    assert not np.array_equal(run.commands, run.actions)  # what the arm was sent is perturbed ...
    assert np.array_equal(run.commands[:, 5], run.actions[:, 5])  # ... on the arm joints only
    assert np.array_equal(run.commands[marks["settle"]:], run.actions[marks["settle"]:])
    assert run.info["dart_noise_deg"] == 3.0


def test_without_noise_the_episode_is_what_it_was_before(kin, planned):
    p, plan, marks = planned
    plain = md.simulate_episode(p, kin, render=False)
    zero = md.simulate_episode(p, kin, render=False, dart_noise_deg=0.0)
    assert plain.commands is None and "dart_noise_deg" not in plain.info
    assert np.array_equal(plain.actions, plan) and np.array_equal(plain.states, zero.states)
    assert plain.success == zero.success and plain.info == zero.info


def test_the_noisy_demonstration_still_lifts_the_seed_without_touching_a_wall(kin, planned):
    p = planned[0]
    run = md.simulate_episode(p, kin, render=False, dart_noise_deg=2.0)
    assert run.success and run.valid, run.info


def test_the_generator_hands_the_noise_to_the_rollout_and_only_then(tmp_path):
    seen = []

    def run(params, kin=None, **kw):
        seen.append(kw)
        n = 3
        actions = np.tile(np.linspace(0, 1, n, dtype=np.float32)[:, None], (1, 6))
        img = np.zeros((n, *IMAGE_SHAPE), dtype=np.uint8)
        return md.Rollout(actions, actions + 0.5, img, img.copy(), success=True, info={"lift_mm": 90.0, "peak_lift_mm": 90.0})

    md.build_dataset(tmp_path / "plain", "black", episodes=1, seed=0, repo_id="local/plain", rollout=run, layout_mode="narrow")
    md.build_dataset(tmp_path / "dart", "black", episodes=1, seed=0, repo_id="local/dart", rollout=run, layout_mode="narrow",
                     dart_noise_deg=2.0)
    assert seen == [{}, {"dart_noise_deg": 2.0}]
    log = json.loads((tmp_path / "dart" / md.LOG_NAME).read_text().splitlines()[0])
    assert log["dart_noise_deg"] == 2.0


def test_the_planner_ceiling_accepts_the_noise_and_passes_it_on(kin):
    seen = []

    def rollout(params, kin=None, *, render=True, **kw):
        seen.append(kw)
        return md.Rollout(np.zeros((1, 6), np.float32), np.zeros((1, 6), np.float32), np.zeros((1, 1, 1, 3), np.uint8),
                          np.zeros((1, 1, 1, 3), np.uint8), success=True, valid=True)

    res = sim_eval.planner_ceiling("black", 2, layout_mode="narrow", rollout=rollout, kin=kin, dart_noise_deg=2.5)
    assert res["successes"] == 2 and seen == [{"dart_noise_deg": 2.5}] * 2
    seen.clear()
    sim_eval.planner_ceiling("black", 1, layout_mode="narrow", rollout=rollout, kin=kin)
    assert seen == [{}]
