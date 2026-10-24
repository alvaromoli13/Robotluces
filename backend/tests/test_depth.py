import numpy as np
import pytest

from smartseed_vision.depth import assign_rows, find_holes, grid_in_tray
from synth import make_box_depth


@pytest.mark.parametrize("rows,cols", [(1, 2), (2, 2), (2, 3), (3, 4)])
def test_each_compartment_is_one_hole_in_row_major_order(rows, cols):
    depth, centers = make_box_depth(rows, cols)
    holes = find_holes(depth)
    assert len(holes) == rows * cols
    got = np.array([[h["x"], h["y"]] for h in holes])
    assert np.abs(got - np.array(centers)).max() < 0.06
    assert [(h["row"], h["col"]) for h in holes] == [(r, c) for r in range(rows) for c in range(cols)]


@pytest.mark.parametrize("angle", [12.0, -12.0, 25.0, -25.0])
def test_rotated_box_keeps_its_compartments_in_one_row(angle):
    depth, centers = make_box_depth(1, 2, angle_deg=angle)
    holes = find_holes(depth)
    assert [(h["row"], h["col"]) for h in holes] == [(0, 0), (0, 1)]
    got = np.array([[h["x"], h["y"]] for h in holes])
    assert np.abs(got - np.array(centers)).max() < 0.08


def test_tilted_table_without_box_has_no_holes():
    yy, xx = np.mgrid[0:240, 0:320].astype(np.float32)
    assert find_holes(0.2 + 0.3 * (1 - yy / 240) + 0.05 * xx / 320) == []


def test_depression_open_to_the_frame_edge_is_not_a_hole():
    depth = np.full((240, 320), 0.5, np.float32)
    depth[100:140, 0:120] = 0.2  # a trench that reaches the left border, like the table around a box
    assert find_holes(depth) == []


def test_hole_reports_area_and_depth():
    depth, _ = make_box_depth(1, 2)
    hole = find_holes(depth)[0]
    assert 0 < hole["area"] < 0.5
    assert hole["depth"] > 0


def hole(x, y, h=0.08):
    return {"x": x, "y": y, "_h": h}


def test_side_by_side_holes_offset_by_a_tilted_box_share_a_row():
    # measured on the real 1x2 cardboard box: centers (393, 280) and (250, 323) in 640x480,
    # each basin core ~40 px tall because only the lower part of a compartment looks deep
    rows = assign_rows([hole(393 / 640, 280 / 480), hole(250 / 640, 323 / 480)])
    assert [(h["row"], h["col"]) for h in rows] == [(0, 0), (0, 1)]
    assert rows[0]["x"] < rows[1]["x"]


def test_grid_holes_split_into_rows():
    grid = [hole(x, y) for y in (0.3, 0.6) for x in (0.3, 0.5, 0.7)]
    assert [(h["row"], h["col"]) for h in assign_rows(grid)] == [(r, c) for r in range(2) for c in range(3)]


def on_a_table(depth, pad):
    """The synthetic tray fills its frame; put it in the middle of a wider flat table like the real scene."""
    return np.pad(depth, pad, mode="edge")


def pit(depth, x, y, r=0.02):
    depth = depth.copy()
    h, w = depth.shape
    ys, xs = np.mgrid[0:h, 0:w]
    depth[((xs - x * w) ** 2 + (ys - y * h) ** 2) < (r * w) ** 2] = depth.min()
    return depth


def test_a_basin_just_outside_a_correct_tray_quad_is_dropped():
    depth = on_a_table(make_box_depth(3, 4)[0], 120)
    h, w = depth.shape
    x0, y0, x1, y1 = 120 / w, 120 / h, (w - 120) / w, (h - 120) / h
    holes = find_holes(pit(depth, x1 + 0.04, (y0 + y1) / 2), tray=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    assert len(holes) == 12
    assert all(x0 <= h["x"] <= x1 for h in holes)


def test_grid_in_tray_numbers_holes_in_tray_coordinates_even_when_rotated():
    rows, cols, angle = 3, 4, np.deg2rad(14)
    centre, half = np.array([0.6, 0.5]), np.array([0.2, 0.12])
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    to_img = lambda u, v: centre + rot @ ((np.array([u, v]) * 2 - 1) * half)
    corners = [to_img(0, 0).tolist(), to_img(1, 0).tolist(), to_img(1, 1).tolist(), to_img(0, 1).tolist()]
    truth = {(r, c): to_img((c + 0.5) / cols, (r + 0.5) / rows) for r in range(rows) for c in range(cols)}
    shuffled = [truth[k] for k in [(2, 3), (0, 0), (1, 2), (0, 3), (2, 0), (1, 0), (0, 1), (2, 2), (1, 3), (0, 2),
                                   (2, 1), (1, 1)]]
    holes = grid_in_tray([{"x": x, "y": y, "area": 0.01, "depth": 0.2} for x, y in shuffled], corners, rows, cols)
    assert [(h["row"], h["col"]) for h in holes] == [(r, c) for r in range(rows) for c in range(cols)]
    for h in holes:
        assert np.allclose([h["x"], h["y"]], truth[(h["row"], h["col"])])


def test_a_wrong_tray_quad_does_not_drop_a_whole_row_of_holes():
    depth, centers = make_box_depth(3, 4)
    ys = sorted({round(y, 3) for _, y in centers})
    two_rows_only = [[0.0, 0.0], [1.0, 0.0], [1.0, (ys[1] + ys[2]) / 2], [0.0, (ys[1] + ys[2]) / 2]]
    assert len(find_holes(depth, tray=two_rows_only)) == 12


def test_an_isolated_basin_far_from_the_grid_is_dropped_without_a_tray():
    # a deep pit in the far corner, like the gripper seen from above
    depth = pit(on_a_table(make_box_depth(3, 4)[0], ((120, 480), (120, 120))), 0.5, 0.95)
    holes = find_holes(depth)
    assert len(holes) == 12
    assert all(h["x"] < 0.9 or h["y"] < 0.9 for h in holes)
