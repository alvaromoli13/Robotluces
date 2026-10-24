"""Is something already sitting in a tray cell?

Each hole's interior is compared with the bare tray material, sampled on the rim between the
holes, not with the other holes: that keeps working when most cells are already full. A cell is
occupied when its colour moves away from the rim (chroma in Lab, so shadows do not count) or when
its brightness turns busy (pebbles, seeds and their shadows). Measured on the real cardboard tray:
empty cells stay at chroma <= 4.5 and std <= 16, a cell with stones reaches 17 and 30.
"""
import cv2
import numpy as np

CHROMA_LIMIT = 9.0  # Lab a/b distance from the rim
TEXTURE_LIMIT = 22.0  # std of L inside the hole
PATCH = 0.45  # patch radius as a fraction of the hole's equivalent radius
RIM_SHRINK = 0.92  # stay away from the tray edge, where the table shows through
RIM_CLEARANCE = 1.8  # keep the rim samples this many patch radii away from every hole


def _radius(hole, w, h):
    return max(4, int(PATCH * np.sqrt(hole["area"] * w * h / np.pi)))


def mark_occupied(img, holes, tray):
    """Return copies of `holes` with `occupied` (bool) and `fill_score` (>= 1 means occupied)."""
    if not holes:
        return []
    if tray is None:
        return [{**hole, "occupied": False, "fill_score": 0.0} for hole in holes]
    h, w = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    quad = np.asarray(tray, np.float32) * [w, h]
    centre = quad.mean(axis=0)
    rim = np.zeros((h, w), np.uint8)
    cv2.fillPoly(rim, [(centre + (quad - centre) * RIM_SHRINK).astype(np.int32)], 1)
    centres = [(int(hole["x"] * w), int(hole["y"] * h), _radius(hole, w, h)) for hole in holes]
    for x, y, r in centres:
        cv2.circle(rim, (x, y), int(r * RIM_CLEARANCE), 0, -1)
    if not rim.any():
        return [{**hole, "occupied": False, "fill_score": 0.0} for hole in holes]
    ref = np.median(lab[rim > 0][:, 1:], axis=0)
    out = []
    for hole, (x, y, r) in zip(holes, centres):
        mask = np.zeros((h, w), np.uint8)
        cv2.circle(mask, (x, y), r, 1, -1)
        px = lab[mask > 0]
        chroma = float(np.hypot(*(np.median(px[:, 1:], axis=0) - ref)))
        score = max(chroma / CHROMA_LIMIT, float(px[:, 0].std()) / TEXTURE_LIMIT)
        out.append({**hole, "occupied": score >= 1.0, "fill_score": round(score, 3)})
    return out
