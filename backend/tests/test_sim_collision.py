"""Walls of the boxes and the tray stop every jaw geom, and the wall monitor tells a clean episode from a pass-through.

Hardware-free: the twin's physics, no rendering, no network.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest

from sim import collision, grasp_test, layout
from smartseed_robot.robot import JOINTS
from smartseed_robot.sim_robot import SimRobot, joints_to_qpos

JAW_GEOMS = ("pad_fixed", "pad_moving")  # plus the two jaw hulls, found by body below


@pytest.fixture(scope="module")
def model():
    return mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))


def pair_collides(m, a: int, b: int) -> bool:
    """MuJoCo's contact filter for two geoms of different bodies."""
    return bool(m.geom_contype[a] & m.geom_conaffinity[b]) or bool(m.geom_contype[b] & m.geom_conaffinity[a])


def jaw_geoms(m) -> dict[str, int]:
    """Every collision geom of the two jaws: the fixed-jaw hull (`wrist_roll_follower`), the moving-jaw hull and the pads."""
    out = {name: m.geom(name).id for name in JAW_GEOMS}
    fixed = m.body("gripper").id
    moving = m.body("moving_jaw_so101_v1").id
    for g in range(m.ngeom):
        if m.geom_group[g] == 3 and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and m.geom_bodyid[g] in (fixed, moving):
            if m.mesh(m.geom_dataid[g]).name in ("moving_jaw_so101_v1", "wrist_roll_follower_so101_v1"):
                out[f"hull:{m.mesh(m.geom_dataid[g]).name}"] = g
    return out


def test_wall_geoms_are_the_box_and_tray_walls_but_not_the_floors(model):
    names = {model.geom(g).name for g in collision.wall_geoms(model)}
    assert {"box_white_wall_far", "box_black_wall_left", "tray_wall_near", "tray_div_row1", "tray_div_col2"} <= names
    assert not any("floor" in n for n in names) and not {"mat", "paper", "table"} & names
    assert len(names) == 4 + 4 + 4 + 3 + 2


def test_every_jaw_geom_collides_with_every_wall_but_with_no_floor(model):
    walls = collision.wall_geoms(model)
    floors = [model.geom(n).id for n in ("box_white_floor", "box_black_floor", "tray_floor", "mat", "paper", "table")]
    jaws = jaw_geoms(model)
    assert {"pad_fixed", "pad_moving", "hull:moving_jaw_so101_v1", "hull:wrist_roll_follower_so101_v1"} <= set(jaws)
    for name, g in jaws.items():
        for w in walls:
            assert pair_collides(model, g, w), (name, model.geom(w).name)
        if name != "hull:wrist_roll_follower_so101_v1":  # the fixed hull always hit the box floors, the others never did
            for f in floors:
                assert not pair_collides(model, g, f), (name, model.geom(f).name)


def test_the_rest_of_the_arm_still_collides_with_the_walls(model):
    arm = collision.arm_geoms(model)
    assert len(arm) >= 15
    walls = collision.wall_geoms(model)
    assert all(pair_collides(model, a, w) for a in arm for w in walls)


def put_wall_on(m, d, wall: str, geom: int) -> None:
    """Slide the box or tray holding `wall` so that the wall's centre coincides with the world position of `geom`."""
    w = m.geom(wall).id
    body, board = m.geom_bodyid[w], m.body("board").id
    centre = d.geom_xpos[geom].copy()
    if m.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH:  # the frame of a mesh geom can lie outside its hull: use a point inside
        mesh = m.geom_dataid[geom]
        verts = m.mesh_vert[m.mesh_vertadr[mesh]:m.mesh_vertadr[mesh] + m.mesh_vertnum[mesh]]
        centre += d.geom_xmat[geom].reshape(3, 3) @ verts.mean(axis=0)
    m.body_pos[body] += d.xmat[board].reshape(3, 3).T @ (centre - d.geom_xpos[w])
    mujoco.mj_forward(m, d)


@pytest.mark.parametrize("name", ["pad_fixed", "pad_moving", "hull:moving_jaw_so101_v1", "hull:wrist_roll_follower_so101_v1"])
def test_a_wall_through_any_jaw_geom_makes_a_contact_the_monitor_reports(name):
    robot = SimRobot()
    try:
        m, d = robot._model, robot._data
        g = jaw_geoms(m)[name]
        mon = collision.WallMonitor(m)
        put_wall_on(m, d, "box_white_wall_far", g)
        pairs = {(d.contact[i].geom1, d.contact[i].geom2) for i in range(d.ncon)}
        wall = m.geom("box_white_wall_far").id
        assert (g, wall) in pairs or (wall, g) in pairs
        mon(m, d)
        report = mon.report()
        assert report.contact_steps == 1 and report.max_penetration_m > 0.001
        assert not report.valid
    finally:
        robot.close()


def test_a_clean_pose_reports_no_wall_contact():
    robot = SimRobot()
    try:
        mon = collision.WallMonitor(robot._model)
        for _ in range(5):
            robot.send_joints({})
            mon(robot._model, robot._data)
        report = mon.report()
        assert report.contact_steps == 0 and report.max_penetration_m == 0.0 and report.max_force_n == 0.0
        assert report.valid
    finally:
        robot.close()


def test_geometry_mode_flags_a_pass_through_even_when_the_collision_bits_are_off():
    """The audit of the old v1 scenes: there the moving jaw hull and the pads did not collide with walls at all."""
    robot = SimRobot()
    try:
        m, d = robot._model, robot._data
        g = jaw_geoms(m)["hull:moving_jaw_so101_v1"]
        m.geom_contype[g] = 0
        m.geom_conaffinity[g] = 0
        mon = collision.WallMonitor(m, mode="geometry")
        put_wall_on(m, d, "box_white_wall_far", g)
        assert not any({d.contact[i].geom1, d.contact[i].geom2} >= {g} for i in range(d.ncon))  # physics sees nothing
        mon(m, d)
        report = mon.report()
        assert report.max_penetration_m > 0.001 and not report.valid
    finally:
        robot.close()


def test_min_wall_distance_is_signed_and_positive_in_free_space():
    robot = SimRobot()
    try:
        m, d = robot._model, robot._data
        assert collision.min_wall_distance(m, d) > 0.02
        g = jaw_geoms(m)["pad_moving"]
        put_wall_on(m, d, "tray_wall_far", g)
        assert collision.min_wall_distance(m, d) < -0.001
    finally:
        robot.close()


def drive_tool_at_a_wall(kin, wall_xy_board, side: float, spin: float = 0.0, z: float = 0.012):
    """Hold the tool 4 cm in front of a wall of the white box, then push it 4 cm through the wall; returns the report
    and the signed distance of the tool past the wall plane at the end."""
    robot = SimRobot()
    try:
        m = robot._model
        mon = collision.WallMonitor(m)
        robot.step_hook = mon
        start = layout.to_world((wall_xy_board[0] - side * 0.04, wall_xy_board[1]))
        end = layout.to_world((wall_xy_board[0] + side * 0.04, wall_xy_board[1]))
        sol = grasp_test._move(robot, kin, [*start, 0.06], robot.read_joints(), 10.0, spin)
        sol = grasp_test._move(robot, kin, [*start, z], sol, 10.0, spin)
        mon.reset()
        grasp_test._move(robot, kin, [*end, z], sol, 10.0, spin)
        tool = layout.to_board(grasp_test.tool_xyz(robot)[:2])
        return mon.report(), side * (tool[0] - wall_xy_board[0])
    finally:
        robot.close()


def test_a_tool_pushed_through_a_box_wall_is_stopped_by_it(kin):
    wall = (layout.WHITE_BOX.center[0] - layout.WHITE_BOX.outer_half[0] + layout.WHITE_BOX.wall / 2, layout.WHITE_BOX.center[1])
    report, past = drive_tool_at_a_wall(kin, wall, side=+1)  # from the base side towards the box
    assert report.contact_steps > 0  # it did touch ...
    assert report.max_penetration_m <= 0.001, report  # ... and the wall held it to a millimetre
    assert past < 0.012  # the tool is still on this side of the wall (the jaw hull sticks out in front of it)
