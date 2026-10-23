import numpy as np
import pytest

from smartseed_vision.geometry import analyze_tray
from synth import make_box_on_mat_image, make_cardboard_box_image, make_tray_image


@pytest.mark.parametrize("rows,cols", [(4, 6), (5, 8), (3, 3), (6, 4), (1, 2), (2, 1), (2, 2), (2, 3)])
@pytest.mark.parametrize("angle", [0.0, 10.0])
def test_rows_cols_and_corners(rows, cols, angle):
    img, true = make_tray_image(rows, cols, angle)
    result = analyze_tray(img)
    assert (result.rows, result.cols) == (rows, cols)
    assert np.abs(np.array(result.corners_px) - true).max() < 5
    assert result.confidence > 0.3


def test_bbox_restricts_search_to_the_tray():
    img, true = make_tray_image(4, 6, 0.0, center=(200, 200))
    img[:, 450:] = 20  # unrelated dark region the detector bbox excludes
    result = analyze_tray(img, bbox=(0, 0, 440, 480))
    assert np.abs(np.array(result.corners_px) - true).max() < 5


def test_corner_order_is_tl_tr_br_bl():
    img, _ = make_tray_image(4, 6, 10.0)
    tl, tr, br, bl = np.array(analyze_tray(img).corners_px)
    assert tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]


def test_blank_image_returns_none():
    assert analyze_tray(np.full((480, 640, 3), 200, np.uint8)) is None


@pytest.mark.parametrize("rows,cols", [(1, 2), (2, 2), (1, 3)])
def test_light_box_on_dark_mat_is_found_instead_of_the_mat(rows, cols):
    img, true = make_box_on_mat_image(rows, cols)
    result = analyze_tray(img)
    assert (result.rows, result.cols) == (rows, cols)
    assert np.abs(np.array(result.corners_px) - true).max() < 8
    assert result.confidence > 0.35


@pytest.mark.parametrize("rows,cols", [(1, 2), (2, 2)])
def test_cardboard_box_with_shadowed_wall_is_located_by_colour(rows, cols):
    img, true = make_cardboard_box_image(rows, cols)
    result = analyze_tray(img)
    assert (result.rows, result.cols) == (rows, cols)
    assert np.abs(np.array(result.corners_px) - true).max() < 8
