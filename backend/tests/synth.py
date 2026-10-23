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


def make_box_on_mat_image(rows, cols, cell_px=120, size=(800, 640), seed=0):
    """Light cardboard box with compartments on a dark mat over white paper.

    Return (BGR image, true box corners TL,TR,BR,BL in pixels).
    """
    w, h = size
    gray = np.full((h, w), 235, np.float32)  # white paper, touches the frame border
    cv2.rectangle(gray, (60, 50), (w - 60, h - 50), 70, -1)  # dark mat, larger than the box
    box_w, box_h = cols * cell_px + 2 * BORDER_PX, rows * cell_px + 2 * BORDER_PX
    x0, y0 = (w - box_w) // 2, (h - box_h) // 2
    cv2.rectangle(gray, (x0, y0), (x0 + box_w, y0 + box_h), 215, -1)  # walls
    for r in range(rows):
        for c in range(cols):
            cx, cy = x0 + BORDER_PX + c * cell_px, y0 + BORDER_PX + r * cell_px
            cv2.rectangle(gray, (cx + 4, cy + 4), (cx + cell_px - 5, cy + cell_px - 5), 165, -1)  # floor
    rng = np.random.default_rng(seed)
    gray = cv2.GaussianBlur(gray, (0, 0), 1.0) + rng.normal(0, 3, gray.shape)
    img = cv2.cvtColor(np.clip(gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    true = np.array([[x0, y0], [x0 + box_w, y0], [x0 + box_w, y0 + box_h], [x0, y0 + box_h]], np.float32)
    return img, true


def make_cardboard_box_image(rows, cols, cell_px=120, size=(800, 640), seed=0):
    """Tan cardboard box on a grey mat over white paper, with its bottom wall in shadow.

    The shadowed wall is as dark as the mat, so only colour (saturation) separates it.
    Return (BGR image, true box corners TL,TR,BR,BL in pixels).
    """
    w, h = size
    img = np.full((h, w, 3), 235, np.float32)
    cv2.rectangle(img, (60, 50), (w - 60, h - 50), (80, 72, 70), -1)  # grey-blue mat
    box_w, box_h = cols * cell_px + 2 * BORDER_PX, rows * cell_px + 2 * BORDER_PX
    x0, y0 = (w - box_w) // 2, (h - box_h) // 2
    cv2.rectangle(img, (x0, y0), (x0 + box_w, y0 + box_h), (120, 170, 215), -1)  # lit walls
    shadow = 30
    cv2.rectangle(img, (x0, y0 + box_h - shadow), (x0 + box_w, y0 + box_h), (35, 65, 105), -1)
    for r in range(rows):
        for c in range(cols):
            cx, cy = x0 + BORDER_PX + c * cell_px, y0 + BORDER_PX + r * cell_px
            cv2.rectangle(img, (cx + 4, cy + 4), (cx + cell_px - 5, cy + cell_px - 5), (95, 140, 185), -1)
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(img, (0, 0), 1.0) + rng.normal(0, 3, img.shape)
    true = np.array([[x0, y0], [x0 + box_w, y0], [x0 + box_w, y0 + box_h], [x0, y0 + box_h]], np.float32)
    return np.clip(img, 0, 255).astype(np.uint8), true


def make_box_depth(rows, cols, size=(320, 240), seed=0, angle_deg=0.0):
    """Relative depth map (higher = closer, like Depth Anything) of a box with compartments.

    The table is a tilted plane, the box walls stand out from it and each compartment floor
    sits back down at table level. Return (depth, true hole centers normalized, row-major).
    """
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    depth = 0.2 + 0.3 * (1 - yy / h) + 0.05 * xx / w  # tilted table
    box_w, box_h = int(w * 0.6), int(h * 0.6)
    x0, y0 = (w - box_w) // 2, (h - box_h) // 2
    wall = 6
    depth[y0:y0 + box_h, x0:x0 + box_w] += 0.35
    cell_w, cell_h = (box_w - wall) / cols, (box_h - wall) / rows
    centers = []
    for r in range(rows):
        for c in range(cols):
            cx0, cy0 = int(x0 + wall + c * cell_w), int(y0 + wall + r * cell_h)
            cx1, cy1 = int(x0 + (c + 1) * cell_w), int(y0 + (r + 1) * cell_h)
            depth[cy0:cy1, cx0:cx1] -= 0.35
            centers.append(((cx0 + cx1) / 2 / w, (cy0 + cy1) / 2 / h))
    if angle_deg:
        table = 0.2 + 0.3 * (1 - yy / h) + 0.05 * xx / w
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
        box = cv2.warpAffine(depth - table, m, (w, h), flags=cv2.INTER_LINEAR)
        depth = table + box
        centers = [tuple((m[:, :2] @ [x * w, y * h] + m[:, 2]) / [w, h]) for x, y in centers]
    rng = np.random.default_rng(seed)
    depth = cv2.GaussianBlur(depth, (0, 0), 1.5) + rng.normal(0, 0.003, depth.shape).astype(np.float32)
    return depth.astype(np.float32), centers
