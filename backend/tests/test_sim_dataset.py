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
from smartseed_robot.sim_robot import SimRobot, joints_to_qpos

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


# -- narrow layout (T5b) --------------------------------------------------------------------------------------
N = md.NARROW
NOMINAL = {"white": layout.WHITE_BOX.center, "black": layout.BLACK_BOX.center, "tray": layout.TRAY_CENTER}


def test_layouts_are_named_and_the_wide_one_is_the_default_distribution():
    assert md.LAYOUTS == {"wide": md.RANDOM, "narrow": md.NARROW}
    assert md.dataset_name("black") == "smartseed-sim-grasp-black-v2"
    assert md.dataset_name("white", "narrow") == "smartseed-sim-grasp-white-v3-narrow"
    assert md.sample_params("black", 1, 2) == md.sample_params("black", 1, 2, r=md.RANDOM)  # wide streams unchanged


@pytest.mark.parametrize("color", ["black", "white"])
def test_narrow_layout_keeps_boxes_and_tray_near_their_nominal_pose_and_every_other_rule(color):
    poly = _view_quad()
    pan = np.array([layout.BASE_PAN_AXIS[0], 0.0])
    assert 0.0 < N.anchor_jitter_m <= 0.05 and 0.0 < N.anchor_yaw_deg <= 30.0  # a few cm, within +-30 deg
    assert (N.seeds_min, N.seeds_max, N.seed_wall_margin_m) == (R.seeds_min, R.seeds_max, R.seed_wall_margin_m)
    assert (N.light_scale, N.light_tilt_deg, N.colour_jitter) == (R.light_scale, R.light_tilt_deg, R.colour_jitter)
    centers = {k: [] for k in NOMINAL}
    for attempt in range(150):
        p = md.sample_params(color, seed=1, attempt=attempt, r=N)
        placed = {"white": (p.white.center, p.white.yaw_deg, layout.WHITE_BOX.outer_half),
                  "black": (p.black.center, p.black.yaw_deg, layout.BLACK_BOX.outer_half),
                  "tray": (p.tray.center, p.tray.yaw_deg, layout.TRAY_OUTER_HALF)}
        for name, (center, yaw, half) in placed.items():
            assert np.abs(np.subtract(center, NOMINAL[name])).max() <= N.anchor_jitter_m + 1e-12, name
            assert abs(yaw) <= N.anchor_yaw_deg + 1e-12, name
            centers[name].append(center)
            for corner in md.footprint(center, yaw, half):  # the wide-mode rules still hold
                world = np.array(layout.to_world(corner))
                assert _inside(poly, world, N.view_margin_m)
                assert np.linalg.norm(world - pan) >= N.base_keepout_m
        for a, b in itertools.combinations(placed.values(), 2):
            assert not md.overlap(a, b, N.object_gap_m)
        for state, box in ((p.black, layout.BLACK_BOX), (p.white, layout.WHITE_BOX)):  # seeds: still random in the box
            hx, hy = box.inner_half[0] - N.seed_wall_margin_m, box.inner_half[1] - N.seed_wall_margin_m
            assert N.seeds_min <= len(state.seeds) <= N.seeds_max
            assert all(abs(lx) <= hx + 1e-12 and abs(ly) <= hy + 1e-12 for _, lx, ly in state.seeds)
    for name, xy in centers.items():  # and it really jitters (not pinned to the nominal pose)
        assert np.array(xy).std(axis=0).min() > 0.25 * N.anchor_jitter_m, name


def test_narrow_scenes_are_reproducible_and_differ_from_the_wide_ones():
    a = md.sample_params("white", 5, 3, r=N)
    assert a == md.sample_params("white", 5, 3, r=N) and a != md.sample_params("white", 5, 3)


def test_the_generator_and_the_coverage_plot_use_the_requested_layout(tmp_path):
    seen = []

    def run(params, kin=None):
        seen.append(params)
        return fake_rollout(3)(params)

    root = tmp_path / "ds"
    md.build_dataset(root, "white", episodes=2, seed=0, repo_id="local/n", rollout=run, layout_mode="narrow")
    assert seen == [md.sample_params("white", 0, a, r=N) for a in range(2)]
    assert md.logged_scenes(md._read_log(root), layout_mode="narrow") == seen


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
        before = robot._model.body_pos.copy(), robot._model.cam_pos.copy()
        md.apply_scene(robot, p)
        m = robot._model
        for name in ("box_white", "box_black", "tray"):
            b = m.body(name).id
            assert not np.allclose(m.body_pos[b, :2], before[0][b, :2]), name
        assert not np.allclose(m.cam_pos, before[1])
        for name, state in (("box_white_wall_far", p.white), ("box_black_wall_far", p.black), ("tray_wall_far", p.tray)):
            xmat = robot._data.geom_xmat[m.geom(name).id].reshape(3, 3)  # the turn really reaches the rendered/colliding geom
            assert math.atan2(xmat[1, 0], xmat[0, 0]) == pytest.approx(
                math.atan2(math.sin(layout.BOARD_YAW + math.radians(state.yaw_deg)),
                           math.cos(layout.BOARD_YAW + math.radians(state.yaw_deg))), abs=1e-6), name
        for color, state in (("black", p.black), ("white", p.white)):
            assert np.allclose(m.body_pos[m.body(f"box_{color}").id, :2], state.center, atol=1e-9)
            for i, _, _ in state.seeds:  # every seed rests where the planner believes it is
                adr = m.joint(f"seed_{color}_{i}_free").qposadr[0]
                assert np.allclose(robot._data.qpos[adr:adr + 2], p.seed_xy(color, i), atol=1e-9)
            for i in set(range(layout.SEEDS_PER_BOX)) - {i for i, _, _ in state.seeds}:
                adr = m.joint(f"seed_{color}_{i}_free").qposadr[0]
                assert np.linalg.norm(robot._data.qpos[adr:adr + 2]) > 1.0  # parked far from the scene
    finally:
        robot.close()


@pytest.mark.parametrize("wall", ["box_black_wall_far", "box_white_wall_near", "tray_wall_left", "tray_div_row2"])
def test_walls_that_the_scene_moved_still_collide_with_the_arm(kin, wall):
    """MuJoCo's static broad phase is built at compile time: a wall moved by editing its geom would stay solid only
    at its nominal spot. The tool of the arm placed in the middle of a moved wall must touch it."""
    from sim import collision

    robot = SimRobot(initial=ACT_START)
    try:
        p = md.sample_params("black", seed=0, attempt=4)
        md.apply_scene(robot, p)
        m, d = robot._model, robot._data
        w = m.geom(wall).id
        nominal = np.array(layout.to_world(layout.WHITE_BOX.center))
        assert np.linalg.norm(d.geom_xpos[w][:2] - nominal) > 0.0  # (it moved somewhere)
        target = d.geom_xpos[w].copy()
        sol = kin.solve(target[0], target[1], 0.012, seed=dict(zip(JOINTS, [0.0, -60.0, 60.0, 30.0, 0.0, 10.0])))
        d.qpos[robot._qadr] = joints_to_qpos({**sol, "gripper": 10.0})
        mujoco.mj_forward(m, d)
        walls = set(collision.wall_geoms(m))
        arm = set(collision.arm_geoms(m))
        pairs = [(d.contact[i].geom1, d.contact[i].geom2) for i in range(d.ncon)]
        touching = [(a, b) for a, b in pairs if (a in arm and b in walls) or (b in arm and a in walls)]
        assert touching or collision.min_wall_distance(m, d) > 0.001, "overlapping geometry without a contact"
        assert collision.min_wall_distance(m, d) < 0.0, "the pose is meant to put the tool inside the wall"
        assert touching
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


# -- walls: the jaw yaw, the swept path and the validity of an episode ----------------------------------------
def test_jaw_axis_candidates_clear_the_walls_and_come_in_order_of_wrist_roll():
    from sim import grasp_test

    box = layout.OpenBox("b", (0.2, 0.0), (0.09, 0.06), 0.035)
    seed = np.array([*layout.to_world((0.2, 0.0)), 0.0])
    found = grasp_test.grasp_candidates(seed, 0.007, box)
    assert len(found) >= 6
    assert all(clear > grasp_test.WALL_MARGIN for clear, _, _ in found)
    spins = [abs(spin) for _, spin, _ in found]
    assert spins == sorted(spins)


def test_a_seed_in_a_box_too_small_for_the_open_jaws_has_no_candidate_and_no_plan(kin):
    from sim import grasp_test

    tiny = layout.OpenBox("b", (0.2, 0.0), (0.03, 0.03), 0.035)
    seed = np.array([*layout.to_world((0.2, 0.0)), 0.0])
    assert grasp_test.grasp_candidates(seed, 0.007, tiny) == []
    narrow = layout.OpenBox("b", (0.2, 0.0), (0.09, 0.03), 0.035)  # long enough along x, 5.2 cm wide inside
    near_wall = np.array([*layout.to_world((0.2, 0.021)), 0.0])
    assert all(clear > grasp_test.WALL_MARGIN for clear, _, _ in grasp_test.grasp_candidates(near_wall, 0.007, narrow))


def test_every_planned_path_keeps_its_distance_from_every_wall(kin):
    checked = 0
    for attempt in range(6):
        p, actions, marks = reachable(kin, "black" if attempt % 2 else "white", attempt, attempt)
        check = md.check_path(p, actions, marks)
        assert check.ok, check
        assert check.min_grasp_m >= md.GRASP_CLEARANCE_M and check.min_static_m >= md.GRASP_CLEARANCE_M
        assert check.min_transit_m >= min(md.TRANSIT_CLEARANCE_M, check.min_static_m)
        checked += 1
    assert checked == 6


def scenes_where_the_radial_jaw_cuts_a_wall(kin, colour="black"):
    """(params, radial plan, radial marks) of scenes whose radial (spin 0) approach fails the swept check."""
    for attempt in range(60):
        for resample in range(6):
            p = md.sample_params(colour, 0, attempt, resample)
            try:
                actions, marks = md.plan_radial(kin, p)
            except md.Unreachable:
                continue
            if not md.check_path(p, actions, marks).ok:
                yield p, actions, marks


def test_when_the_radial_jaw_cuts_a_wall_the_planner_picks_a_yaw_that_clears_it(kin):
    """Among the scenes whose radial jaw axis cuts a wall, the planner flies another axis in some."""
    rolled = 0
    for p, bad_actions, bad_marks in itertools.islice(scenes_where_the_radial_jaw_cuts_a_wall(kin), 25):
        assert not md.check_path(p, bad_actions, bad_marks).ok
        try:
            actions, marks = md.plan_actions(kin, p)
        except md.Unreachable:
            continue  # no axis fits or reaches there: the scene is redrawn (next test)
        assert md.check_path(p, actions, marks).ok
        wrist = slice(bad_marks["descend_start"], bad_marks["lift_start"])
        assert not np.allclose(actions[wrist, 4], bad_actions[wrist, 4], atol=1.0)  # a different wrist roll
        rolled += 1
        if rolled == 2:
            break
    assert rolled == 2


def test_a_scene_no_jaw_yaw_fits_is_a_placement_rejection_not_a_plan(kin):
    seen = 0
    for attempt in range(40):
        p = md.sample_params("white", 0, attempt)
        try:
            md.plan_actions(kin, p)
        except md.NoFit as exc:
            assert "wall" in str(exc) or "walls" in str(exc)
            seen += 1
        except md.Unreachable:
            pass  # out of the arm's reach: a different rejection
    assert seen > 0


def test_a_no_fit_scene_is_redrawn_and_counted_separately(tmp_path):
    def run(params, kin=None):
        if params.attempt == 0 and params.resample < 3:
            raise (md.NoFit("white seed 1: no jaw yaw clears the walls") if params.resample == 1 else md.Unreachable("ik"))
        return fake_rollout(3)(params)

    summary = md.build_dataset(tmp_path / "ds", "white", episodes=1, seed=0, repo_id="local/nofit", rollout=run)
    assert summary["saved"] == 1 and summary["ik_rejections"] == 3 and summary["fit_rejections"] == 1
    first = json.loads((tmp_path / "ds" / md.LOG_NAME).read_text().splitlines()[0])
    assert first["fit_rejections"] == 1 and first["ik_rejections"] == 3


def test_a_lifted_but_colliding_episode_is_discarded_and_counted(tmp_path):
    verdict = {0: False, 1: True}

    def run(params, kin=None):
        out = fake_rollout(3)(params)
        out.valid = verdict[params.attempt]
        out.info |= {"wall_max_penetration_mm": 4.0 if not out.valid else 0.0, "wall_max_force_n": 30.0, "wall_contact_steps": 7}
        return out

    summary = md.build_dataset(tmp_path / "ds", "black", episodes=1, seed=0, repo_id="local/coll", rollout=run)
    assert summary["saved"] == 1 and summary["attempts"] == 2 and summary["collision_rejections"] == 1
    log = [json.loads(line) for line in (tmp_path / "ds" / md.LOG_NAME).read_text().splitlines()]
    assert log[0]["ok"] is False and log[0]["reason"].startswith("collision") and log[0]["wall_max_penetration_mm"] == 4.0
    assert log[1]["ok"] is True and log[1]["wall_contact_steps"] == 7


def test_a_simulated_episode_is_lifted_and_has_no_wall_contact_at_all(kin):
    for attempt in (0, 1):
        p = reachable(kin, "black", attempt, attempt)[0]
        run = md.simulate_episode(p, kin, render=False)
        assert run.success and run.valid, run.info
        assert run.info["wall_contact_steps"] == 0 and run.info["wall_max_penetration_mm"] <= 1.0


def test_the_monitor_rejects_an_episode_whose_jaw_goes_through_a_wall(kin):
    verdicts = []
    for p, bad_actions, bad_marks in itertools.islice(scenes_where_the_radial_jaw_cuts_a_wall(kin), 4):
        run = md.simulate_episode(p, kin, render=False, plan=(bad_actions, bad_marks))
        verdicts.append((run.valid, run.info["wall_contact_steps"]))
    assert verdicts and not all(valid for valid, _ in verdicts), verdicts  # the monitor sees what the planner sees
    assert any(steps > 0 for _, steps in verdicts)


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


def test_the_v2_dataset_card_says_v1_was_withdrawn_without_linking_it_and_states_the_validity_rule_and_the_stats():
    stats = {"episodes": 100, "frames": 29000, "attempts": 112, "success_rate": 0.89, "collision_rejections": 0,
             "ik_rejections": 640, "fit_rejections": 300, "reach_rejections": 340}
    card = md.dataset_card("white", "RafaelJaime/smartseed-sim-grasp-white-v2", commit="abc1234", stats=stats,
                           v1_rejected_pct=37.0)
    assert "withdrawn" in card.lower() and "git history" in card  # v1 is gone from the Hub, regenerable
    assert "huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white)" not in card  # no link to the deleted repo
    assert "huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white\n" not in card
    assert "pass" in card and "wall" in card and "1 mm" in card  # the v1 problem and the criterion
    assert "37 %" in card  # share of v1 episodes that would be rejected
    assert "640" in card and "300" in card  # placement rejections, no-fit among them
    assert "smartseed-grasp-d2-clean" in card and "BraboRobots" in card.split("---")[1]


def test_no_document_links_the_withdrawn_v1_datasets():
    import re
    from pathlib import Path

    root = Path(md.ROOT)
    dead = re.compile(r"datasets/RafaelJaime/smartseed-sim-grasp-(black|white)(?![\w-])")
    for doc in ("README.md", "sim/README.md", "docs/simulation.md", "odd/tasks/sim-replica.md"):
        assert not dead.search((root / doc).read_text()), f"{doc} links a deleted v1 dataset"


def test_the_narrow_card_states_the_layout_bounds_and_links_no_v1():
    stats = {"episodes": 300, "frames": 88000, "attempts": 330, "success_rate": 0.9, "collision_rejections": 0,
             "ik_rejections": 40, "fit_rejections": 10, "reach_rejections": 30}
    card = md.dataset_card("black", "RafaelJaime/smartseed-sim-grasp-black-v3-narrow", commit="abc1234", stats=stats,
                           layout_mode="narrow")
    assert "narrow" in card.lower() and f"+-{N.anchor_yaw_deg:.0f} deg" in card and f"{100 * N.anchor_jitter_m:.0f} cm" in card
    assert "anywhere on the table" not in card  # the wide-layout row is not claimed
    assert "https://github.com/alvaromoli13/Robotluces" in card and "BraboRobots" in card.split("---")[1]
    assert "huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black)" not in card
    assert "(https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v2)" in card  # the wide sibling
    assert "300" in card and "1 mm" in card


def test_the_wall_audit_flags_a_pass_through_plan_and_passes_a_planned_episode(kin):
    from sim import audit_walls

    bad = next(scenes_where_the_radial_jaw_cuts_a_wall(kin))
    report = audit_walls.audit_episode(bad[0], kin, plan=bad[1:]).report
    assert report.contact_steps > 0  # in v2 physics the wall stops the jaw (<1 mm), but the arm did run into it
    good, actions, marks = reachable(kin, "black", 0, 1)
    audit = audit_walls.audit_episode(good, kin, plan=(actions, marks))
    assert audit.report.valid and audit.report.contact_steps == 0 and audit.lifted
    assert audit.grasp_penetration_m == audit.start_penetration_m == 0.0


def test_the_first_episodes_of_a_dataset_export_as_side_by_side_mp4(tmp_path):
    import imageio.v2 as imageio

    root = tmp_path / "ds"
    md.build_dataset(root, "black", episodes=3, seed=0, rollout=fake_rollout(6), repo_id="local/vid")
    out = tmp_path / "videos"
    paths = md.export_videos(root, "local/vid", episodes=2, out_dir=out, prefix="black")
    assert [p.name for p in paths] == ["black_ep00.mp4", "black_ep01.mp4"]
    frames = imageio.mimread(str(paths[0]), memtest=False)
    assert len(frames) == 6 and frames[0].shape[1] == 2 * IMAGE_SHAPE[1] and frames[0].shape[0] == IMAGE_SHAPE[0]
