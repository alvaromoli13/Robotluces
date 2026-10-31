"""Top-camera seed detector: classic CV on a frame, no model. Frames here are drawn: a cardboard floor with discs."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from smartseed_robot import seed_detector
from smartseed_robot.calibration import Calibration

CARDBOARD, MAT = (199, 153, 102), (51, 48, 69)
BLACK, WHITE = (13, 13, 13), (237, 235, 224)
SS = 8  # supersampling of the drawn discs, so their centres are real sub-pixel positions


def frame(discs=(), floor=((100, 100), (400, 300))) -> np.ndarray:
    """480x640 RGB: dark mat, a cardboard floor rectangle, then discs (u, v, radius_px, rgb) with anti-aliased edges; (u, v) is in pixel-index coordinates, a pixel centre at an integer."""
    big = np.empty((480 * SS, 640 * SS, 3), np.uint8)
    big[:] = MAT
    (x0, y0), (x1, y1) = floor
    cv2.rectangle(big, (x0 * SS, y0 * SS), (x1 * SS, y1 * SS), CARDBOARD, -1)
    for u, v, r, rgb in discs:
        cv2.circle(big, (round(u * SS + (SS - 1) / 2), round(v * SS + (SS - 1) / 2)), round(r * SS), rgb, -1, cv2.LINE_AA)
    return cv2.resize(big, (640, 480), interpolation=cv2.INTER_AREA)


def nearest(found, u, v) -> float:
    return min(np.hypot(a - u, b - v) for a, b in found)


@pytest.mark.parametrize("color,rgb", [("black", BLACK), ("white", WHITE)])
def test_finds_discs_of_its_colour_with_subpixel_accuracy(color, rgb):
    truth = [(150.3, 150.7, 7), (250.55, 180.2, 7), (330.8, 240.45, 7)]
    found = seed_detector.detect_seeds(frame([(u, v, r, rgb) for u, v, r in truth]), color)
    assert len(found) == 3
    for u, v, _ in truth:
        assert nearest(found, u, v) < 0.3


def test_ignores_the_other_colour():
    img = frame([(150.3, 150.7, 7, BLACK), (250.5, 180.2, 7, WHITE)])
    (black,), (white,) = seed_detector.detect_seeds(img, "black"), seed_detector.detect_seeds(img, "white")
    assert np.hypot(black[0] - 150.3, black[1] - 150.7) < 0.3
    assert np.hypot(white[0] - 250.5, white[1] - 180.2) < 0.3


def test_ignores_dark_things_that_are_not_inside_the_cardboard_floor():
    img = frame([(500.0, 400.0, 7, BLACK), (150.0, 150.0, 7, BLACK)])  # the first one lies on the dark mat
    assert len(seed_detector.detect_seeds(img, "black")) == 1


def test_ignores_blobs_of_the_wrong_size_or_shape():
    img = frame([(150.0, 150.0, 7, BLACK), (300.0, 200.0, 18, BLACK), (200.0, 250.0, 1.5, BLACK)])
    cv2.rectangle(img, (320, 240), (370, 252), BLACK, -1)  # a bar 50 x 12 px: not round
    found = seed_detector.detect_seeds(img, "black")
    assert len(found) == 1 and nearest(found, 150.0, 150.0) < 0.3


def test_no_seeds_on_an_empty_floor():
    assert seed_detector.detect_seeds(frame(), "black") == []
    assert seed_detector.detect_seeds(frame(), "white") == []


def test_a_seed_close_to_the_edge_of_the_floor_is_still_found():
    found = seed_detector.detect_seeds(frame([(115.0, 200.0, 7, BLACK)]), "black")
    assert len(found) == 1 and nearest(found, 115.0, 200.0) < 0.6


def test_rejects_an_unknown_colour_and_a_wrong_frame():
    with pytest.raises(ValueError):
        seed_detector.detect_seeds(frame(), "red")
    with pytest.raises(ValueError):
        seed_detector.detect_seeds(np.zeros((480, 640), np.uint8), "black")


def test_seeds_to_robot_goes_through_the_calibration_homography():
    cal = Calibration()
    for u, v, x, y in ((0, 0, 0.0, 0.0), (640, 0, 0.0, -0.64), (640, 480, -0.48, -0.64), (0, 480, -0.48, 0.0)):
        cal.add_point(u, v, x, y, (640, 480))
    cal.fit()
    out = seed_detector.seeds_to_robot(cal, [(320.0, 240.0), (0.0, 480.0)])
    assert out == pytest.approx(np.array([[-0.24, -0.32], [-0.48, 0.0]]), abs=1e-6)
    assert seed_detector.seeds_to_robot(cal, []).shape == (0, 2)


def test_ignores_spots_on_the_saturated_orange_arm_which_is_not_a_cardboard_floor():
    img = frame()
    cv2.rectangle(img, (420, 320), (520, 420), (240, 105, 15), -1)  # orange plastic: same hue as cardboard, far more saturated
    cv2.circle(img, (470, 370), 7, WHITE, -1, cv2.LINE_AA)
    cv2.circle(img, (440, 340), 7, BLACK, -1, cv2.LINE_AA)
    assert seed_detector.detect_seeds(img, "white") == []
    assert seed_detector.detect_seeds(img, "black") == []


def test_ignores_a_dark_blob_sitting_on_the_floor_edge_such_as_a_chunk_of_box_wall():
    img = frame([(300.0, 200.0, 7, BLACK)])
    cv2.circle(img, (102, 200), 7, BLACK, -1, cv2.LINE_AA)  # across the edge: most of its surroundings is not floor
    found = seed_detector.detect_seeds(img, "black")
    assert len(found) == 1 and nearest(found, 300.0, 200.0) < 0.3
