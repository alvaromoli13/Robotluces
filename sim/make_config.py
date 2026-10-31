"""Write `sim/config/calibration.json`, `grasp_calibration.json` and `poses.json`: a self-consistent data dir for
`SMARTSEED_ROBOT=sim`.

The real `backend/data/` is git-ignored and specific to one arm and one camera mount, so a replicator has none.
Here the camera-robot calibration is made from the sim top camera itself: six tool positions over the tray at
`CLIENT_Z` are projected to pixels, exactly the (pixel, tool xyz) pairs the web calibration collects. The poses
`home` and `act_start` are the MEASURED ones taught on the real arm.

    backend/.venv/bin/python -m sim.make_config
"""
from __future__ import annotations

import json
from pathlib import Path

from sim import layout
from sim.measure_layout import project

CONFIG_DIR = Path(__file__).resolve().parent / "config"
TOOL_Z = layout.TRAY_TOP_Z  # the plane of the cell mouths
GRASP_GRID = [(x, y) for x in (0.15, 0.25, 0.35, 0.45) for y in (-0.15, 0.0, 0.15)]  # base-frame xy over the mat
POSES = {
    "home": {"shoulder_pan": 1.010989010989011, "shoulder_lift": -103.25274725274726, "elbow_flex": 97.05494505494505,
             "wrist_flex": 72.48351648351648, "wrist_roll": 0.3076923076923077, "gripper": 10.663021189336979},
    "act_start": {"shoulder_pan": -2.4175824175824174, "shoulder_lift": -103.07692307692308,
                  "elbow_flex": 97.14285714285714, "wrist_flex": 71.95604395604396, "wrist_roll": -8.043956043956044,
                  "gripper": 6.903622693096377},
}


def calibration() -> dict:
    cx, cy = layout.TRAY_CENTER
    hx, hy = layout.TRAY_OUTER_HALF
    points = []
    for fx, fy in ((-1, -1), (-1, 1), (1, 1), (1, -1), (0, 0), (0, 0.5)):
        x, y = layout.to_world((cx + fx * hx, cy + fy * hy))
        u, v = project((x, y, TOOL_Z))
        points.append({"u": u, "v": v, "x": x, "y": y})
    return {"image_size": [640, 480], "points": points}


def grasp_calibration() -> dict:
    """The seed-height calibration: the same camera, the tool tip at the seed centres (box floor plus mean radius)."""
    z = layout.BLACK_BOX.floor_z + sum(layout.SEED_RADIUS.values()) / len(layout.SEED_RADIUS)
    points = []
    for x, y in GRASP_GRID:
        u, v = project((x, y, z))
        points.append({"u": u, "v": v, "x": x, "y": y, "z": z})
    return {"image_size": [640, 480], "points": points}


if __name__ == "__main__":
    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "calibration.json").write_text(json.dumps(calibration(), indent=2) + "\n")
    (CONFIG_DIR / "grasp_calibration.json").write_text(json.dumps(grasp_calibration(), indent=2) + "\n")
    (CONFIG_DIR / "poses.json").write_text(json.dumps(POSES, indent=2) + "\n")
    print(f"wrote {CONFIG_DIR}")
