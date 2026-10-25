import types

import pytest

from smartseed_robot.robot import ARM_JOINTS, JOINTS, CameraUnavailable, FakeRobot, LeRobotFollower


def test_fake_robot_defaults_and_partial_commands():
    robot = FakeRobot()
    assert set(robot.read_joints()) == set(JOINTS)
    robot.send_joints({"shoulder_pan": 12.0})
    assert robot.read_joints()["shoulder_pan"] == 12.0
    assert robot.read_joints()["elbow_flex"] == 0.0
    assert robot.commands == [{"shoulder_pan": 12.0}]


def test_read_joints_returns_a_copy():
    robot = FakeRobot()
    robot.read_joints()["gripper"] = 99
    assert robot.read_joints()["gripper"] != 99


def test_empty_grasp_closes_fully_and_full_grasp_stops_on_the_seed():
    robot = FakeRobot(grasp_script=[False, True])
    robot.send_joints({"gripper": 60})
    robot.send_joints({"gripper": 0})
    assert robot.read_joints()["gripper"] == 0
    robot.send_joints({"gripper": 60})
    robot.send_joints({"gripper": 0})
    assert robot.read_joints()["gripper"] > 8


def test_closing_in_steps_consumes_one_script_entry():
    robot = FakeRobot(grasp_script=[False, True])
    for value in (60, 30, 9, 5, 0):
        robot.send_joints({"gripper": value})
    assert robot.read_joints()["gripper"] == 0
    robot.send_joints({"gripper": 60})
    for value in (9, 0):
        robot.send_joints({"gripper": value})
    assert robot.read_joints()["gripper"] > 8


def test_torque_off_and_close_are_recorded():
    robot = FakeRobot()
    assert robot.torque_enabled
    robot.torque_off()
    robot.close()
    assert not robot.torque_enabled and robot.closed


def test_arm_joints_exclude_gripper():
    assert "gripper" not in ARM_JOINTS and JOINTS[-1] == "gripper"


def test_history_keeps_full_state_after_each_command():
    robot = FakeRobot()
    robot.send_joints({"shoulder_pan": 5.0})
    robot.send_joints({"elbow_flex": 9.0})
    assert [h["shoulder_pan"] for h in robot.history] == [5.0, 5.0]
    assert robot.history[-1]["elbow_flex"] == 9.0


def test_fake_robot_ignores_commands_without_torque_and_torque_on_restores_them():
    robot = FakeRobot(initial={"shoulder_pan": 10.0})
    robot.torque_off()
    robot.send_joints({"shoulder_pan": 50.0})
    assert robot.read_joints()["shoulder_pan"] == 10.0
    robot.torque_on()
    assert robot.torque_enabled
    robot.send_joints({"shoulder_pan": 50.0})
    assert robot.read_joints()["shoulder_pan"] == 50.0


def test_fake_robot_dead_cameras_fail_the_observation_until_reconnected():
    robot = FakeRobot()
    robot.drop_cameras()
    assert not robot.cameras_ok()
    with pytest.raises(RuntimeError, match="read thread is not running"):
        robot.read_observation()
    robot.reconnect_cameras()
    assert robot.cameras_ok() and robot.reconnects == 1
    assert "observation.images.top" in robot.read_observation()


def test_fake_robot_reconnect_can_fail():
    robot = FakeRobot()
    robot.drop_cameras(reconnectable=False)
    with pytest.raises(CameraUnavailable):
        robot.reconnect_cameras()


class FakeCam:
    def __init__(self, name, log, connect_failures=0, alive=True):
        self.name, self.log, self.failures, self.alive = name, log, connect_failures, alive

    @property
    def is_connected(self):
        return self.alive

    @property
    def thread(self):
        return types.SimpleNamespace(is_alive=lambda: self.alive)

    def disconnect(self):
        self.log.append(f"disconnect {self.name}")
        self.alive = False

    def connect(self):
        self.log.append(f"connect {self.name}")
        if self.failures:
            self.failures -= 1
            raise ConnectionError("no frames")
        self.alive = True


def follower(cams):
    f = object.__new__(LeRobotFollower)
    f._robot = types.SimpleNamespace(cameras=cams)
    return f


def test_follower_cameras_ok_needs_every_read_thread_alive():
    log = []
    assert follower({"top": FakeCam("top", log), "wrist": FakeCam("wrist", log)}).cameras_ok()
    assert not follower({"top": FakeCam("top", log), "wrist": FakeCam("wrist", log, alive=False)}).cameras_ok()


def test_follower_reconnect_reopens_every_camera_with_the_same_objects():
    log = []
    f = follower({"top": FakeCam("top", log, alive=False), "wrist": FakeCam("wrist", log)})
    f.reconnect_cameras(sleep=lambda s: None)
    assert log == ["disconnect top", "connect top", "disconnect wrist", "connect wrist"]
    assert f.cameras_ok()


def test_follower_reconnect_retries_with_backoff_then_succeeds():
    log, naps = [], []
    f = follower({"top": FakeCam("top", log, connect_failures=2, alive=False)})
    f.reconnect_cameras(attempts=3, backoff_s=0.5, sleep=naps.append)
    assert f.cameras_ok() and naps == [0.5, 1.0]


def test_follower_reconnect_gives_up_with_camera_unavailable():
    log, naps = [], []
    f = follower({"top": FakeCam("top", log, connect_failures=9, alive=False)})
    with pytest.raises(CameraUnavailable, match="top"):
        f.reconnect_cameras(attempts=3, backoff_s=0.1, sleep=naps.append)
    assert log.count("connect top") == 3 and len(naps) == 2
