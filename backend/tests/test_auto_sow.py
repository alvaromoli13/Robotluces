import numpy as np
import pytest

from smartseed_robot.calibration import Calibration
from smartseed_robot.executor import Executor, ExecutorConfig, PlanError
from smartseed_robot.robot import FakeRobot

from test_executor import CONFIG, HOME, SIZE, cell, make_calibration, make_poses, robot_xy

SEED_Z = 0.007
AUTO = ExecutorConfig(hz=1000, max_speed=10_000, settle_s=0.0, release_wrist_tilt_deg=0.0, auto_attempts=2,
                      cartesian_speed=5.0)


def make_grasp_calibration(z=SEED_Z):
    cal = Calibration()
    for u, v in [(50, 60), (590, 70), (600, 420), (40, 430), (320, 240)]:
        cal.add_point(u, v, *robot_xy(u, v), image_size=SIZE, z=z)
    cal.fit()
    return cal


class Finder:
    """Stands in for the seed detector: each call returns the next scripted list of pixel centres (the last repeats)."""

    def __init__(self, *frames):
        self.frames, self.calls = list(frames), 0

    def __call__(self, rgb, color):
        self.calls += 1
        return self.frames[min(self.calls - 1, len(self.frames) - 1)]


def tcell(i, color):
    """A target cell far from where the test seeds are (the tray is on the left of the frame, the box on the right)."""
    return cell(i, color, 100 + 40 * i, 300)


def make(tmp_path, kin, finder, grasp_script=None, grasp=True, config=AUTO):
    robot = FakeRobot(initial=HOME, grasp_script=grasp_script)
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=config,
                  grasp_calibration=make_grasp_calibration() if grasp else None, seed_finder=finder)
    return robot, ex


def types(ex):
    return [e["type"] for e in ex.events]


def tool_path(robot, kin):
    return [kin.tool_xyz({k: v for k, v in s.items() if k != "gripper"}) for s in robot.history]


def test_auto_without_a_grasp_calibration_is_a_409_with_its_own_code(tmp_path, kin):
    _, ex = make(tmp_path, kin, Finder([]), grasp=False)
    with pytest.raises(PlanError) as err:
        ex.run([tcell(0, "black")], SIZE, mode="auto")
    assert err.value.status == 409 and err.value.code == "no_grasp_calibration" and "grasp" in err.value.detail


def test_auto_needs_the_place_calibration_and_the_home_pose_too(tmp_path, kin):
    robot = FakeRobot(initial=HOME)
    ex = Executor(robot, make_poses(tmp_path), Calibration(), kin, config=AUTO, grasp_calibration=make_grasp_calibration(),
                  seed_finder=Finder([]))
    with pytest.raises(PlanError) as err:
        ex.run([tcell(0, "black")], SIZE, mode="auto")
    assert err.value.code == "no_calibration"
    ex = Executor(robot, make_poses(tmp_path / "other", colors=()), make_calibration(), kin, config=AUTO,
                  grasp_calibration=make_grasp_calibration(), seed_finder=Finder([]))
    ex.poses._poses.pop("home")
    with pytest.raises(PlanError) as err:
        ex.run([tcell(0, "black")], SIZE, mode="auto")
    assert err.value.code == "missing_pose"


def test_auto_sows_each_seed_in_the_next_free_cell_and_stops_when_the_box_is_empty(tmp_path, kin):
    finder = Finder([(300, 240), (360, 300)], [(360, 300)], [])
    robot, ex = make(tmp_path, kin, finder)
    ex.run([cell(0, "black", 100, 300), cell(1, "black", 140, 300), cell(2, "black", 180, 300)], SIZE, mode="auto")
    assert ex.status()["done"] == [0, 1] and ex.status()["state"] == "idle"
    assert types(ex).count("drop_pose") == 2 and types(ex)[-1] == "finished"
    stopped = [e for e in ex.events if e["type"] == "auto_stopped"]
    assert len(stopped) == 1 and stopped[0]["reason"] == "no_seeds" and stopped[0]["color"] == "black"
    path = tool_path(robot, kin)
    for pixel in ((300, 240), (360, 300)):  # the tool went down to each seed, at the grasp height
        x, y = robot_xy(*pixel)
        assert any(p == pytest.approx((x, y, SEED_Z), abs=0.004) or
                   (abs(p[2] - SEED_Z) < 0.004 and np.hypot(p[0] - x, p[1] - y) < 0.012) for p in path), pixel
    for cell_pixel in ((100, 300), (140, 300)):  # and released over the cells in order
        assert any(np.allclose(p, (*robot_xy(*cell_pixel), AUTO.drop_z), atol=0.004) for p in path)
    assert robot.read_joints()["gripper"] == pytest.approx(AUTO.gripper_open) or robot.read_joints() == pytest.approx(HOME)


def test_the_nearest_seed_to_the_arm_goes_first(tmp_path, kin):
    finder = Finder([(560, 100), (320, 240)], [])
    robot, ex = make(tmp_path, kin, finder)
    ex.run([tcell(0, "black")], SIZE, mode="auto")
    grasps = [e for e in ex.events if e["type"] == "grasp_attempt"]
    assert grasps[0]["x"] == pytest.approx(robot_xy(320, 240)[0], abs=1e-6)


def test_an_empty_grasp_is_retried_and_counted(tmp_path, kin):
    finder = Finder([(300, 240)], [(300, 240)], [])
    robot, ex = make(tmp_path, kin, finder, grasp_script=[False, True])
    ex.run([tcell(0, "black"), tcell(1, "black")], SIZE, mode="auto")
    attempts = [e for e in ex.events if e["type"] == "grasp_attempt"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    failed = [e for e in ex.events if e["type"] == "grasp_failed"]
    assert len(failed) == 1 and failed[0]["cause"] == "empty"
    assert ex.status()["done"] == [0] and ex.retries == [0]


def test_a_seed_that_never_closes_on_anything_is_given_up_after_the_attempt_budget(tmp_path, kin):
    finder = Finder([(300, 240)])  # the detector keeps seeing it
    robot, ex = make(tmp_path, kin, finder, grasp_script=[False] * 10)
    ex.run([tcell(0, "black"), tcell(1, "black")], SIZE, mode="auto")
    assert types(ex).count("grasp_attempt") == AUTO.auto_attempts
    assert [e["reason"] for e in ex.events if e["type"] == "auto_stopped"] == ["gave_up"]
    assert ex.status()["done"] == [] and ex.status()["failed"] == [0] and ex.status()["state"] == "idle"
    assert types(ex).count("drop_pose") == 0  # nothing held, nothing released over a cell


def test_an_unreachable_seed_is_skipped_for_a_reachable_one(tmp_path, kin):
    far = (4000, 240)  # x = 0.63 m: beyond the arm
    finder = Finder([far, (300, 240)], [far], [far])
    robot, ex = make(tmp_path, kin, finder)
    ex.run([tcell(0, "black"), tcell(1, "black")], SIZE, mode="auto")
    assert ex.status()["done"] == [0]
    causes = [e["cause"] for e in ex.events if e["type"] == "grasp_failed"]
    assert causes == ["unreachable"]
    assert [e["reason"] for e in ex.events if e["type"] == "auto_stopped"] == ["gave_up"]


def test_a_colour_with_no_seeds_does_not_stop_the_other_colour(tmp_path, kin):
    def finder(rgb, color):
        return [] if color == "white" else [(300, 240)]

    # white has no seeds: its cell is skipped; the black cell after it is still sown (the seed is detected again after)
    robot, ex = make(tmp_path, kin, finder)
    ex.run([tcell(0, "white"), tcell(1, "black")], SIZE, mode="auto")
    assert ex.status()["done"] == [1]
    assert [(e["color"], e["reason"]) for e in ex.events if e["type"] == "auto_stopped"][0] == ("white", "no_seeds")


def test_the_detector_gets_the_top_frame_and_the_cells_colour(tmp_path, kin):
    seen = []

    def finder(rgb, color):
        seen.append((rgb.shape, color))
        return []

    _, ex = make(tmp_path, kin, finder)
    ex.run([tcell(0, "white")], SIZE, mode="auto")
    assert seen == [((480, 640, 3), "white")]


def test_stop_interrupts_auto_and_the_arm_holds(tmp_path, kin):
    finder = Finder([(300, 240)])
    robot, ex = make(tmp_path, kin, finder)
    ex._begin([tcell(0, "black")], SIZE, "auto", None)
    ex._stop.set()  # a stop that arrives before the first move
    ex._execute([tcell(0, "black")], SIZE, ex._plan_id)
    assert types(ex)[-1] == "stopped" and ex.status()["state"] == "idle"


def test_the_other_modes_do_not_need_a_grasp_calibration(tmp_path, kin):
    robot = FakeRobot(initial=HOME)
    ex = Executor(robot, make_poses(tmp_path), make_calibration(), kin, config=CONFIG)
    ex.run([cell(0, "red")], SIZE, mode="place")
    assert ex.status()["done"] == [0]


def test_seeds_lying_in_the_target_cells_are_not_picked_up_again(tmp_path, kin):
    # the tray is cardboard like the box floor: a seed already sown shows up in the same detection
    cells_px = [(100, 300), (160, 300), (100, 360), (160, 360)]
    sown = [(130, 330), (100, 300)]  # inside the cells' hull, and on a cell centre
    just_outside = [(215, 330)]  # a bit more than a cell pitch beyond the hull: the box floor is not that close
    finder = Finder([*sown, (360, 240)], [*sown], [*sown])
    robot, ex = make(tmp_path, kin, finder)
    ex.run([cell(i, "black", u, v) for i, (u, v) in enumerate(cells_px)], SIZE, mode="auto")
    grasps = [e for e in ex.events if e["type"] == "grasp_attempt"]
    assert len(grasps) == 1 and grasps[0]["x"] == pytest.approx(robot_xy(360, 240)[0], abs=1e-6)
    assert [e["reason"] for e in ex.events if e["type"] == "auto_stopped"] == ["no_seeds"]
    keep = Finder(just_outside, [])
    robot, ex = make(tmp_path / "again", kin, keep)
    ex.run([cell(i, "black", u, v) for i, (u, v) in enumerate(cells_px)], SIZE, mode="auto")
    assert types(ex).count("grasp_attempt") == 1


def test_the_jaw_reading_decides_held_or_empty_with_the_real_followers_numbers(tmp_path, kin):
    # real follower: 6.1 closed empty, 6.9 holding a black seed, 7.4 a white one (the stop is at about 6)
    for reading, sown in ((6.9, [0]), (7.4, [0]), (6.1, [])):
        robot = FakeRobot(initial=HOME, held_value=reading)
        ex = Executor(robot, make_poses(tmp_path / str(reading)), make_calibration(), kin, config=AUTO,
                      grasp_calibration=make_grasp_calibration(), seed_finder=Finder([(300, 240)], []))
        ex.run([tcell(0, "black")], SIZE, mode="auto")
        assert ex.status()["done"] == sown, reading
