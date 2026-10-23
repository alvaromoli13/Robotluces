"""Tray quad + grid size from a camera frame. Pure OpenCV/numpy, no model needed."""
from dataclasses import dataclass

import cv2
import numpy as np

MIN_TRAY_AREA_FRAC = 0.02  # ignore specks smaller than this share of the search area
MIN_CELL_PX = 8


@dataclass
class TrayGeometry:
    corners_px: list  # [[x, y]] * 4 in full-image pixels, TL, TR, BR, BL
    rows: int
    cols: int
    confidence: float  # 0..1, mean autocorrelation strength of both axes


def order_corners(pts):
    """Order 4 points as TL, TR, BR, BL (valid for rotations well under 45 degrees)."""
    pts = np.asarray(pts, np.float32)
    s, d = pts.sum(axis=1), pts[:, 0] - pts[:, 1]
    return np.array([pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()]], np.float32)


def find_tray_quad(img, bbox=None):
    """Largest dark blob inside bbox (x0, y0, x1, y1) as 4 ordered corners, or None."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (0, 0, w, h) if bbox is None else (max(0, int(bbox[0])), max(0, int(bbox[1])),
                                                         min(w, int(bbox[2])), min(h, int(bbox[3])))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (0, 0), 2)
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = max(contours, key=cv2.contourArea)
    if cv2.contourArea(best) < MIN_TRAY_AREA_FRAC * gray.size:
        return None
    box = cv2.boxPoints(cv2.minAreaRect(best)) + (x0, y0)
    return order_corners(box)


def warp_tray(img, quad):
    """Perspective-warp the quad to an upright rectangle sized from its edge lengths."""
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    height = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (width, height))


def _count_cells(profile):
    """(count, confidence) from the periodicity of a 1-D gradient profile."""
    n = len(profile)
    p = profile - profile.mean()
    if n < 2 * MIN_CELL_PX or p.std() < 1e-6:
        return 1, 0.0
    ac = np.correlate(p, p, "full")[n - 1:]
    ac = ac / ac[0]
    lags = np.arange(MIN_CELL_PX, n // 2)
    peaks = [lag for lag in lags if ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1] and ac[lag] > 0]
    if not peaks:
        return 1, 0.0
    top = max(ac[lag] for lag in peaks)
    # the first strong peak is the fundamental; later ones are its harmonics
    lag = next(lag for lag in peaks if ac[lag] >= 0.8 * top)
    # parabolic refinement of the peak position
    a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
    denom = a - 2 * b + c
    period = lag + (0.5 * (a - c) / denom if denom else 0.0)
    return max(1, int(round(n / period))), float(np.clip(ac[lag], 0, 1))


def estimate_grid(warped):
    """(rows, cols, confidence) of the cell pattern in an upright, tray-only image."""
    gray = cv2.GaussianBlur(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (0, 0), 1).astype(np.float32)
    h, w = gray.shape
    my, mx = h // 20, w // 20  # skip the tray edge, it dominates the gradients
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0))[my:h - my, mx:w - mx]
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))[my:h - my, mx:w - mx]
    cols, conf_c = _count_cells(gx.mean(axis=0))
    rows, conf_r = _count_cells(gy.mean(axis=1))
    return rows, cols, (conf_r + conf_c) / 2


def analyze_tray(img, bbox=None):
    """Full pipeline on a BGR frame; None when no dark tray-like blob is found."""
    quad = find_tray_quad(img, bbox)
    if quad is None:
        return None
    rows, cols, confidence = estimate_grid(warp_tray(img, quad))
    return TrayGeometry(quad.tolist(), rows, cols, confidence)
