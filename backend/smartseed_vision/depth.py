"""Seed holes from monocular depth: compartments are basins enclosed by walls.

Depth Anything gives relative depth (higher = closer). The table around a box is just as
low as a compartment floor, so "deep" is not enough: a hole is a basin that cannot drain
to the frame border without climbing over a wall. Grayscale hole filling (morphological
reconstruction from the border) finds exactly those basins.
"""
import threading

import cv2
import numpy as np

MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
WORK_WIDTH = 320  # smaller maps blur thin walls between compartments into one basin
MIN_HOLE_DEPTH = 0.035  # basin depth, as a share of the frame's depth range; real noise reached 0.026
MIN_HOLE_AREA_FRAC = 0.002
HOLE_LEVEL = 0.25  # pixels deeper than this share of their basin's max depth form the hole


def fill_basins(depth):
    """How far each pixel is below the level water would fill it to, draining at the border."""
    marker = np.full_like(depth, depth.max())
    marker[0, :], marker[-1, :], marker[:, 0], marker[:, -1] = depth[0, :], depth[-1, :], depth[:, 0], depth[:, -1]
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(depth.size):
        nxt = np.maximum(cv2.erode(marker, kernel), depth)
        if np.array_equal(nxt, marker):
            break
        marker = nxt
    return marker - depth


def _row_gap(holes):
    """y jump that starts a new row: half the typical spacing between neighbouring holes.

    A hole's own height is too small for this, because often only the lower part of a
    compartment looks deep, and a tilted box shifts side-by-side holes vertically.
    """
    if len(holes) < 2:
        return holes[0]["_h"] / 2 if holes else 0.0
    pts = np.array([[h["x"], h["y"]] for h in holes])
    dist = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    np.fill_diagonal(dist, np.inf)
    return max(float(np.median(dist.min(axis=1))), max(h["_h"] for h in holes)) / 2


def assign_rows(holes):
    """Group holes (dicts with x, y, _h) into rows by y, sort each row by x, set row and col."""
    gap = _row_gap(holes)
    rows, current = [], []
    for hole in sorted(holes, key=lambda h: h["y"]):
        if current and hole["y"] - np.mean([h["y"] for h in current]) > gap:
            rows.append(current)
            current = []
        current.append(hole)
    if current:
        rows.append(current)
    ordered = []
    for r, row in enumerate(rows):
        for c, hole in enumerate(sorted(row, key=lambda h: h["x"])):
            hole.update(row=r, col=c)
            hole.pop("_h")
            ordered.append(hole)
    return ordered


REGION_MARGIN = 0.1  # grow the tray quad by 10% around its centre before testing hole centres
MIN_KEPT_BY_TRAY = 0.75  # a tray quad that would drop more holes than this is itself wrong
ISOLATION = 3.0  # a basin farther than this many median spacings from any other is not a cell


def _drop_isolated(holes):
    if len(holes) < 3:
        return holes
    pts = np.array([[h["x"], h["y"]] for h in holes])
    dist = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    np.fill_diagonal(dist, np.inf)
    nearest = dist.min(axis=1)
    limit = ISOLATION * float(np.median(nearest))
    return [h for h, d in zip(holes, nearest) if d <= limit]


def _inside(region, x, y):
    quad = np.asarray(region, np.float32)
    centre = quad.mean(axis=0)
    grown = centre + (quad - centre) * (1 + REGION_MARGIN)
    return cv2.pointPolygonTest(grown.reshape(-1, 1, 2), (float(x), float(y)), False) >= 0


def find_holes(depth, tray=None):
    """Holes in a relative depth map, row-major: dicts with normalized x, y, area, depth, row, col.

    Basins far from every other one (the robot gripper, a cup at the edge) are dropped. `tray`
    (normalized quad, e.g. the detected tray corners) also drops basins outside the tray, unless it
    would drop a large share of them: then the quad is the wrong one and is ignored.
    """
    depth = np.asarray(depth, np.float32)
    span = float(np.ptp(depth))
    if span < 1e-6:
        return []
    scale = min(1.0, WORK_WIDTH / depth.shape[1])
    small = cv2.resize(depth, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else depth
    small = (small - small.min()) / span
    basins = fill_basins(small)
    h, w = small.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats((basins > 0).astype(np.uint8))
    holes = []
    for i in range(1, count):
        region = labels == i
        peak = float(basins[region].max())
        if peak < MIN_HOLE_DEPTH:
            continue
        core = region & (basins > HOLE_LEVEL * peak)
        area = core.sum() / small.size
        if area < MIN_HOLE_AREA_FRAC:
            continue
        ys, xs = np.nonzero(core)
        holes.append({"x": (xs.mean() + 0.5) / w, "y": (ys.mean() + 0.5) / h, "area": float(area),
                      "depth": peak, "_h": (ys.max() - ys.min() + 1) / h})
    holes = _drop_isolated(holes)
    if tray is not None:
        inside = [hole for hole in holes if _inside(tray, hole["x"], hole["y"])]
        if len(inside) >= MIN_KEPT_BY_TRAY * len(holes):
            holes = inside
    return assign_rows(holes)


class DepthEstimator:
    """Lazy-loads Depth Anything V2 on first use; `estimate` takes a BGR frame."""

    def __init__(self, model_id=MODEL_ID):
        self.model_id = model_id
        self.loaded = False
        self.device = "unloaded"
        self._lock = threading.Lock()

    def load(self):
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self._torch = torch
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._processor = AutoImageProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForDepthEstimation.from_pretrained(self.model_id).to(self.device).eval()
        self.loaded = True

    def estimate(self, image_bgr):
        """Relative depth (higher = closer) at the model's output resolution."""
        from PIL import Image

        with self._lock:
            if not self.loaded:
                self.load()
            image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
            inputs = self._processor(images=image, return_tensors="pt").to(self.device)
            with self._torch.no_grad():
                depth = self._model(**inputs).predicted_depth
            return depth.squeeze().float().cpu().numpy()


def grid_in_tray(holes, tray, rows, cols):
    """Renumber holes by their position inside the tray quad (TL, TR, BR, BL, normalized).

    Grouping by image y splits a row in two once the tray is rotated; mapping the centres into the
    tray's own square fixes that. Returns None if two holes land in the same cell, so the caller can
    keep the image-space numbering.
    """
    quad = np.asarray(tray, np.float32)
    square = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    warp = cv2.getPerspectiveTransform(quad, square)
    pts = np.float32([[h["x"], h["y"]] for h in holes]).reshape(-1, 1, 2)
    uv = cv2.perspectiveTransform(pts, warp).reshape(-1, 2)
    out, seen = [], set()
    for hole, (u, v) in zip(holes, uv):
        cell = (min(max(int(v * rows), 0), rows - 1), min(max(int(u * cols), 0), cols - 1))
        if cell in seen:
            return None
        seen.add(cell)
        out.append({**hole, "row": cell[0], "col": cell[1]})
    return sorted(out, key=lambda h: (h["row"], h["col"]))
