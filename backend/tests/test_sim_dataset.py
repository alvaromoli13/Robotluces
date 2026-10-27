"""`sim/make_dataset.py`: scripted demonstrations of the twin recorded as LeRobotDatasets with the real schema.

Hardware-free and network-free. The tests that need physics use the real scene without rendering; the dataset tests
inject a tiny fake rollout so no episode has to be simulated.
"""
from __future__ import annotations

import itertools
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
    assert md.sample_params("black", seed=7, attempt=3, resample=1) != a
    assert md.sample_params("black", seed=8, attempt=3) != a
    assert md.sample_params("white", seed=7, attempt=3) != a


def _view_quad():
    return md.view_polygon()


def _inside(poly, point, margin):
    """Point (world xy) inside the convex polygon, at least `margin` from every edge."""
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = x1 - x0, y1 - y0
        if (ex * (point[1] - y0) - ey * (point[0] - x0)) / math.hypot(ex, ey) < margin - 1e-9:
            return False
    return True


@pytest.mark.parametrize("color", ["black", "white"])
def test_every_random_parameter_stays_inside_its_documented_bound(color):
    poly = _view_quad()
    pan = np.array([layout.BASE_PAN_AXIS[0], 0.0])
    for attempt in range(200):
        p = md.sample_params(color, seed=1, attempt=attempt)
        assert R.seeds_min <= len(p.present) <= R.seeds_max and len(set(p.present)) == len(p.present)
        assert p.target in p.present and p.proposals >= 1
        footprints = []
        for name, state, box in (("black", p.black, layout.BLACK_BOX), ("white", p.white, layout.WHITE_BOX)):
            assert -180 <= state.yaw_deg < 180
            assert R.seeds_min <= len(state.seeds) <= R.seeds_max
            hx, hy = box.inner_half[0] - R.seed_wall_margin_m, box.inner_half[1] - R.seed_wall_margin_m
            for _, lx, ly in state.seeds:  # anywhere on the floor, a margin off the walls
                assert abs(lx) <= hx + 1e-12 and abs(ly) <= hy + 1e-12
            for (_, ax, ay), (_, bx, by) in itertools.combinations(state.seeds, 2):
                assert math.hypot(ax - bx, ay - by) >= R.seed_min_gap_m - 1e-12
            footprints.append((state.center, state.yaw_deg, box.outer_half))
        footprints.append((p.tray.center, p.tray.yaw_deg, layout.TRAY_OUTER_HALF))
        for center, yaw, half in footprints:
            assert np.linalg.norm(layout.to_world(center) - pan) <= R.reach_max_m
            for corner in md.footprint(center, yaw, half):
                world = np.array(layout.to_world(corner))
                assert _inside(poly, world, R.view_margin_m), "inside the top camera view"
                assert np.linalg.norm(world - pan) >= R.base_keepout_m
        for i in range(3):
            for j in range(i + 1, 3):
                assert not md.overlap(footprints[i], footprints[j], R.object_gap_m), "objects do not overlap"
        assert np.abs(p.top_cam_shift).max() <= R.top_cam_shift_m + 1e-12
        assert np.abs(p.top_cam_rot_deg).max() <= R.cam_rot_deg + 1e-12
        assert np.abs(p.wrist_cam_shift).max() <= R.wrist_cam_shift_m + 1e-12
        assert R.light_scale[0] <= p.light_scale <= R.light_scale[1]
        assert np.linalg.norm(p.light_tilt_deg) <= R.light_tilt_deg + 1e-9
        assert np.abs(p.colour_gain).max() <= R.colour_jitter + 1e-12
        assert md.MIN_FRAMES <= p.total_frames <= md.MAX_FRAMES
        assert np.abs(np.asarray(p.start_noise_deg)).max() <= max(R.start_noise_deg.values()) + 1e-12


def test_objects_and_seeds_cover_the_visible_table_not_just_a_neighbourhood_of_the_nominal_layout():
    ps = [md.sample_params("white", seed=0, attempt=i) for i in range(150)]
    for get in (lambda p: p.white.center, lambda p: p.black.center, lambda p: p.tray.center):
        xy = np.array([get(p) for p in ps])
        assert xy.std(axis=0).min() > 0.03  # centimetres of spread, not millimetres
        assert np.ptp(xy, axis=0).min() > 0.12
    for get in (lambda p: p.white.yaw_deg, lambda p: p.black.yaw_deg, lambda p: p.tray.yaw_deg):
        yaw = np.array([get(p) for p in ps])
        assert yaw.min() < -150 and yaw.max() > 150 and np.histogram(yaw, bins=4, range=(-180, 180))[0].min() > 15
    local = np.array([(lx, ly) for p in ps for _, lx, ly in p.white.seeds])
    hx, hy = (layout.WHITE_BOX.inner_half[i] - R.seed_wall_margin_m for i in (0, 1))
    assert local[:, 0].min() < -0.8 * hx and local[:, 0].max() > 0.8 * hx  # up to the margin on every side
    assert local[:, 1].min() < -0.8 * hy and local[:, 1].max() > 0.8 * hy
    assert len({len(p.present) for p in ps}) == 3 and len({p.target for p in ps}) == 4
    for field in ("top_cam_shift", "light_scale", "colour_gain", "wrist_cam_shift"):
        assert len({np.asarray(getattr(p, field)).tobytes() for p in ps}) > 100, field
    lengths = {p.total_frames for p in ps}  # most episodes run to the 300 frame cap, like the real ones
    assert 300 in lengths and len(lengths) > 5


def test_overlap_and_footprint_geometry():
    a = ((0.0, 0.0), 0.0, (0.05, 0.03))
    assert md.overlap(a, ((0.09, 0.0), 0.0, (0.05, 0.03)), 0.0)  # 1 cm into each other
    assert not md.overlap(a, ((0.12, 0.0), 0.0, (0.05, 0.03)), 0.0)  # 2 cm apart
    assert md.overlap(a, ((0.12, 0.0), 0.0, (0.05, 0.03)), 0.03)  # ... closer than a 3 cm gap
    assert not md.overlap(a, ((0.0, 0.09), 90.0, (0.05, 0.03)), 0.0)  # turned 90 degrees it is 10 cm long in y
    assert md.overlap(a, ((0.0, 0.07), 90.0, (0.05, 0.03)), 0.0)
    corners = md.footprint((0.1, 0.2), 90.0, (0.05, 0.03))
    assert np.allclose(sorted(map(tuple, np.round(corners, 6))), sorted([(0.07, 0.15), (0.13, 0.15), (0.07, 0.25), (0.13, 0.25)]))


def test_the_view_polygon_is_the_top_camera_footprint_on_the_table():
    poly = np.array(md.view_polygon())
    assert poly.shape == (4, 2)
    assert _inside(poly.tolist(), (0.30, -0.02), 0.1)  # right under the camera
    assert not _inside(poly.tolist(), (-0.2, 0.0), 0.0)  # behind the base


def test_the_scene_moves_both_boxes_the_tray_and_parks_the_absent_seeds():
    robot = SimRobot(initial=ACT_START)
    try:
        p = md.sample_params("black", seed=0, attempt=0)
        before = robot._model.geom_pos.copy(), robot._model.cam_pos.copy()
        md.apply_scene(robot, p)
        m = robot._model
        for name in ("box_white_floor", "box_black_floor", "tray_floor"):
            g = m.geom(name).id
            assert not np.allclose(m.geom_pos[g, :2], before[0][g, :2]), name
        assert not np.allclose(m.cam_pos, before[1])
        for name, state in (("box_white_wall_far", p.white), ("box_black_wall_far", p.black), ("tray_wall_far", p.tray)):
            xmat = robot._data.geom_xmat[m.geom(name).id].reshape(3, 3)  # the turn really reaches the rendered/colliding geom
            assert math.atan2(xmat[1, 0], xmat[0, 0]) == pytest.approx(
                math.atan2(math.sin(layout.BOARD_YAW + math.radians(state.yaw_deg)),
                           math.cos(layout.BOARD_YAW + math.radians(state.yaw_deg))), abs=1e-6), name
        for color, state in (("black", p.black), ("white", p.white)):
            floor = m.geom(f"box_{color}_floor").id
            assert np.allclose(m.geom_pos[floor, :2], state.center, atol=1e-9)
            for i, _, _ in state.seeds:  # every seed rests where the planner believes it is
                adr = m.joint(f"seed_{color}_{i}_free").qposadr[0]
                assert np.allclose(robot._data.qpos[adr:adr + 2], p.seed_xy(color, i), atol=1e-9)
            for i in set(range(layout.SEEDS_PER_BOX)) - {i for i, _, _ in state.seeds}:
                adr = m.joint(f"seed_{color}_{i}_free").qposadr[0]
                assert np.linalg.norm(robot._data.qpos[adr:adr + 2]) > 1.0  # parked far from the scene
    finally:
        robot.close()


def test_seeds_move_rigidly_with_their_box():
    p = md.sample_params("white", seed=3, attempt=2)
    state = p.white
    c, s = math.cos(math.radians(state.yaw_deg)), math.sin(math.radians(state.yaw_deg))
    for i, lx, ly in state.seeds:
        expected = np.array(state.center) + [c * lx - s * ly, s * lx + c * ly]
        assert np.allclose(layout.to_board(p.seed_xy("white", i)), expected, atol=1e-9)
    assert p.seed_xyz(p.target)[2] == pytest.approx(layout.WHITE_BOX.floor_z + layout.SEED_RADIUS["white"] + 1e-4)


# -- the motion -----------------------------------------------------------------------------------------------
def reachable(kin, color, seed, attempt=0):
    """The first resampled placement the planner can reach: (params, actions, phases)."""
    for k in range(60):
        p = md.sample_params(color, seed, attempt, k)
        try:
            return (p, *md.plan_actions(kin, p))
        except md.Unreachable:
            continue
    raise AssertionError("no reachable placement")


@pytest.fixture(scope="module")
def planned(kin):
    return reachable(kin, "black", 0, 1)[1:]


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
    assert step[:, :5].max() < 7.8  # below the follower's 8 degree per step clamp, so the state tracks the command
    jerk = np.abs(np.diff(actions, n=3, axis=0))
    assert jerk[:, :5].max() < 3.0  # eased, no steps


def test_the_descent_reaches_the_seed_centre_height(kin):
    p, actions, phases = reachable(kin, "white", 5)
    tool = kin.tool_xyz(dict(zip(JOINTS, map(float, actions[phases["close_start"]]))))
    seed = p.seed_xyz(p.target)
    assert abs(tool[2] - (seed[2] + md.TOOL_Z_OFFSET)) < 0.004
    assert np.linalg.norm(np.array(tool[:2]) - seed[:2]) < 0.03  # beside the seed, within one jaw length


def test_two_plans_of_the_same_params_are_identical(kin):
    p = reachable(kin, "white", 5)[0]
    assert np.array_equal(md.plan_actions(kin, p)[0], md.plan_actions(kin, p)[0])


def test_unreachable_seeds_are_reported_not_planned(kin):
    far = md.sample_params("black", seed=0, attempt=0)
    with pytest.raises(md.Unreachable):
        md.plan_actions(kin, far, force_seed_xyz=np.array([0.9, 0.0, 0.0]))


def test_wall_clearance_does_not_depend_on_how_the_box_is_turned():
    from sim import grasp_test

    box = layout.OpenBox("b", (0.2, 0.0), (0.09, 0.06), 0.035)
    for yaw in (0.0, 0.7, 2.0, -1.2):
        c, s = math.cos(yaw), math.sin(yaw)
        for local, k in (((0.01, 0.025), 0), ((-0.03, -0.02), 3), ((0.05, 0.01), 7)):  # a seed in the box frame
            xy = (0.2 + c * local[0] - s * local[1], s * local[0] + c * local[1])
            seed = np.array([*layout.to_world(xy), 0.0])
            ref = layout.to_world((0.2 + local[0], local[1]))
            phi = layout.BOARD_YAW + yaw + math.radians(15 * k)
            turned = grasp_test._clearance(seed, phi, box, (), box_yaw=yaw)
            straight = grasp_test._clearance(np.array([*ref, 0.0]), layout.BOARD_YAW + math.radians(15 * k), box, ())
            assert turned == pytest.approx(straight, abs=1e-9)


def test_the_coverage_plot_redraws_every_kept_scene_from_the_log(tmp_path):
    from PIL import Image

    kept = [{"attempt": a, "ok": a % 2 == 0, "ik_rejections": a % 3, "color": "black", "seed": 5} for a in range(8)]
    scenes = md.logged_scenes(kept)
    assert [s.attempt for s in scenes] == [0, 2, 4, 6]  # only kept episodes, redrawn with the same resample
    assert scenes[1] == md.sample_params("black", 5, 2, 2)
    out = tmp_path / "coverage.png"
    md.coverage_plot({"black": scenes, "white": [md.sample_params("white", 0, a) for a in range(3)]}, out)
    image = Image.open(out)
    assert image.size[0] > 800 and image.size[1] > 400


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


def test_a_placement_the_planner_cannot_reach_is_resampled_and_counted(tmp_path):
    seen = []

    def run(params, kin=None):
        seen.append(params)
        if params.attempt == 0 and params.resample < 2:
            raise md.Unreachable("black seed 3")
        return fake_rollout(3)(params)

    root = tmp_path / "ds"
    summary = md.build_dataset(root, "black", episodes=1, seed=0, repo_id="local/y", rollout=run)
    assert summary["saved"] == 1 and summary["attempts"] == 1 and summary["ik_rejections"] == 2
    assert [(p.attempt, p.resample) for p in seen] == [(0, 0), (0, 1), (0, 2)]
    assert seen[0] == md.sample_params("black", 0, 0, 0) and seen[2] == md.sample_params("black", 0, 0, 2)
    proposals = sum(p.proposals for p in seen)
    assert summary["placement_acceptance"] == pytest.approx(3 / proposals)  # fully accepted scenes per drawn object
    assert summary["ik_acceptance"] == pytest.approx(1 / 3)  # 1 reachable scene of the 3 that passed the geometry
    assert summary["geometry_acceptance"] == pytest.approx(9 / proposals)
    first = json.loads((root / md.LOG_NAME).read_text().splitlines()[0])
    assert first["ok"] is True and first["ik_rejections"] == 2 and first["proposals"] == proposals


def test_the_dataset_card_names_the_generator_and_says_it_is_simulated():
    card = md.dataset_card("black", "RafaelJaime/smartseed-sim-grasp-black", commit="abc1234",
                           stats={"episodes": 100, "frames": 28000, "attempts": 140, "success_rate": 0.71})
    assert "simulated" in card.lower() and "abc1234" in card
    assert "https://github.com/alvaromoli13/Robotluces" in card
    assert "BraboRobots" in card.split("---")[1]  # in the YAML tags
    assert "grasp the seed below the gripper" in card
    assert "smartseed-grasp-d1-clean" in card
