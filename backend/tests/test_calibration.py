import numpy as np
import pytest

from smartseed_robot.calibration import Calibration, CalibrationError

SIZE = (640, 480)


def truth(u, v):  # pixel -> robot metres: scale, flip v, offset
    return 0.1 + u * 0.0005, 0.2 - v * 0.0005


def filled(n=6):
    cal = Calibration()
    for u, v in [(50, 60), (590, 70), (600, 420), (40, 430), (320, 240), (200, 100)][:n]:
        cal.add_point(u, v, *truth(u, v), image_size=SIZE)
    return cal


def test_fit_recovers_mapping_and_reports_error():
    cal = filled()
    stats = cal.fit()
    assert stats["n"] == 6 and stats["max_error_mm"] < 0.5
    assert cal.pixel_to_robot(100, 300) == pytest.approx(truth(100, 300), abs=0.0005)


def test_fit_needs_four_points():
    with pytest.raises(CalibrationError):
        filled(3).fit()


def test_unfitted_calibration_refuses_to_convert():
    with pytest.raises(CalibrationError):
        filled().pixel_to_robot(1, 1)


def test_pixel_scaling_for_other_image_sizes():
    cal = filled()
    cal.fit()
    assert cal.pixel_to_robot(50, 150, image_size=(320, 240)) == pytest.approx(truth(100, 300), abs=0.0005)


def test_points_must_share_an_image_size():
    cal = filled(4)
    with pytest.raises(CalibrationError):
        cal.add_point(1, 1, 0, 0, image_size=(1280, 720))


def test_save_and_load_round_trip(tmp_path):
    cal = filled()
    cal.fit()
    path = tmp_path / "calibration.json"
    cal.save(path)
    loaded = Calibration.load(path)
    assert loaded.fitted and len(loaded.points) == 6
    assert np.allclose(loaded.pixel_to_robot(10, 10), cal.pixel_to_robot(10, 10))


def test_load_missing_file_gives_empty_calibration(tmp_path):
    cal = Calibration.load(tmp_path / "nope.json")
    assert not cal.fitted and cal.points == []


def test_clear_drops_points_and_fit():
    cal = filled()
    cal.fit()
    cal.clear()
    assert not cal.fitted and cal.points == []


def test_points_may_carry_the_tool_height_and_the_mean_survives_save_and_load(tmp_path):
    cal = Calibration()
    assert cal.mean_z is None
    for i, (u, v) in enumerate([(0, 0), (10, 0), (10, 10), (0, 10)]):
        cal.add_point(u, v, u * 0.001, v * 0.001, image_size=(640, 480), z=0.01 + 0.002 * i)
    assert cal.mean_z == pytest.approx(0.013)
    cal.fit()
    cal.save(tmp_path / "grasp_calibration.json")
    assert Calibration.load(tmp_path / "grasp_calibration.json").mean_z == pytest.approx(0.013)


def test_points_without_a_height_leave_the_mean_height_unknown_and_the_file_format_unchanged(tmp_path):
    cal = filled(4)
    assert cal.mean_z is None and all("z" not in p for p in cal.points)
