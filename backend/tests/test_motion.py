import threading

import pytest

from smartseed_robot.motion import MotionConfig, move_to
from smartseed_robot.robot import FakeRobot


def test_move_reaches_target_with_speed_limited_steps():
    robot = FakeRobot()
    ok = move_to(robot, {"shoulder_pan": 30.0}, threading.Event(), MotionConfig(hz=10, max_speed=30))
    assert ok and robot.read_joints()["shoulder_pan"] == pytest.approx(30.0)
    assert 9 <= len(robot.commands) <= 11  # 30 deg at 30 deg/s and 10 Hz
    steps = [c["shoulder_pan"] for c in robot.commands]
    assert all(b - a <= 3.01 for a, b in zip([0.0, *steps], steps))


def test_move_to_current_position_still_sends_one_command():
    robot = FakeRobot()
    assert move_to(robot, {"shoulder_pan": 0.0}, threading.Event(), MotionConfig(hz=1000, max_speed=60))
    assert len(robot.commands) == 1


def test_stop_event_halts_within_one_step():
    stop = threading.Event()

    class Stopping(FakeRobot):
        def send_joints(self, target):
            super().send_joints(target)
            if len(self.commands) == 3:
                stop.set()

    robot = Stopping()
    assert not move_to(robot, {"shoulder_pan": 90.0}, stop, MotionConfig(hz=1000, max_speed=60))
    assert len(robot.commands) == 3
    assert robot.read_joints()["shoulder_pan"] < 90.0


def test_already_stopped_sends_nothing():
    stop = threading.Event()
    stop.set()
    robot = FakeRobot()
    assert not move_to(robot, {"shoulder_pan": 10.0}, stop, MotionConfig(hz=1000, max_speed=60))
    assert robot.commands == []
