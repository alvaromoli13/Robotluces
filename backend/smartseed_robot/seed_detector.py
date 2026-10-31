"""Seed detector for the top camera: classic CV, no model, no sim-only input.

A seed is a small round blob that is much darker (black seeds) or much less saturated (white seeds) than the
cardboard floor it lies on (holes in a blob are filled: real black seeds shine in the middle). The boxes are found by their floor colour: the seed colour mask is kept only inside the
cardboard mask closed over seed-sized holes, so a dark mat, a black box wall, an arm shadow or the tray dividers
never count (the tray cells are cardboard too: seeds dropped in a cell would be found there as well). The centre is a
weighted centroid of how far each pixel is from the local floor colour, which is sub-pixel.

`seeds_to_robot` maps pixel centres to base-frame metres with the homography of `calibration.Calibration`. That
homography is a single plane: calibrate it with the tool tip at seed-centre height (box floor plus seed radius), not
at the tray top, or every seed lands off by (distance from the optical axis) x (height gap) / (camera height).
"""
from __future__ import annotations

import cv2
import numpy as np

from .calibration import Calibration

COLORS = ("black", "white")
CARDBOARD_HUE = (5, 28)  # OpenCV hue, 0-179: orange-brown
CARDBOARD_SAT = (60, 190)  # the orange arm plastic is the same hue at about 245
CARDBOARD_MIN_VAL = 70
CLOSE_PX = 5  # closing of the seed mask: a shiny seed's reflection can read as cardboard and split the mask in a C
FILL_PX = 25  # closing kernel: wider than a seed (about 15 px across at 640x480) so a seed counts as inside the floor
AREA_PX = (60, 450)  # a seed covers about 150 px
MIN_ASPECT, MIN_EXTENT = 0.6, 0.6  # bounding-box shortest/longest side, and blob area / box area (a disc gives 0.79)
BLACK_VALUE_RATIO = 0.45  # black: brightness below this share of the floor's
WHITE_SAT_RATIO, WHITE_VALUE_RATIO = 0.45, 0.6  # white: saturation below this share of the floor's, not dark
RING_PX = (4, 12)  # inner and outer radius of the ring that samples the floor colour around a blob
MIN_RING_FLOOR = 0.7  # share of that ring that must be floor: a seed lies inside the floor, a wall chunk on its edge does not


def _cardboard(hsv: np.ndarray) -> np.ndarray:
    h, s, v = cv2.split(hsv)
    return ((h >= CARDBOARD_HUE[0]) & (h <= CARDBOARD_HUE[1]) & (s >= CARDBOARD_SAT[0]) & (s <= CARDBOARD_SAT[1]) & (v >= CARDBOARD_MIN_VAL)).astype(np.uint8)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Solid blobs: a shiny black seed has a light reflection in the middle, so its dark mask is a ring (real frames)."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    return filled


def _round_enough(stats_row) -> bool:
    w, h, area = int(stats_row[cv2.CC_STAT_WIDTH]), int(stats_row[cv2.CC_STAT_HEIGHT]), int(stats_row[cv2.CC_STAT_AREA])
    return AREA_PX[0] <= area <= AREA_PX[1] and min(w, h) / max(w, h) >= MIN_ASPECT and area / (w * h) >= MIN_EXTENT


def _centre(rgb: np.ndarray, blob: np.ndarray, floor: np.ndarray) -> tuple[float, float] | None:
    """Centroid of the distance to the local floor colour, over the blob plus a 2 px rim of anti-aliased edge; None
    when the blob is not surrounded by floor."""
    ring = cv2.dilate(blob, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * RING_PX[1] + 1,) * 2))
    ring &= 1 - cv2.dilate(blob, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * RING_PX[0] + 1,) * 2))
    around = int(ring.sum())
    ring &= floor
    if ring.sum() < 20 or ring.sum() < MIN_RING_FLOOR * around:
        return None
    background = np.median(rgb[ring > 0].astype(np.float32), axis=0)
    near = cv2.dilate(blob, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    ys, xs = np.nonzero(near)
    distance = np.linalg.norm(rgb[ys, xs].astype(np.float32) - background, axis=1)
    top = np.percentile(distance[blob[ys, xs] > 0], 90)
    if top <= 0:
        return None
    weight = np.clip(distance / top, 0.0, 1.0)
    return float((weight * xs).sum() / weight.sum()), float((weight * ys).sum() / weight.sum())


def detect_seeds(rgb: np.ndarray, color: str) -> list[tuple[float, float]]:
    """Pixel centres (u, v), sub-pixel, of the `color` seeds in a top frame (HxWx3 RGB uint8), left to right."""
    if color not in COLORS:
        raise ValueError(f"color must be one of {COLORS}, got {color!r}")
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"expected an HxWx3 RGB frame, got shape {rgb.shape}")
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    floor = _cardboard(hsv)
    if floor.sum() < AREA_PX[1]:
        return []
    inside = cv2.morphologyEx(floor, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FILL_PX, FILL_PX)))
    h, s, v = (c.astype(np.float32) for c in cv2.split(hsv))
    floor_s, floor_v = np.median(s[floor > 0]), np.median(v[floor > 0])
    if color == "black":
        mask = v < BLACK_VALUE_RATIO * floor_v
    else:
        mask = (s < WHITE_SAT_RATIO * floor_s) & (v > WHITE_VALUE_RATIO * floor_v)
    mask = (mask & (inside > 0) & (floor == 0)).astype(np.uint8)
    if color == "black":  # white has no such split, and closing it would join the light edges of the tray cells
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CLOSE_PX, CLOSE_PX)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = _fill_holes(mask)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        if _round_enough(stats[i]):
            centre = _centre(rgb, (labels == i).astype(np.uint8), floor)
            if centre is not None:
                found.append(centre)
    return sorted(found)


def seeds_to_robot(calibration: Calibration, centres, image_size=None) -> np.ndarray:
    """Base-frame (x, y) metres of pixel centres, shape (n, 2), through the calibration homography."""
    return np.array([calibration.pixel_to_robot(u, v, image_size) for u, v in centres], dtype=float).reshape(-1, 2)
