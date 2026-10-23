"""Synthetic top-down images of a dark cell tray on a light table."""
import cv2
import numpy as np

CELL_PX = 40
BORDER_PX = 8


def make_tray_image(rows, cols, angle_deg=0.0, center=(320, 240), size=(640, 480), seed=0):
    """Return (BGR image, true corners TL,TR,BR,BL in pixels)."""
    tray_w, tray_h = cols * CELL_PX + 2 * BORDER_PX, rows * CELL_PX + 2 * BORDER_PX
    tray = np.full((tray_h, tray_w), 55, np.uint8)
    for r in range(rows):
        for c in range(cols):
            x0, y0 = BORDER_PX + c * CELL_PX, BORDER_PX + r * CELL_PX
            cv2.rectangle(tray, (x0 + 3, y0 + 3), (x0 + CELL_PX - 4, y0 + CELL_PX - 4), 30, -1)
            cv2.rectangle(tray, (x0 + 1, y0 + 1), (x0 + CELL_PX - 2, y0 + CELL_PX - 2), 85, 1)
    m = cv2.getRotationMatrix2D((tray_w / 2, tray_h / 2), angle_deg, 1.0)
    m[:, 2] += (center[0] - tray_w / 2, center[1] - tray_h / 2)
    w, h = size
    warped = cv2.warpAffine(tray, m, (w, h), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.full_like(tray, 255), m, (w, h), flags=cv2.INTER_LINEAR)
    table = np.full((h, w), 205, np.uint8)
    alpha = mask.astype(np.float32) / 255
    gray = table * (1 - alpha) + warped * alpha
    rng = np.random.default_rng(seed)
    gray = cv2.GaussianBlur(gray, (0, 0), 1.0) + rng.normal(0, 3, gray.shape)
    img = cv2.cvtColor(np.clip(gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    corners = np.array([[0, 0], [tray_w, 0], [tray_w, tray_h], [0, tray_h]], np.float32)
    true = (m[:, :2] @ corners.T).T + m[:, 2]
    return img, true
