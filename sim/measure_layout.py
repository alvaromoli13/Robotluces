"""Back-project pixels of the real top frame onto the scene to get the metric layout in `sim/layout.py`.

The pixel coordinates below were read by eye off `act_white_top.png` (a real 640x480 top frame of the final setup,
tray 3 columns x 4 rows); each lands on a plane of known height with the *fitted* top camera
(`layout.TOP_CAMERA_*`), so metric errors are about the pixel reading error (~3 px, ~3 mm) plus the camera fit.
It also solves for the tool height of the four calibration clicks. Prints, does not write.

    backend/.venv/bin/python sim/measure_layout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import layout  # noqa: E402

FOVY, POS = np.radians(layout.TOP_CAMERA_FOVY), np.array(layout.TOP_CAMERA_POS)
_x, _y = np.array(layout.TOP_CAMERA_XYAXES[:3]), np.array(layout.TOP_CAMERA_XYAXES[3:])
ROT = np.column_stack([_x, _y, np.cross(_x, _y)])  # camera axes in the base frame (x right, y up, z backwards)
F = 0.5 * 480 / np.tan(FOVY / 2)


def project(point) -> tuple[float, float]:
    p = ROT.T @ (np.asarray(point) - POS)
    return 320 + F * p[0] / -p[2], 240 - F * p[1] / -p[2]


def backproject(u: float, v: float, z: float) -> np.ndarray:
    ray = ROT @ np.array([(u - 320) / F, -(v - 240) / F, -1.0])
    return POS + ray * (z - POS[2]) / ray[2]


# pixel features of act_white_top.png (u, v), TL TR BR BL
FEATURES = {
    "tray rim (top z=%.3f)" % layout.TRAY_TOP_Z: ([(253, 100), (399, 100), (396, 287), (257, 287)], layout.TRAY_TOP_Z),
    "white box rim": ([(122, 272), (228, 268), (236, 430), (133, 443)], layout.WHITE_BOX.top_z),
    "black box rim": ([(440, 276), (562, 270), (556, 430), (437, 432)], layout.BLACK_BOX.top_z),
    "mat (left/right/top edges; bottom edge hidden, guessed v=445)": (
        [(118, 52), (553, 49), (556, 445), (115, 445)], layout.MAT_TOP_Z),
}
SEEDS_PX = {"white": [(175, 314), (181, 366)], "black": [(501, 340), (531, 385)]}


def to_board(xy) -> np.ndarray:
    """Base-frame xy -> board frame (x' up in the image, y' left, origin at the base, rotated by BOARD_YAW)."""
    c, s = np.cos(-layout.BOARD_YAW), np.sin(-layout.BOARD_YAW)
    return np.array([[c, -s], [s, c]]) @ np.asarray(xy)


def main() -> None:
    print(f"board yaw {np.degrees(layout.BOARD_YAW):.2f} deg (image up in the base frame)")
    for name, (pixels, z) in FEATURES.items():
        pts = np.array([to_board(backproject(u, v, z)[:2]) for u, v in pixels])
        lo, hi = pts.min(0), pts.max(0)
        print(f"{name}: board-frame corners {np.round(pts, 3).tolist()}\n    centre {np.round((lo + hi) / 2, 3)} "
              f"size x' {hi[0] - lo[0]:.3f} y' {hi[1] - lo[1]:.3f}")
    for color, pixels in SEEDS_PX.items():
        print(color, "seeds (board frame) at", [np.round(to_board(backproject(u, v, 0.0)[:2]), 3).tolist()
                                              for u, v in pixels])
    pts = layout.CALIBRATION_POINTS
    zs = np.linspace(-0.02, 0.12, 141)
    err = [np.mean([np.hypot(*(np.array(project((x, y, z))) - (u, v))) for u, v, x, y in pts]) for z in zs]
    best = int(np.argmin(err))
    print(f"calibration clicks: best tool z {zs[best]:.3f} m, mean reprojection error {err[best]:.2f} px "
          f"(at z={layout.CALIBRATION_TOOL_Z}: {np.interp(layout.CALIBRATION_TOOL_Z, zs, err):.2f} px)")
    base_px = project((layout.BASE_PAN_AXIS[0], 0.0, 0.06))
    print(f"robot shoulder axis (0.0388, 0, ~0.06) projects to pixel {np.round(base_px, 1)}")


if __name__ == "__main__":
    main()
