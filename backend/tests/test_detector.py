import numpy as np

from smartseed_vision.detector import best_box


def test_best_box_picks_highest_score_and_clips_to_image():
    boxes = np.array([[10, 10, 50, 50], [-5, 20, 700, 500]], float)
    scores = np.array([0.2, 0.6])
    assert best_box(boxes, scores, (640, 480)) == ((0, 20, 640, 480), 0.6)


def test_best_box_none_when_empty():
    assert best_box(np.zeros((0, 4)), np.zeros(0), (640, 480)) is None
