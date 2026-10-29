"""T5f: the arm stops at the table, the paper and the mat, and the monitor rejects an episode that sinks into them.

Hardware-free: the twin's physics, no rendering, no network.
"""
from __future__ import annotations

import json

import mujoco
import numpy as np
import pytest

from sim import collision, make_dataset as md
from sim.run_policy import load_act_start
from smartseed_robot.robot import JOINTS
from smartseed_robot.sim_robot import SimRobot, joints_to_qpos

GROUND = ("table", "paper", "mat")
POSES = json.loads((md.CONFIG_DIR / "poses.json").read_text())


def ground_contacts(m, d) -> list[tuple[str, str, float]]:
    """(arm geom, ground geom, dist) of every arm-vs-table/paper/mat contact of the current state."""
    arm, ground = set(collision.arm_geoms(m)), set(collision.table_geoms(m))
    out = []
    for i in range(d.ncon):
        c = d.contact[i]
        a, b = (c.geom1, c.geom2) if c.geom1 in arm else (c.geom2, c.geom1)
        if a in arm and b in ground:
            out.append((m.geom(a).name or m.body(m.geom_bodyid[a]).name, m.geom(b).name, float(c.dist)))
    return out


def pushed_down(joints: dict[str, float], by_deg: float = 25.0) -> dict[str, float]:
    """A target that drives the jaws well below the table (the servo cannot get there)."""
    return joints | {"wrist_flex": joints["wrist_flex"] + by_deg, "shoulder_lift": joints["shoulder_lift"] + by_deg}


def test_table_geoms_are_the_table_the_paper_and_the_mat_only():
    robot = SimRobot()
    try:
        names = {robot._model.geom(g).name for g in collision.table_geoms(robot._model)}
        assert names == set(GROUND)
    finally:
        robot.close()


def test_every_arm_geom_collides_with_the_table_the_paper_and_the_mat():
    robot = SimRobot()
    try:
        m = robot._model
        for a in collision.arm_geoms(m):
            for g in collision.table_geoms(m):
                assert m.geom_contype[a] & m.geom_conaffinity[g] or m.geom_contype[g] & m.geom_conaffinity[a], (a, g)
                body_bits = m.body_conaffinity[m.geom_bodyid[g]]  # the broad phase filters on the body-level bits
                assert m.geom_contype[a] & body_bits, (a, g)
    finally:
        robot.close()


def test_seeds_still_rest_on_the_ground_and_the_scene_geoms_do_not_hit_the_ground_as_arm_geoms_do():
    robot = SimRobot()
    try:
        m = robot._model
        seed, table = m.geom("seed_white_0_geom").id, m.geom("table").id
        assert m.geom_contype[seed] & m.geom_conaffinity[table] or m.geom_contype[table] & m.geom_conaffinity[seed]
    finally:
        robot.close()


def test_a_pose_pushed_below_the_table_makes_contacts_with_bounded_penetration():
    robot = SimRobot(initial=POSES["act_start"])
    try:
        m, d = robot._model, robot._data
        mon = robot.step_hook = collision.WallMonitor(m)
        target = pushed_down(load_act_start())
        for _ in range(60):
            robot.send_joints(target)
        assert ground_contacts(m, d), "the arm is below the table but nothing touches it"
        report = mon.report()
        assert report.table_contact_steps > 0
        assert 0.0 < report.table_max_penetration_m <= collision.MAX_TABLE_PENETRATION_M
        assert report.valid
    finally:
        robot.close()


def test_the_monitor_rejects_an_arm_forced_through_the_table():
    robot = SimRobot(initial=POSES["act_start"])
    try:
        m, d = robot._model, robot._data
        mon = collision.WallMonitor(m)
        adr = [m.joint(j).qposadr[0] for j in JOINTS]
        d.qpos[adr] = joints_to_qpos(pushed_down(load_act_start(), 12.0))
        mujoco.mj_forward(m, d)
        mon(m, d)
        report = mon.report()
        assert report.table_max_penetration_m > collision.MAX_TABLE_PENETRATION_M
        assert not report.table_valid and report.wall_valid and not report.valid
        assert report.as_info()["table_max_penetration_mm"] > 1000 * collision.MAX_TABLE_PENETRATION_M
    finally:
        robot.close()


def test_a_rollout_that_sinks_into_the_table_is_invalid_and_gets_its_own_reason(kin, monkeypatch):
    """The contact is stiff (the servo's push sinks the jaw 0.5 mm at most), so the rollout is judged against a 0.2 mm
    limit here; the monitor test above uses the real 2 mm limit on a pose forced through the table."""
    monkeypatch.setattr(collision, "MAX_TABLE_PENETRATION_M", 0.0002)
    p = md.sample_params("black", seed=0, attempt=0)
    start = np.array([load_act_start()[j] for j in JOINTS])
    deep = pushed_down(dict(zip(JOINTS, start)), 12.0)
    actions = np.tile(start, (40, 1))
    actions[10:] = [deep[j] for j in JOINTS]
    run = md.simulate_episode(p, kin, render=False, plan=(actions.astype(np.float32), {"descend_start": 10}))
    assert run.info["table_max_penetration_mm"] > 1000 * collision.MAX_TABLE_PENETRATION_M > 0
    assert not run.valid
    assert "table" in md.invalid_reason(run.info) and "wall" not in md.invalid_reason(run.info)


def test_the_wall_reason_is_unchanged():
    reason = md.invalid_reason({"wall_max_penetration_mm": 3.0, "wall_max_force_n": 5.0, "table_max_penetration_mm": 0.0})
    assert reason == "collision: arm 3.0 mm into a wall, 5 N"


@pytest.mark.parametrize("pose", ["act_start", "home"])
def test_the_taught_poses_of_the_sim_do_not_penetrate_the_table(pose):
    robot = SimRobot(initial=POSES[pose])
    try:
        m, d = robot._model, robot._data
        mujoco.mj_forward(m, d)
        assert all(dist >= 0 for _, _, dist in ground_contacts(m, d))
        mon = robot.step_hook = collision.WallMonitor(m)
        for _ in range(30):
            robot.send_joints(POSES[pose])
        assert mon.report().table_max_penetration_m <= 0.0005
    finally:
        robot.close()


def test_the_v5_dart_datasets_have_their_own_name():
    assert md.dataset_name("black", "narrow", dart=True) == "smartseed-sim-grasp-black-v5-dart"
    assert md.dataset_name("white", "narrow", dart=True) == "smartseed-sim-grasp-white-v5-dart"


def test_the_audit_reports_penetration_of_recorded_states_and_zero_for_a_clean_pose():
    from sim import audit_table

    robot = SimRobot()
    try:
        m, d = robot._model, robot._data
        clean = np.array([POSES["act_start"][j] for j in JOINTS], np.float32)
        sunk = np.array([pushed_down(POSES["act_start"], 12.0)[j] for j in JOINTS], np.float32)
        result = audit_table.episode_penetrations(m, d, np.stack([clean, clean, sunk, sunk]), np.array([0, 0, 1, 1]))
        assert result[0][0] == 0.0 and result[0][1] == 0.0
        assert result[1][0] > 0.002 and result[1][1] > 0.002 and result[1][2]
        text = audit_table.summarise(result)
        assert "episodes 2" in text and ">2 mm 1" in text
    finally:
        robot.close()


def test_a_start_pose_a_few_mm_under_the_table_is_pushed_out_and_is_not_an_episode_rejection(kin):
    """The start noise can place the arm a few mm into the table; the placement is not a motion, the servo and the
    stiff contact lift it out, and only what happens afterwards counts."""
    p = md.sample_params("black", seed=0, attempt=0)
    start = {j: load_act_start()[j] for j in JOINTS}
    low = start | {"elbow_flex": start["elbow_flex"] + 2.0}
    actions = np.tile([low[j] for j in JOINTS], (60, 1)).astype(np.float32)
    run = md.simulate_episode(p, kin, render=False, plan=(actions, {"descend_start": 30}))
    assert run.info["table_max_penetration_mm"] <= 1000 * collision.MAX_TABLE_PENETRATION_M
