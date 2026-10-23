import numpy as np
import pytest

from smartseed_vision.depth import assign_rows, find_holes
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
