"""Geometry of the scripted IK grasp of one seed: where the tool goes and how the wrist is rolled.

The same idea as the sim demo planner (`sim/grasp_test.py`, `grasp_candidates` / `axis_pose`), without a box model
(the backend does not know where the walls are): the open jaws are a thin rectangle along a jaw axis, the fixed-jaw
face (the tool frame) sits `FACE_GAP` plus one seed radius before the seed along that axis, and the wrist roll is
what turns the radial jaw axis (from the shoulder pan axis through the tool) onto the chosen one. The radial axis,
roll 0, is preferred; an axis is skipped while another detected seed lies inside its footprint.
"""
from __future__ import annotations

import math

from .kinematics import PAN_AXIS_X

FACE_GAP = 0.0035  # m; the open fixed-jaw face starts this far from the seed surface (> the perception error)
TOOL_Z_OFFSET = -0.0003  # m; MEASURED in the sim: the recorded grasp closes with the tool frame this far below the seed centre
FOOT_NEAR, FOOT_FAR, FOOT_SIDE = 0.018, 0.040, 0.016  # open-jaw footprint around the seed along / across the jaw axis
SEED_CLEAR = 0.010  # a neighbouring seed (radius plus slack) must stay out of the footprint
AXIS_STEP_DEG = 30.0  # candidate jaw axes: the radial one and every 30 degrees around it


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def clearance(seed, phi: float, others) -> float:
    """Smallest distance (m) from the open-jaw footprint along the axis `phi` (rad) to the other seeds, less
    `SEED_CLEAR` (negative: one is inside); infinite when there are none."""
    c, s = math.cos(phi), math.sin(phi)
    margin = math.inf
    for ox, oy in others:
        a = c * (ox - seed[0]) + s * (oy - seed[1])  # the other seed in the jaw frame: along ...
        b = -s * (ox - seed[0]) + c * (oy - seed[1])  # ... and across the axis
        da, db = max(-FOOT_NEAR - a, a - FOOT_FAR), abs(b) - FOOT_SIDE  # signed distances to the rectangle's sides
        outside = math.hypot(max(da, 0.0), max(db, 0.0)) if max(da, db) > 0 else max(da, db)
        margin = min(margin, outside - SEED_CLEAR)
    return margin


def axis_pose(seed, radius: float, phi: float) -> tuple[float, tuple[float, float]]:
    """Wrist spin (deg) and tool xy that put the jaw axis along the world direction `phi` (rad) with the seed on it."""
    tool_xy = (seed[0] - math.cos(phi) * (radius + FACE_GAP), seed[1] - math.sin(phi) * (radius + FACE_GAP))
    radial_tool = math.degrees(math.atan2(tool_xy[1], tool_xy[0] - PAN_AXIS_X))
    return _wrap_deg(radial_tool - math.degrees(phi)), tool_xy


def jaw_axes(seed, others, radius: float) -> list[tuple[float, tuple[float, float]]]:
    """Every candidate as (spin deg, tool xy), best first: the axes clear of `others` with the smallest wrist roll
    first, then the crowded ones, the most room first."""
    radial = math.atan2(seed[1], seed[0] - PAN_AXIS_X)
    scored = []
    for k in range(round(360 / AXIS_STEP_DEG)):
        phi = radial + math.radians(AXIS_STEP_DEG * k)
        spin, tool_xy = axis_pose(seed, radius, phi)
        scored.append((clearance(seed, phi, others), spin, tool_xy))
    free = sorted((c for c in scored if c[0] > 0), key=lambda c: abs(c[1]))
    crowded = sorted((c for c in scored if c[0] <= 0), key=lambda c: -c[0])
    return [(spin, tool_xy) for _, spin, tool_xy in free + crowded]
