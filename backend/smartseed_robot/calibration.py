from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


class CalibrationError(ValueError):
    pass


class Calibration:
    """Pixel -> robot (x, y) homography fitted from pairs (pixel, tool position from FK)."""

    def __init__(self):
        self.points: list[dict] = []
        self.image_size: tuple[int, int] | None = None
        self.homography: np.ndarray | None = None

    @property
    def fitted(self) -> bool:
        return self.homography is not None

    def add_point(self, u: float, v: float, x: float, y: float, image_size) -> None:
        size = (int(image_size[0]), int(image_size[1]))
        if self.image_size not in (None, size):
            raise CalibrationError(f"all points must use image size {self.image_size}, got {size}")
        self.image_size = size
        self.points.append({"u": float(u), "v": float(v), "x": float(x), "y": float(y)})
        self.homography = None  # the old fit no longer matches the points

    def clear(self) -> None:
        self.__init__()

    def fit(self) -> dict:
        if len(self.points) < 4:
            raise CalibrationError(f"need at least 4 points, have {len(self.points)}")
        src = np.array([[p["u"], p["v"]] for p in self.points], np.float64)
        dst = np.array([[p["x"], p["y"]] for p in self.points], np.float64)
        h, _ = cv2.findHomography(src, dst, 0)
        if h is None:
            raise CalibrationError("points are degenerate (collinear or repeated)")
        self.homography = h
        errors = np.array([np.hypot(*(np.subtract(self.pixel_to_robot(u, v), (x, y))))
                           for (u, v), (x, y) in zip(src, dst)]) * 1000
        return {"n": len(self.points), "mean_error_mm": float(errors.mean()), "max_error_mm": float(errors.max())}

    def pixel_to_robot(self, u: float, v: float, image_size=None) -> tuple[float, float]:
        if self.homography is None:
            raise CalibrationError("calibration is not fitted")
        if image_size is not None and self.image_size is not None:
            u, v = u * self.image_size[0] / image_size[0], v * self.image_size[1] / image_size[1]
        x, y, w = self.homography @ np.array([u, v, 1.0])
        return float(x / w), float(y / w)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"image_size": self.image_size, "points": self.points}, indent=2))

    @classmethod
    def load(cls, path: Path) -> Calibration:
        cal = cls()
        path = Path(path)
        if not path.exists():
            return cal
        data = json.loads(path.read_text())
        for p in data["points"]:
            cal.add_point(p["u"], p["v"], p["x"], p["y"], data["image_size"])
        if len(cal.points) >= 4:
            cal.fit()
        return cal
