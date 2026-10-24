from smartseed_robot.robot import ARM_JOINTS, JOINTS, FakeRobot


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
