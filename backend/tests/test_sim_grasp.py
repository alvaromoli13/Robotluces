"""Contact-physics grasp in the twin: the jaws close on a seed and lift it by friction alone (no weld, no attach)."""
from __future__ import annotations

import mujoco
import numpy as np
import pytest

from sim import grasp_test, layout
from smartseed_robot.sim_robot import SimRobot

# Real follower readings (datasets d1-clean / d2-clean, 96 + 91 episodes): holding a black seed 6.9 (6.1 closed
# empty), holding a white one 7.4. The sim jaw stops at 6.0 empty.
BLACK_READING, WHITE_READING = (6.5, 7.5), (7.0, 8.0)


@pytest.fixture(scope="module")
def model():
    return mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))


def grasp(kin, color, jitter=(0.0, 0.0), index=2):
    robot = SimRobot()
    try:
        return grasp_test.run_trial(robot, kin, color, jitter, index=index)
    finally:
        robot.close()


def test_the_grasp_has_no_weld_equality_or_mocap_trick(model):
    assert model.neq == 0 and model.nmocap == 0
    for color in ("black", "white"):
        body = model.body(f"seed_{color}_2")
        assert model.jnt_type[body.jntadr[0]] == mujoco.mjtJoint.mjJNT_FREE


def test_both_jaws_have_fingertip_pads_that_are_the_only_arm_geoms_touching_seeds(model):
    seed = model.geom("seed_black_2_geom")
    touches = []
    for g in range(model.ngeom):
        if model.geom_bodyid[g] in (model.body("gripper").id, model.body("moving_jaw_so101_v1").id) or \
                model.body(model.geom_bodyid[g]).name in ("gripper", "moving_jaw_so101_v1"):
            hit = bool(seed.contype[0] & model.geom_conaffinity[g]) or bool(model.geom_contype[g] & seed.conaffinity[0])
            if hit:
                touches.append(model.geom(g).name)
    assert sorted(touches) == ["pad_fixed", "pad_moving"]


def test_closed_empty_jaws_still_stop_at_the_real_reading():
    robot = SimRobot()
    for _ in range(60):
        robot.send_joints({"gripper": 4.5})
    assert robot.read_joints()["gripper"] == pytest.approx(6.0, abs=0.3)
    robot.close()


@pytest.mark.parametrize("color,band", [("black", BLACK_READING), ("white", WHITE_READING)])
def test_closing_on_a_seed_stops_the_jaw_at_the_real_reading(kin, color, band):
    reading = grasp(kin, color).gripper
    assert band[0] <= reading <= band[1], reading
    assert reading > 6.4  # the seed, not the joint stop, holds the jaw open


@pytest.mark.parametrize("color", ["black", "white"])
def test_seed_rises_with_the_arm_and_stays_between_the_jaws_for_two_seconds(kin, color):
    trial = grasp(kin, color)
    assert trial.lift_mm > 30.0  # lifted more than 3 cm ...
    assert trial.slip_mm < 8.0  # ... and still where the jaws closed on it after the 2 s hold
    assert trial.success


@pytest.mark.parametrize("color", ["black", "white"])
def test_grasp_tolerates_a_3_mm_seed_placement_error(kin, color):
    for jitter in ((0.003, 0.003), (-0.003, 0.003), (0.003, -0.003), (-0.003, -0.003)):
        assert grasp(kin, color, jitter).success, jitter


def test_the_grasp_is_deterministic(kin):
    a, b = grasp(kin, "black", (0.002, -0.001)), grasp(kin, "black", (0.002, -0.001))
    assert (a.lift_mm, a.slip_mm, a.gripper) == (b.lift_mm, b.slip_mm, b.gripper)


def test_replaying_the_recorded_grasp_actions_lifts_the_black_seed_it_was_recorded_on():
    """Episode 0 of d1-clean closes on black seed 0; its recorded actions through the physics carry it away."""
    from smartseed_robot.robot import JOINTS

    npz = np.load(layout.SIM_DIR / "config" / "ep0_actions.npz")
    robot = SimRobot(initial=dict(zip(JOINTS, npz["state"][0].tolist())))
    adr = robot._model.joint("seed_black_0_free").qposadr[0]
    z0, top = robot._data.qpos[adr + 2], 0.0
    for action in npz["action"]:
        robot.send_joints(dict(zip(JOINTS, action.astype(float).tolist())))
        top = max(top, robot._data.qpos[adr + 2] - z0)
    robot.close()
    assert top > 0.03
