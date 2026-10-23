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
MIN_HOLE_DEPTH = 0.05  # basin depth, as a share of the frame's depth range; below is noise
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


def find_holes(depth):
    """Holes in a relative depth map, row-major: dicts with normalized x, y, area, depth, row, col."""
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
