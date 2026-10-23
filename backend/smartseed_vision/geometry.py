"""Tray quad + grid size from a camera frame. Pure OpenCV/numpy, no model needed."""
from dataclasses import dataclass

import cv2
import numpy as np

MIN_TRAY_AREA_FRAC = 0.01  # ignore specks smaller than this share of the search area
MIN_CELL_PX = 12  # smaller periods are edges inside one cell
MIN_PERIOD_STRENGTH = 0.25  # weaker autocorrelation peaks are noise, not cells
MAX_PERIOD_FRAC = 0.6  # 2 cells give ~0.5; a single cell's own walls give 0.65+
MIN_NESTED_CONFIDENCE = 0.35  # a blob inside the best one wins with at least this grid confidence
MAX_NESTED_AREA_FRAC = 0.6  # ...and when clearly smaller (box on a mat), not the same object
MAX_CANDIDATES_PER_POLARITY = 2


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


def _is_background(contour, w, h, margin=2):
    """Table or paper: touches 3+ sides of the frame. A tray overhanging one edge is kept."""
    x, y, cw, ch = cv2.boundingRect(contour)
    return sum((x <= margin, y <= margin, x + cw >= w - margin, y + ch >= h - margin)) >= 3


def tray_candidates(img, bbox=None):
    """Ordered corner quads of dark, light and coloured blobs inside bbox (x0, y0, x1, y1).

    The tray can be darker (plastic tray on a table) or lighter (cardboard box on a mat)
    than its surroundings, so both polarities are tried. Cardboard walls in shadow are as
    dark as the mat, so saturated (coloured) blobs are tried too. Without a bbox, blobs touching
    most of the frame border are background (table, paper) and are skipped.
    """
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (0, 0, w, h) if bbox is None else (max(0, int(bbox[0])), max(0, int(bbox[1])),
                                                         min(w, int(bbox[2])), min(h, int(bbox[3])))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []
    roi = img[y0:y1, x0:x1]
    gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (0, 0), 2)
    sat = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)[..., 1], (0, 0), 2)
    quads = []
    for channel, mode in ((gray, cv2.THRESH_BINARY_INV), (gray, cv2.THRESH_BINARY), (sat, cv2.THRESH_BINARY)):
        if channel.std() < 1e-6:  # e.g. no colour at all in a grey image
            continue
        _, mask = cv2.threshold(channel, 0, 255, mode + cv2.THRESH_OTSU)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        # CCOMP keeps blobs that sit inside a hole of another blob (box on a mat on paper)
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        outer = [c for c, hier in zip(contours, hierarchy[0]) if hier[3] == -1] if contours else []
        contours = [c for c in outer if cv2.contourArea(c) >= MIN_TRAY_AREA_FRAC * gray.size
                    and (bbox is not None or not _is_background(c, *gray.shape[::-1]))]
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:MAX_CANDIDATES_PER_POLARITY]:
            quads.append(order_corners(cv2.boxPoints(cv2.minAreaRect(c)) + (x0, y0)))
    return quads


def find_tray_quad(img, bbox=None):
    """Largest tray-like blob inside bbox as 4 ordered corners, or None."""
    quads = tray_candidates(img, bbox)
    return max(quads, key=lambda q: cv2.contourArea(q)) if quads else None


def warp_tray(img, quad):
    """Perspective-warp the quad to an upright rectangle sized from its edge lengths."""
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    height = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (width, height))


def _count_cells(profile):
    """(count, confidence) from the periodicity of a 1-D gradient profile.

    Confidence is None when no period is found, i.e. a single cell along this axis.
    """
    n = len(profile)
    p = profile - profile.mean()
    if n < 2 * MIN_CELL_PX or p.std() < 1e-6:
        return 1, None
    # unbiased autocorrelation (divided by the overlap), so long periods are not damped
    ac = np.correlate(p, p, "full")[n - 1:] / (n - np.arange(n))
    ac = ac / ac[0]
    lags = np.arange(MIN_CELL_PX, int(n * MAX_PERIOD_FRAC))
    peaks = [lag for lag in lags if ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1]
             and ac[lag] > MIN_PERIOD_STRENGTH]
    if not peaks:
        return 1, None
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
    # an axis with a single cell has no period to measure, so only periodic axes count
    confs = [c for c in (conf_r, conf_c) if c is not None]
    return rows, cols, (sum(confs) / len(confs) if confs else 0.0)


def _contains(outer, inner):
    """True when inner's center lies inside outer and inner is clearly smaller."""
    center = tuple(float(v) for v in inner.mean(axis=0))
    return (cv2.contourArea(inner) < MAX_NESTED_AREA_FRAC * cv2.contourArea(outer)
            and cv2.pointPolygonTest(outer, center, False) > 0)


def analyze_tray(img, bbox=None):
    """Full pipeline on a BGR frame; None when no tray-like blob is found.

    Keeps the candidate with the clearest cell pattern, but a candidate sitting inside it
    with a clear pattern of its own wins: the tray is the object on the mat, not the mat.
    """
    scored = []
    for quad in tray_candidates(img, bbox):
        rows, cols, confidence = estimate_grid(warp_tray(img, quad))
        scored.append((quad, TrayGeometry(quad.tolist(), rows, cols, confidence)))
    if not scored:
        return None
    best_quad, best = max(scored, key=lambda s: s[1].confidence)
    nested = [g for q, g in scored if g.confidence >= MIN_NESTED_CONFIDENCE and _contains(best_quad, q)]
    return max(nested, key=lambda g: g.confidence) if nested else best
