from pathlib import Path

import cv2
import numpy as np

from smartseed_vision.occupancy import mark_occupied

FIXTURES = Path(__file__).parent / "fixtures"

# Holes and tray corners as the backend returned them for the two real top-camera frames.
STONES_TRAY = [[0.4171, 0.3646], [0.7400, 0.3359], [0.7547, 0.6303], [0.4318, 0.6590]]
STONES_HOLES = [
    (0, 0, 0.4725, 0.3987, 0.00284), (0, 1, 0.5442, 0.3984, 0.00315), (0, 2, 0.6206, 0.3943, 0.00356),
    (0, 3, 0.6950, 0.3850, 0.00245), (1, 0, 0.4746, 0.4985, 0.00331), (1, 1, 0.5471, 0.4962, 0.00365),
    (1, 2, 0.6207, 0.4913, 0.00372), (1, 3, 0.6922, 0.4802, 0.00225), (2, 0, 0.4754, 0.5890, 0.00289),
    (2, 1, 0.5483, 0.5841, 0.00261), (2, 2, 0.6214, 0.5874, 0.00381), (2, 3, 0.6953, 0.5776, 0.00288),
]
EMPTY_TRAY = [[0.4976, 0.3925], [0.8301, 0.2971], [0.8801, 0.6072], [0.5476, 0.7026]]
EMPTY_HOLES = [
    (0, 0, 0.5512, 0.4244, 0.00289), (0, 1, 0.6312, 0.4139, 0.00431), (0, 2, 0.7082, 0.3858, 0.00349),
    (0, 3, 0.7855, 0.3662, 0.00363), (1, 0, 0.5671, 0.5274, 0.00343), (1, 1, 0.6402, 0.5109, 0.00343),
    (1, 2, 0.7196, 0.4919, 0.00398), (1, 3, 0.7980, 0.4692, 0.00362), (2, 0, 0.5797, 0.6244, 0.00342),
    (2, 1, 0.6568, 0.6053, 0.00302), (2, 2, 0.7319, 0.5822, 0.00279), (2, 3, 0.8072, 0.5662, 0.00311),
]


def holes(rows):
    return [{"row": r, "col": c, "x": x, "y": y, "area": a, "depth": 0.2} for r, c, x, y, a in rows]


def occupied(result):
    return {(h["row"], h["col"]) for h in result if h["occupied"]}


def test_real_frame_flags_only_the_cell_with_stones():
    img = cv2.imread(str(FIXTURES / "real_tray_stones.png"))
    result = mark_occupied(img, holes(STONES_HOLES), STONES_TRAY)
    assert occupied(result) == {(2, 2)}
    assert all(0.0 <= h["fill_score"] for h in result)


def test_real_empty_tray_has_no_occupied_cells():
    img = cv2.imread(str(FIXTURES / "real_tray_empty.png"))
    assert occupied(mark_occupied(img, holes(EMPTY_HOLES), EMPTY_TRAY)) == set()


def synthetic_tray(filled):
    """Beige tray with a 3x4 grid of slightly darker cells; `filled` cells hold grey speckled pebbles."""
    rng = np.random.default_rng(0)
    img = np.full((480, 640, 3), (70, 60, 60), np.uint8)
    x0, y0, cw, ch = 160, 120, 80, 80
    cv2.rectangle(img, (x0, y0), (x0 + 4 * cw, y0 + 3 * ch), (150, 185, 205), -1)
    rows = []
    for r in range(3):
        for c in range(4):
            cx, cy = x0 + c * cw + cw // 2, y0 + r * ch + ch // 2
            cv2.circle(img, (cx, cy), 28, (125, 160, 180), -1)
            if (r, c) in filled:
                for _ in range(40):
                    p = (int(cx + rng.integers(-18, 19)), int(cy + rng.integers(-18, 19)))
                    cv2.circle(img, p, 4, tuple(int(v) for v in rng.integers(40, 120, 3)), -1)
            rows.append((r, c, cx / 640, cy / 480, np.pi * 28 ** 2 / (640 * 480)))
    tray = [[x0 / 640, y0 / 480], [(x0 + 4 * cw) / 640, y0 / 480], [(x0 + 4 * cw) / 640, (y0 + 3 * ch) / 480],
            [x0 / 640, (y0 + 3 * ch) / 480]]
    return img, holes(rows), tray


def test_most_cells_full_still_compares_against_the_cardboard_not_the_other_cells():
    filled = {(r, c) for r in range(3) for c in range(4)} - {(0, 0), (2, 3)}
    img, hs, tray = synthetic_tray(filled)
    assert occupied(mark_occupied(img, hs, tray)) == filled


def test_without_tray_or_holes_nothing_is_flagged():
    img, hs, _ = synthetic_tray({(1, 1)})
    assert mark_occupied(img, [], None) == []
    assert all(h["occupied"] is False for h in mark_occupied(img, hs, None))
