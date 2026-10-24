import threading

import pytest

from smartseed_robot.act import ACT_START_FALLBACK, ActConfig, ActGrasp
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
    assert types(ex) == ["plan_started", "cell_started", "drop_pose", "cell_done", "cell_started", "drop_pose", "cell_done", "finished"]
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
    assert types(ex) == ["plan_started", "cell_started", "drop_pose", "cell_done", "finished"]
    assert ex.retries == [0]


def test_two_empty_grasps_still_release_over_the_cell_and_count_it_done(tmp_path, kin):
    robot = FakeRobot(initial=HOME, grasp_script=[False, False])
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0), cell(1)], SIZE)
    assert types(ex) == ["plan_started", "cell_started", "drop_pose", "cell_done", "cell_started", "drop_pose", "cell_done", "finished"]
    assert ex.status()["done"] == [0, 1] and ex.status()["failed"] == []
    first, second = [e for e in ex.events if e["type"] == "cell_done"]
    assert first["empty"] is True and "empty" in first["message"]
    assert not second.get("empty")
    target = (*robot_xy(320, 240), CONFIG.drop_z)
    at_drop = [s for s in robot.history
               if kin.tool_xyz({k: v for k, v in s.items() if k != "gripper"}) == pytest.approx(target, abs=0.003)]
    assert at_drop and at_drop[-1]["gripper"] == CONFIG.gripper_open
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


def test_user_defined_colour_without_taught_pose_is_a_conflict(parts):
    _, ex = parts
    with pytest.raises(PlanError) as err:
        ex.run([cell(0, "blue")], SIZE)
    assert err.value.status == 409 and err.value.code == "missing_pose" and "above_box_blue" in err.value.detail


def test_user_defined_colour_with_taught_pose_is_planted(tmp_path, kin):
    poses = make_poses(tmp_path, colors=("red", "orange"))
    robot = FakeRobot(initial=HOME)
    ex = Executor(robot, poses, make_calibration(), kin, config=CONFIG)
    ex.run([cell(0, "orange")], SIZE)
    assert types(ex)[-1] == "finished" and "cell_done" in types(ex)


def test_missing_calibration_is_a_conflict(tmp_path, kin):
    ex = Executor(FakeRobot(initial=HOME), make_poses(tmp_path), Calibration(), kin, config=CONFIG)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0)], SIZE)
    assert err.value.status == 409 and err.value.code == "no_calibration"


@pytest.mark.parametrize("bad", [[], [cell(0, "Blue!")], [cell(0, "")], [{"cell_index": 0, "color": "red"}]])
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


# -- ACT grasp ---------------------------------------------------------------------------------------------
POLICY_ROLL = 77.0
ACT_START = {"shoulder_pan": 1.0, "shoulder_lift": -100.0, "elbow_flex": 95.0, "wrist_flex": 45.0, "wrist_roll": -5.0,
             "gripper": 6.0}


class FakePolicy:
    def __init__(self):
        self.calls = 0

    def reset(self):
        pass

    def step(self, observation):
        self.calls += 1
        return {**ACT_START, "wrist_roll": POLICY_ROLL, "gripper": 7.0}


def make_act_executor(tmp_path, kin, robot=None, steps=5, policy=None, taught_start=True, colors=("red",)):
    poses = make_poses(tmp_path, colors=())
    if taught_start:
        poses.set("act_start", ACT_START)
    policy = policy or FakePolicy()
    act = ActGrasp(ActConfig(policies=dict.fromkeys(colors, "fake"), duration_s=steps / CONFIG.hz), lambda spec: policy)
    robot = robot or FakeRobot(initial=HOME)
    return robot, policy, Executor(robot, poses, make_calibration(), kin, config=CONFIG, act=act)


def arm_of(state):
    return {k: v for k, v in state.items() if k != "gripper"}


def policy_commands(robot):
    return [i for i, c in enumerate(robot.commands) if c.get("wrist_roll") == POLICY_ROLL]


def test_act_cell_goes_start_policy_cell_open_start(tmp_path, kin):
    robot, policy, ex = make_act_executor(tmp_path, kin, steps=5)
    ex.run([cell(0, "red")], SIZE)
    assert types(ex) == ["plan_started", "cell_started", "drop_pose", "cell_done", "finished"]
    assert policy.calls == 5 and len(policy_commands(robot)) == 5
    first = policy_commands(robot)[0]
    assert arm_of(robot.history[first - 1]) == pytest.approx(arm_of(ACT_START))  # act_start reached before the policy
    target = (*robot_xy(320, 240), CONFIG.drop_z)
    after = robot.history[policy_commands(robot)[-1] + 1:]
    at_drop = [s for s in after if kin.tool_xyz(arm_of(s)) == pytest.approx(target, abs=0.003)]
    assert at_drop and CONFIG.empty_below < at_drop[0]["gripper"] < CONFIG.gripper_open  # closed on the seed
    assert max(s["gripper"] for s in at_drop) == CONFIG.gripper_open  # released above the cell
    assert arm_of(robot.read_joints()) == pytest.approx(arm_of(ACT_START))  # back at act_start
    assert not any(h == pytest.approx(ex.poses.get("above_box_red") or {}) for h in robot.history)


def test_act_falls_back_to_the_mean_start_pose_when_untaught(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin, taught_start=False)
    ex.run([cell(0)], SIZE)
    assert arm_of(robot.history[policy_commands(robot)[0] - 1]) == pytest.approx(arm_of(ACT_START_FALLBACK))
    assert arm_of(robot.read_joints()) == pytest.approx(arm_of(ACT_START_FALLBACK))


def test_stop_during_the_policy_loop_ends_within_one_step(tmp_path, kin):
    class Stopping(FakeRobot):
        def send_joints(self, target):
            super().send_joints(target)
            if len(policy_commands(self)) == 3:
                ex.stop()

    robot, policy, ex = make_act_executor(tmp_path, kin, robot=Stopping(initial=HOME), steps=50)
    ex.run([cell(0), cell(1)], SIZE)
    assert len(policy_commands(robot)) == 3 and policy.calls == 3
    assert types(ex)[-1] == "stopped" and "finished" not in types(ex)
    assert robot.commands[-1].get("wrist_roll") == POLICY_ROLL and robot.torque_enabled


def test_colour_without_policy_still_uses_the_taught_box_path(tmp_path, kin):
    poses = make_poses(tmp_path, colors=("green",))
    act = ActGrasp(ActConfig(policies={"red": "fake"}), lambda spec: FakePolicy())
    robot = FakeRobot(initial=HOME)
    ex = Executor(robot, poses, make_calibration(), kin, config=CONFIG, act=act)
    ex.run([cell(0, "green")], SIZE)
    assert types(ex)[-1] == "finished" and policy_commands(robot) == []
    assert any(s["shoulder_pan"] == pytest.approx(40.0) for s in robot.history)


def test_colour_with_neither_policy_nor_pose_is_a_conflict(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0, "red"), cell(1, "blue")], SIZE)
    assert err.value.status == 409 and err.value.code == "missing_pose" and "above_box_blue" in err.value.detail
    assert "above_box_red" not in err.value.detail and robot.commands == []


def test_status_lists_policy_colours(tmp_path, kin):
    _, _, ex = make_act_executor(tmp_path, kin, colors=("red", "green"))
    assert ex.status()["policies"] == ["green", "red"]


# -- split test modes and drop height ----------------------------------------------------------------------
def test_grasp_mode_runs_only_the_policy_and_holds_the_seed(tmp_path, kin):
    robot, policy, ex = make_act_executor(tmp_path, kin, steps=5)
    ex.poses.set("act_start", ACT_START)
    ex.calibration = Calibration()  # grasp needs no calibration
    ex.run([cell(0, "red")], SIZE, mode="grasp")
    assert ex.events[0]["mode"] == "grasp"
    assert types(ex) == ["plan_started", "cell_started", "cell_done", "finished"]
    assert policy.calls == 5 and len(policy_commands(robot)) == 5
    assert robot.commands[-1].get("wrist_roll") == POLICY_ROLL  # stopped where the policy left the arm
    assert max(s["gripper"] for s in robot.history) < CONFIG.gripper_open  # never opened


def test_grasp_mode_without_policy_or_taught_pose_is_a_conflict(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0, "blue")], SIZE, mode="grasp")
    assert err.value.status == 409 and err.value.code == "missing_pose" and robot.commands == []


def test_grasp_mode_with_taught_poses_stops_after_the_lift(parts, kin):
    robot, ex = parts
    ex.run([cell(0, "green")], SIZE, mode="grasp")
    box = ex.poses.get("above_box_green")
    assert types(ex)[-1] == "finished"
    assert robot.read_joints()["shoulder_pan"] == pytest.approx(box["shoulder_pan"])  # lifted at the box, no cell
    assert not any(kin.tool_xyz(arm_of(s)) == pytest.approx((*robot_xy(320, 240), CONFIG.drop_z), abs=0.003)
                   for s in robot.history)


def test_place_mode_goes_over_the_cell_opens_and_returns_without_policy_or_box_poses(tmp_path, kin):
    robot, policy, ex = make_act_executor(tmp_path, kin, robot=FakeRobot(initial={**HOME, "gripper": 25.0}))
    ex.run([cell(0, "blue")], SIZE, mode="place")  # no policy and no above_box_blue: still fine
    assert ex.events[0]["mode"] == "place" and types(ex)[-1] == "finished"
    assert policy.calls == 0 and policy_commands(robot) == []
    target = (*robot_xy(320, 240), CONFIG.drop_z)
    at_drop = [s for s in robot.history if kin.tool_xyz(arm_of(s)) == pytest.approx(target, abs=0.003)]
    assert at_drop and min(s["gripper"] for s in at_drop) == pytest.approx(25.0)  # arrives with the gripper as it was
    assert max(s["gripper"] for s in at_drop) == CONFIG.gripper_open
    assert arm_of(robot.read_joints()) == pytest.approx(arm_of(ACT_START))


def test_place_mode_still_needs_calibration_and_reachability(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin)
    ex.calibration = Calibration()
    with pytest.raises(PlanError) as err:
        ex.run([cell(0)], SIZE, mode="place")
    assert err.value.code == "no_calibration"
    ex.calibration = make_calibration()
    with pytest.raises(PlanError) as err:
        ex.run([cell(0, u=5000, v=5000)], SIZE, mode="place")
    assert err.value.status == 422 and err.value.code == "unreachable" and robot.commands == []


def test_unknown_mode_is_invalid(tmp_path, kin):
    _, _, ex = make_act_executor(tmp_path, kin)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0)], SIZE, mode="dance")
    assert err.value.status == 422 and err.value.code == "invalid"


def test_drop_z_overrides_the_config_for_one_run(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin)
    ex.run([cell(0)], SIZE, drop_z=0.12)
    high = (*robot_xy(320, 240), 0.12)
    assert any(kin.tool_xyz(arm_of(s)) == pytest.approx(high, abs=0.003) for s in robot.history)
    ex.run([cell(0)], SIZE)  # the override does not stick
    assert [e["target"][2] for e in drop_poses(ex)] == pytest.approx([0.12, CONFIG.drop_z])


@pytest.mark.parametrize("drop_z", [0.0, 0.01, 0.3, -1])
def test_drop_z_out_of_range_is_invalid(tmp_path, kin, drop_z):
    robot, _, ex = make_act_executor(tmp_path, kin)
    with pytest.raises(PlanError) as err:
        ex.run([cell(0)], SIZE, drop_z=drop_z)
    assert err.value.status == 422 and err.value.code == "invalid" and robot.commands == []


# -- closed-loop drop correction ---------------------------------------------------------------------
def sagging(degrees):
    """The arm reads lower than commanded, like servos giving way under gravity when extended."""
    return lambda state: {**state, "shoulder_lift": state["shoulder_lift"] + degrees}


def drop_poses(ex):
    return [e for e in ex.events if e["type"] == "drop_pose"]


def place_executor(tmp_path, kin, sag=None, **cfg):
    robot = FakeRobot(initial=HOME, sag=sag)
    config = ExecutorConfig(hz=1000, max_speed=10_000, settle_s=0.0, **cfg)
    return robot, Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=config)


def test_drop_pose_event_reports_target_reached_and_error(parts):
    _, ex = parts
    ex.run([cell(3)], SIZE)
    (event,) = drop_poses(ex)
    assert event["cell_index"] == 3 and event["corrections"] == 0
    assert event["target"] == pytest.approx([*robot_xy(320, 240), CONFIG.drop_z], abs=1e-6)
    assert event["reached"] == pytest.approx(event["target"], abs=0.003)
    assert event["error_mm"] < 5.0
    assert types(ex).index("drop_pose") < types(ex).index("cell_done")


def test_sag_without_correction_misses_the_cell(tmp_path, kin):
    _, ex = place_executor(tmp_path, kin, sag=sagging(-20.0), place_corrections=0)
    ex.run([cell(0)], SIZE, mode="place")
    (event,) = drop_poses(ex)
    assert event["corrections"] == 0 and event["error_mm"] > 8.0


def test_closed_loop_correction_reduces_the_drop_error_under_sag(tmp_path, kin):
    _, open_loop = place_executor(tmp_path, kin, sag=sagging(-20.0), place_corrections=0)
    open_loop.run([cell(0)], SIZE, mode="place")
    _, closed = place_executor(tmp_path, kin, sag=sagging(-20.0))
    closed.run([cell(0)], SIZE, mode="place")
    (before,), (after,) = drop_poses(open_loop), drop_poses(closed)
    assert 1 <= after["corrections"] <= 2
    assert after["error_mm"] < before["error_mm"] / 2
    assert after["error_mm"] < 6.0
    assert closed.events[-1]["type"] == "finished"


def test_correction_also_runs_in_the_full_taught_cycle(tmp_path, kin):
    robot = FakeRobot(initial=HOME, sag=sagging(-20.0))
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0)], SIZE)
    (event,) = drop_poses(ex)
    assert event["corrections"] >= 1 and event["error_mm"] < 6.0
    assert robot.read_joints()["gripper"] == pytest.approx(CONFIG.gripper_open)


def test_stop_during_a_correction_stops_without_releasing(tmp_path, kin):
    robot, ex = place_executor(tmp_path, kin, sag=sagging(-20.0))
    moves, real_move = [], ex._move

    def counting_move(target):
        moves.append(target)
        if len(moves) == 2:  # the first move goes over the cell, the second is the correction
            ex.stop()
        real_move(target)

    ex._move = counting_move
    ex.run([cell(0)], SIZE, mode="place")
    assert types(ex)[-1] == "stopped" and "drop_pose" not in types(ex)
    assert len(moves) == 2  # no third move: the gripper never opened


# -- approach from above -----------------------------------------------------------------------------
def tool_heights(robot, kin):
    return [kin.tool_xyz(arm_of(s))[2] for s in robot.history]


def test_release_hovers_above_the_cell_before_descending_and_after_opening(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin, robot=FakeRobot(initial={**HOME, "gripper": 25.0}))
    ex.run([cell(0, "blue")], SIZE, mode="place")
    hover = CONFIG.drop_z + CONFIG.approach_clearance
    zs, grip = tool_heights(robot, kin), [s["gripper"] for s in robot.history]
    at_hover = [i for i, z in enumerate(zs) if z == pytest.approx(hover, abs=0.003)]
    at_drop = [i for i, z in enumerate(zs) if z == pytest.approx(CONFIG.drop_z, abs=0.003)]
    assert at_hover and at_drop
    assert at_hover[0] < at_drop[0]  # comes down onto the cell from above
    opened = next(i for i in at_drop if grip[i] == CONFIG.gripper_open)
    assert any(i > opened for i in at_hover)  # lifts straight back up after letting go
    assert not any(grip[i] == CONFIG.gripper_open for i in at_hover if i < opened)  # opens only at the drop height


def test_release_without_a_reachable_hover_pose_still_drops(tmp_path, kin):
    robot, _, ex = make_act_executor(tmp_path, kin, robot=FakeRobot(initial={**HOME, "gripper": 25.0}))
    ex.cfg.approach_clearance = 5.0  # far beyond the arm's reach
    ex.run([cell(0, "blue")], SIZE, mode="place")
    assert types(ex)[-1] == "finished" and drop_poses(ex)
    assert max(tool_heights(robot, kin)) < CONFIG.drop_z + 0.05 + 0.1  # never went anywhere near the hover height
    assert max(s["gripper"] for s in robot.history) == CONFIG.gripper_open
