"""The MuJoCo twin of the scene: layout constants, the generated MJCF, the joint mapping and the cameras."""
from __future__ import annotations

import mujoco
import numpy as np
import pytest

from sim import layout
from smartseed_robot.robot import JOINTS
from smartseed_robot.sim_robot import (GRIPPER_JAW_RAD, deg_to_rad, gripper_to_jaw, jaw_to_gripper, qpos_to_joints,
                                       joints_to_qpos)


@pytest.fixture(scope="module")
def model():
    return mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))


def test_committed_scene_xml_is_what_the_generator_writes():
    assert layout.SCENE_PATH.read_text() == layout.build_scene_xml()


def test_scene_declares_both_640x480_cameras(model):
    for name in ("top", "wrist"):
        assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name) >= 0
    assert (model.vis.global_.offwidth, model.vis.global_.offheight) == (640, 480)


def test_wrist_camera_rides_on_the_gripper(model):
    cam = model.camera("wrist")
    assert model.body(cam.bodyid[0]).name in ("gripper", "wrist_camera", "wrist_camera_mount")


def test_tray_has_twelve_recessed_cells_inside_the_tray(model):
    centers = [layout.cell_center(r, c) for r in range(layout.TRAY_ROWS) for c in range(layout.TRAY_COLS)]
    assert len(centers) == 12
    x0, x1, y0, y1 = layout.tray_bounds()
    for x, y, z in centers:
        bx, by = layout.to_board((x, y))
        assert x0 < bx < x1 and y0 < by < y1
        assert z == pytest.approx(layout.CELL_FLOOR_Z)
    assert layout.CELL_FLOOR_Z < layout.TRAY_TOP_Z - 0.02  # recessed


def test_cell_rows_run_away_from_the_robot_and_columns_to_the_right_of_the_image():
    # image up = away from the base, image right = -y: row 0 is the far row, col 0 the left column
    far, near = layout.to_board(layout.cell_center(0, 0)), layout.to_board(layout.cell_center(3, 0))
    left, right = layout.to_board(layout.cell_center(0, 0)), layout.to_board(layout.cell_center(0, 2))
    assert far[0] > near[0] and left[1] > right[1]


def test_board_frame_round_trips_and_is_yawed_like_the_camera():
    assert layout.to_board(layout.to_world((0.3, 0.1))) == pytest.approx((0.3, 0.1))
    assert abs(layout.BOARD_YAW) > 0.05  # the real camera is not aligned with the robot axes


@pytest.mark.parametrize("color,box", [("white", "WHITE_BOX"), ("black", "BLACK_BOX")])
def test_seeds_sit_inside_their_own_open_top_box(model, color, box):
    seeds = layout.seed_positions(color)
    assert len(seeds) >= 2
    b = getattr(layout, box)
    for x, y, z in seeds:
        bx, by = layout.to_board((x, y))
        assert abs(bx - b.center[0]) < b.inner_half[0] and abs(by - b.center[1]) < b.inner_half[1]
        assert z < b.top_z
    names = [model.geom(i).name for i in range(model.ngeom) if model.geom(i).name.startswith(f"seed_{color}")]
    assert len(names) == len(seeds)
    rgba = model.geom(names[0]).rgba
    assert (rgba[:3].mean() > 0.8) == (color == "white")


def test_top_camera_vs_the_four_real_calibration_clicks_stays_within_the_documented_residual(model):
    """Each click pairs a pixel with the FK tool xyz. The arm-fitted pinhole camera misses them by 28-31 px (about
    3 cm: the real lens is distorted and the tool height varied per click), see sim/README.md. Guard that bound."""
    cam = model.camera("top")
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    pos, mat = data.cam_xpos[cam.id], data.cam_xmat[cam.id].reshape(3, 3)
    f = 0.5 * 480 / np.tan(np.radians(model.cam_fovy[cam.id]) / 2)
    for u, v, x, y in layout.CALIBRATION_POINTS:
        p = mat.T @ (np.array([x, y, layout.CALIBRATION_TOOL_Z]) - pos)
        pu, pv = 320 + f * p[0] / -p[2], 240 - f * p[1] / -p[2]
        assert np.hypot(pu - u, pv - v) < 65.0, (u, v, pu, pv)


def test_arm_joint_mapping_is_degrees_to_radians():
    assert deg_to_rad(180.0) == pytest.approx(np.pi)
    q = joints_to_qpos({"shoulder_pan": 90.0, "shoulder_lift": -45.0, "elbow_flex": 10.0, "wrist_flex": 0.0,
                        "wrist_roll": 3.0, "gripper": 0.0})
    assert q[0] == pytest.approx(np.pi / 2) and q[1] == pytest.approx(-np.pi / 4)


def test_gripper_map_is_linear_and_invertible_within_the_mjcf_range():
    lo, hi = GRIPPER_JAW_RAD
    assert gripper_to_jaw(0.0) == pytest.approx(lo)
    assert gripper_to_jaw(100.0) == pytest.approx(hi)
    assert gripper_to_jaw(50.0) == pytest.approx((lo + hi) / 2)
    for g in (0.0, 6.0, 30.0, 100.0):
        assert jaw_to_gripper(gripper_to_jaw(g)) == pytest.approx(g)
    assert np.degrees(hi - lo) == pytest.approx(128.6, abs=0.1)  # the follower calibration span for 0-100


def test_qpos_round_trip():
    joints = dict(zip(JOINTS, [10.0, -50.0, 40.0, 60.0, -3.0, 25.0]))
    back = qpos_to_joints(joints_to_qpos(joints))
    assert back == pytest.approx(joints)


def test_tool_site_matches_backend_forward_kinematics_within_a_millimetre(model, kin):
    data = mujoco.MjData(model)
    site = model.site("gripperframe").id
    rng = np.random.default_rng(0)
    for _ in range(20):
        joints = dict(zip(JOINTS, [*rng.uniform([-40, -100, -10, 20, -20], [50, 10, 96, 90, 20]), 10.0]))
        data.qpos[:6] = joints_to_qpos(joints)
        mujoco.mj_kinematics(model, data)
        assert np.linalg.norm(data.site_xpos[site] - np.array(kin.tool_xyz(joints))) < 1e-3
