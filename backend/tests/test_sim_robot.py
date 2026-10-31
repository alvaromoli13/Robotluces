"""SimRobot honours the RobotPort contract FakeRobot defines, plus the sim-only physics and recording."""
from __future__ import annotations

import numpy as np
import pytest

from smartseed_robot.api import build_runtime
from smartseed_robot.robot import CAMERAS, IMAGE_SHAPE, JOINTS, FakeRobot
from smartseed_robot.sim_robot import SimRobot

HOME = {"shoulder_pan": 1.0, "shoulder_lift": -103.0, "elbow_flex": 97.0, "wrist_flex": 72.0, "wrist_roll": 0.3,
        "gripper": 10.7}


@pytest.fixture(scope="module")
def sim():
    robot = SimRobot(initial=HOME)
    yield robot
    robot.close()


def make(kind):
    return FakeRobot(initial=HOME) if kind == "fake" else SimRobot(initial=HOME)


@pytest.fixture(params=["fake", "sim"])
def robot(request):
    r = make(request.param)
    yield r
    r.close()


def test_read_joints_has_every_joint_as_float(robot):
    joints = robot.read_joints()
    assert tuple(joints) == JOINTS or set(joints) == set(JOINTS)
    assert all(isinstance(v, float) for v in joints.values())


def test_observation_keys_shapes_and_dtypes(robot):
    obs = robot.read_observation()
    assert set(obs) == {"observation.state", *(f"observation.images.{c}" for c in CAMERAS)}
    assert obs["observation.state"].dtype == np.float32 and obs["observation.state"].shape == (len(JOINTS),)
    for cam in CAMERAS:
        img = obs[f"observation.images.{cam}"]
        assert img.shape == IMAGE_SHAPE and img.dtype == np.uint8


def test_observation_state_follows_joints_order(robot):
    state = robot.read_observation()["observation.state"]
    joints = robot.read_joints()
    assert state == pytest.approx([joints[j] for j in JOINTS], abs=1e-4)


def test_cameras_ok_and_reconnect_are_trivial(robot):
    assert robot.cameras_ok() is True
    robot.reconnect_cameras()
    assert robot.cameras_ok() is True


def test_torque_flags(robot):
    assert robot.torque_enabled is True
    robot.torque_off()
    assert robot.torque_enabled is False
    robot.torque_on()
    assert robot.torque_enabled is True


def test_send_partial_command_moves_that_joint(robot):
    for _ in range(40):
        robot.send_joints({"shoulder_pan": 5.0})
    assert robot.read_joints()["shoulder_pan"] == pytest.approx(5.0, abs=0.6)


def test_close_is_idempotent():
    r = SimRobot(initial=HOME)
    r.close()
    r.close()


def test_sim_starts_at_the_initial_pose_and_stays_there_without_commands():
    r = SimRobot(initial=HOME)
    before = r.read_joints()
    for j in JOINTS:
        assert before[j] == pytest.approx(HOME[j], abs=1e-6)
    r.close()


def test_sim_clamps_each_command_to_max_relative_target():
    r = SimRobot(initial=HOME, max_relative_target=8.0)
    r.send_joints({"shoulder_pan": 90.0})
    assert r.read_joints()["shoulder_pan"] - HOME["shoulder_pan"] <= 8.0 + 1e-6
    r.send_joints({"shoulder_pan": 90.0})
    assert r.read_joints()["shoulder_pan"] - HOME["shoulder_pan"] <= 16.0 + 1e-3
    r.close()


def test_sim_clamp_applies_to_the_gripper_units_too():
    r = SimRobot(initial=HOME, max_relative_target=8.0)
    r.send_joints({"gripper": 100.0})
    assert r.read_joints()["gripper"] <= HOME["gripper"] + 8.0 + 1e-6
    r.close()


def test_sim_converges_to_a_reachable_goal_in_a_second():
    r = SimRobot(initial=HOME)
    goal = {"shoulder_pan": 20.0, "shoulder_lift": -80.0, "elbow_flex": 80.0, "wrist_flex": 60.0, "wrist_roll": 5.0,
            "gripper": 30.0}
    for _ in range(30):
        r.send_joints(goal)
    for j, v in goal.items():
        assert r.read_joints()[j] == pytest.approx(v, abs=1.0), j
    r.close()


def test_each_command_advances_sim_time_by_one_control_period():
    r = SimRobot(initial=HOME, hz=30.0)
    t0 = r.sim_time
    for _ in range(30):
        r.send_joints({})
    assert r.sim_time - t0 == pytest.approx(1.0, abs=1e-6)
    r.close()


def test_torque_off_arm_does_not_follow_goals():
    r = SimRobot(initial=HOME)
    r.torque_off()
    for _ in range(10):
        r.send_joints({"shoulder_pan": 30.0})
    assert r.read_joints()["shoulder_pan"] == pytest.approx(HOME["shoulder_pan"], abs=1.0)
    r.close()


def test_torque_on_holds_where_the_arm_is_not_at_a_stale_goal():
    r = SimRobot(initial=HOME)
    r.torque_off()
    r.send_joints({"shoulder_pan": 30.0})
    r.torque_on()
    for _ in range(15):
        r.send_joints({})
    assert r.read_joints()["shoulder_pan"] == pytest.approx(HOME["shoulder_pan"], abs=1.0)
    r.close()


def test_rendered_cameras_show_something_and_differ(sim):
    obs = sim.read_observation()
    top, wrist = obs["observation.images.top"], obs["observation.images.wrist"]
    assert top.std() > 10 and wrist.std() > 5
    assert not np.array_equal(top, wrist)


def test_rendering_from_another_thread_works(sim):
    import threading

    out = {}
    t = threading.Thread(target=lambda: out.update(sim.read_observation()))
    t.start()
    t.join()
    assert out["observation.images.top"].shape == IMAGE_SHAPE


def test_closed_empty_jaws_read_like_the_real_follower():
    """Real closed-empty reads about 6.0 (episode minimum); the sim jaw stops at the same value."""
    r = SimRobot(initial=HOME)
    for _ in range(40):
        r.send_joints({"gripper": 0.0})
    assert r.read_joints()["gripper"] == pytest.approx(6.0, abs=0.3)
    r.close()


def test_sim_gripper_opens_to_the_commanded_value():
    r = SimRobot(initial=HOME)
    for _ in range(40):
        r.send_joints({"gripper": 60.0})
    assert r.read_joints()["gripper"] == pytest.approx(60.0, abs=0.5)
    r.close()


def test_recording_writes_one_mp4_per_plan(tmp_path):
    r = SimRobot(initial=HOME, record_dir=tmp_path)
    r.begin_plan("p1")
    for _ in range(5):
        r.send_joints({"shoulder_pan": 10.0})
    r.end_plan()
    files = list(tmp_path.glob("*.mp4"))
    assert [f.name for f in files] == ["plan-p1.mp4"] and files[0].stat().st_size > 1000
    r.close()


def test_factory_builds_a_sim_robot_from_the_env_mode(tmp_path):
    rt = build_runtime(mode="sim", data_dir=tmp_path)
    try:
        assert isinstance(rt.robot, SimRobot) and rt.mode == "sim"
    finally:
        rt.robot.close()


def test_factory_error_lists_the_sim_mode(tmp_path):
    with pytest.raises(ValueError, match="sim"):
        build_runtime(mode="bogus", data_dir=tmp_path)


def test_sim_mode_without_a_data_dir_uses_the_committed_sim_config(monkeypatch):
    monkeypatch.delenv("SMARTSEED_DATA_DIR", raising=False)
    rt = build_runtime(mode="sim")
    try:
        assert rt.calibration.fitted and rt.poses.get("home") is not None
        u, v = 320, 240
        x, y = rt.calibration.pixel_to_robot(u, v)
        assert 0.2 < x < 0.5 and abs(y) < 0.15  # the tray area in front of the arm
    finally:
        rt.robot.close()


def test_sim_config_is_in_sync_with_the_camera():
    import json

    from sim import make_config

    committed = json.loads((make_config.CONFIG_DIR / "calibration.json").read_text())
    assert committed == json.loads(json.dumps(make_config.calibration()))


def test_sim_config_ships_a_grasp_calibration_at_the_seed_centre_height(monkeypatch):
    import json

    from sim import layout, make_config

    committed = json.loads((make_config.CONFIG_DIR / "grasp_calibration.json").read_text())
    assert committed == json.loads(json.dumps(make_config.grasp_calibration()))
    monkeypatch.delenv("SMARTSEED_DATA_DIR", raising=False)
    rt = build_runtime(mode="sim")
    try:
        assert rt.grasp_calibration.fitted and rt.executor.status()["grasp_calibrated"] is True
        seed_z = layout.BLACK_BOX.floor_z + sum(layout.SEED_RADIUS.values()) / 2
        assert rt.grasp_calibration.mean_z == pytest.approx(seed_z, abs=1e-4)
    finally:
        rt.robot.close()
