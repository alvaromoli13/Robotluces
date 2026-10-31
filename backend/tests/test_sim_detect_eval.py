"""`sim/detect_eval.py`: how far the seed detector plus a pixel -> base calibration puts each seed from the truth."""
from __future__ import annotations

import numpy as np
import pytest

from sim import detect_eval, eval as sim_eval, layout, make_dataset as md
from sim.measure_layout import project


def test_matching_pairs_each_detection_with_the_nearest_truth_and_counts_the_rest():
    truth = np.array([[0.30, 0.00], [0.30, 0.05], [0.40, 0.10]])
    detected = np.array([[0.3003, 0.0004], [0.2995, 0.0502], [0.10, -0.2]])  # third truth missed, one stray detection
    m = detect_eval.match_positions(detected, truth, gate_m=0.02)
    assert m.errors_mm == pytest.approx([0.5, 0.5385], abs=0.01)
    assert (m.matched, m.misses, m.false) == (2, 1, 1)


def test_matching_does_not_give_one_detection_to_two_seeds():
    truth = np.array([[0.30, 0.000], [0.30, 0.010]])
    m = detect_eval.match_positions(np.array([[0.30, 0.004]]), truth, gate_m=0.02)
    assert (m.matched, m.misses, m.false) == (1, 1, 0)


def test_matching_with_nothing_on_either_side():
    m = detect_eval.match_positions(np.zeros((0, 2)), np.zeros((0, 2)), gate_m=0.02)
    assert (m.matched, m.misses, m.false, len(m.errors_mm)) == (0, 0, 0, 0)


def test_summary_of_errors_is_median_p90_max_in_mm():
    s = detect_eval.summarize(np.arange(1.0, 11.0))
    assert s == {"median": 5.5, "p90": pytest.approx(9.1), "max": 10.0}
    assert detect_eval.summarize(np.array([])) == {"median": None, "p90": None, "max": None}


def test_the_seed_plane_calibration_is_exact_at_the_seed_height_and_not_at_the_tray_top():
    cal = detect_eval.seed_plane_calibration("black")
    z = md.box_of("black").floor_z + layout.SEED_RADIUS["black"]
    for xy in ((0.25, -0.1), (0.40, 0.12)):
        assert cal.pixel_to_robot(*project((*xy, z))) == pytest.approx(xy, abs=1e-4)
    off = cal.pixel_to_robot(*project((0.40, 0.12, layout.TRAY_TOP_Z)))  # a point 4.7 cm higher lands elsewhere
    assert np.hypot(off[0] - 0.40, off[1] - 0.12) > 0.005


@pytest.mark.parametrize("color", ["black", "white"])
def test_a_scene_without_camera_noise_gives_every_seed_within_3_mm(color, kin):
    (scene,) = sim_eval.heldout_scenes(color, 1, kin=kin, layout_mode="narrow")
    result = detect_eval.measure_scene(scene, camera_noise=False)
    assert (result.match.misses, result.match.false) == (0, 0)
    assert result.match.matched == len(getattr(scene, color).seeds) >= 1
    assert result.match.errors_mm.max() < 3.0
    assert result.frame.shape == (480, 640, 3)


def test_camera_noise_changes_the_frame_and_the_detections():
    (scene,) = sim_eval.heldout_scenes("black", 1, layout_mode="narrow")
    assert scene.top_cam_shift != (0, 0, 0)
    clean, noisy = detect_eval.measure_scene(scene, camera_noise=False), detect_eval.measure_scene(scene, camera_noise=True)
    assert not np.array_equal(clean.frame, noisy.frame)
    assert not np.allclose(clean.detected_xy, noisy.detected_xy, atol=1e-4)  # same truth, another camera, other numbers
    assert np.array_equal(clean.truth_xy, noisy.truth_xy)
