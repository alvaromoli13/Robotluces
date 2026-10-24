import threading

import pytest

from smartseed_robot.calibration import Calibration
from smartseed_robot.executor import Executor, ExecutorConfig, PlanBusy, PlanError
from smartseed_robot.poses import PoseStore
from smartseed_robot.robot import FakeRobot

SIZE = (640, 480)
HOME = {"shoulder_pan": 0.0, "shoulder_lift": -30.0, "elbow_flex": 60.0, "wrist_flex": 30.0, "wrist_roll": 0.0,
        "gripper": 60.0}
CONFIG = ExecutorConfig(hz=1000, max_speed=10_000, settle_s=0.0)


def robot_xy(u, v):
    return 0.15 + u * 0.00012, (v - 240) * 0.0004


def make_poses(tmp_path, colors=("red", "yellow", "green", "purple")):
    store = PoseStore(tmp_path / "poses.json")
    store.set("home", dict(HOME))
    for i, color in enumerate(colors):
        store.set(f"above_box_{color}", {**HOME, "shoulder_pan": 40.0 + 10 * i, "shoulder_lift": -10.0})
    return store


def make_calibration():
    cal = Calibration()
    for u, v in [(50, 60), (590, 70), (600, 420), (40, 430), (320, 240)]:
        cal.add_point(u, v, *robot_xy(u, v), image_size=SIZE)
    cal.fit()
    return cal


def cell(i, color="red", u=320, v=240):
    return {"cell_index": i, "row": i // 4, "col": i % 4, "color": color, "u": u, "v": v}


@pytest.fixture
def parts(tmp_path, kin):
    robot = FakeRobot(initial=HOME)
    return robot, Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)


def types(executor):
    return [e["type"] for e in executor.events]


def test_plan_runs_every_cell_in_order_and_ends_home(parts):
    robot, ex = parts
    ex.run([cell(0, "red"), cell(1, "green", 100, 300)], SIZE)
    assert types(ex) == ["plan_started", "cell_started", "cell_done", "cell_started", "cell_done", "finished"]
    assert ex.status()["done"] == [0, 1] and ex.status()["failed"] == []
    assert ex.status()["state"] == "idle" and ex.status()["plan_id"] == ex.events[0]["plan_id"]
    assert robot.read_joints() == pytest.approx(HOME)
    assert robot.torque_enabled


def test_robot_visits_the_box_pose_and_the_ik_pose_above_the_cell(parts, kin):
    robot, ex = parts
    ex.run([cell(0, "green", 100, 300)], SIZE)
    arm = lambda s: {k: v for k, v in s.items() if k != "gripper"}  # noqa: E731
    box = {k: v for k, v in ex.poses.get("above_box_green").items() if k != "gripper"}
    assert any(arm(s) == pytest.approx(box) for s in robot.history)
    target = (*robot_xy(100, 300), CONFIG.drop_z)
    assert any(kin.tool_xyz(arm(s)) == pytest.approx(target, abs=0.003) for s in robot.history)


def test_gripper_is_open_at_the_drop_and_closed_on_the_way(parts, kin):
    robot, ex = parts
    ex.run([cell(0)], SIZE)
    target = (*robot_xy(320, 240), CONFIG.drop_z)
    at_drop = [s for s in robot.history
               if kin.tool_xyz({k: v for k, v in s.items() if k != "gripper"}) == pytest.approx(target, abs=0.003)]
    assert CONFIG.empty_below < at_drop[0]["gripper"] < CONFIG.gripper_open  # seed held while travelling
    assert at_drop[-1]["gripper"] == CONFIG.gripper_open


def test_empty_grasp_retries_once_then_succeeds(tmp_path, kin):
    robot = FakeRobot(initial=HOME, grasp_script=[False, True])
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0)], SIZE)
    assert types(ex) == ["plan_started", "cell_started", "cell_done", "finished"]
    assert ex.retries == [0]


def test_two_empty_grasps_mark_the_cell_failed_and_continue(tmp_path, kin):
    robot = FakeRobot(initial=HOME, grasp_script=[False, False])
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0), cell(1)], SIZE)
    assert types(ex) == ["plan_started", "cell_started", "cell_failed", "cell_started",
                         "cell_done", "finished"]
    assert ex.status()["failed"] == [0] and ex.status()["done"] == [1]
    assert robot.read_joints() == pytest.approx(HOME)


def test_events_carry_cell_identity(parts):
    _, ex = parts
    ex.run([cell(5, "purple")], SIZE)
    started = ex.events[1]
    assert started["cell_index"] == 5 and started["color"] == "purple" and started["message"] is None
    assert set(ex.events[0]) >= {"type", "plan_id", "cell_index", "message"}


def test_stop_halts_within_one_step_and_keeps_torque(tmp_path, kin):
    stop_at = 40

    class Stopping(FakeRobot):
        def send_joints(self, target):
            super().send_joints(target)
            if len(self.commands) == stop_at:
                ex.stop()

    robot = Stopping(initial=HOME)
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin,
                  config=ExecutorConfig(hz=1000, max_speed=60, settle_s=0.0))
    ex.run([cell(0), cell(1)], SIZE)
    assert len(robot.commands) == stop_at
    assert types(ex)[-1] == "stopped" and "finished" not in types(ex)
    assert robot.torque_enabled and not ex.running


def test_start_runs_in_background_and_refuses_a_second_plan(tmp_path, kin):
    gate = threading.Event()

    class Gated(FakeRobot):
        def send_joints(self, target):
            gate.wait(5)
            super().send_joints(target)

    ex = Executor(Gated(initial=HOME), make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.start([cell(0)], SIZE)
    assert ex.running
    with pytest.raises(PlanBusy) as err:
        ex.start([cell(1)], SIZE)
    assert err.value.code == "busy" and ex.status()["state"] == "running"
    gate.set()
    assert ex.join(10)
    assert types(ex)[-1] == "finished"


def test_unexpected_exception_emits_error_and_does_not_cut_torque(tmp_path, kin):
    class Broken(FakeRobot):
        def send_joints(self, target):
            raise OSError("bus down")

    robot = Broken(initial=HOME)
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0)], SIZE)
    assert types(ex)[-1] == "error" and "bus down" in ex.events[-1]["message"]
    assert ex.status()["state"] == "error"
    assert robot.torque_enabled and not ex.running


def test_missing_pose_is_a_conflict(tmp_path, kin):
    poses = make_poses(tmp_path, colors=("red",))
    ex = Executor(FakeRobot(initial=HOME), poses, make_calibration(), kin, config=CONFIG)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0, "green")], SIZE)
    assert err.value.status == 409 and err.value.code == "missing_pose" and "above_box_green" in err.value.detail


def test_missing_calibration_is_a_conflict(tmp_path, kin):
    ex = Executor(FakeRobot(initial=HOME), make_poses(tmp_path), Calibration(), kin, config=CONFIG)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0)], SIZE)
    assert err.value.status == 409 and err.value.code == "no_calibration"


@pytest.mark.parametrize("bad", [[], [cell(0, "blue")], [{"cell_index": 0, "color": "red"}]])
def test_invalid_plans_are_unprocessable(parts, bad):
    _, ex = parts
    with pytest.raises(PlanError) as err:
        ex.run(bad, SIZE)
    assert err.value.status == 422


def test_unreachable_cell_is_rejected_before_any_motion(parts):
    robot, ex = parts
    with pytest.raises(PlanError) as err:
        ex.run([cell(0), cell(1, u=5000, v=240)], SIZE)  # far outside the arm's reach
    assert err.value.status == 422 and "1" in err.value.detail
    assert robot.commands == []
