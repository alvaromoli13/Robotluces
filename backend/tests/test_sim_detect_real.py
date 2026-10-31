"""`sim/detect_real.py`: the seed detector on frames of the real LeRobot datasets (helpers only; no dataset needed)."""
from __future__ import annotations

import imageio.v2 as imageio
import numpy as np
import pytest

from sim import detect_real


def test_sampled_episodes_are_spread_evenly_and_never_repeat():
    picked = detect_real.sample_episodes(96, 12)
    assert picked[0] == 0 and picked[-1] == 95 and len(picked) == 12 and picked == sorted(set(picked))
    assert detect_real.sample_episodes(5, 12) == [0, 1, 2, 3, 4]
    assert detect_real.sample_episodes(10, 1) == [0]


def test_frame_at_returns_the_frame_of_that_timestamp(tmp_path):
    path = tmp_path / "top.mp4"
    with imageio.get_writer(str(path), fps=30, codec="libx264", macro_block_size=1) as w:
        for i in range(30):
            w.append_data(np.full((48, 64, 3), (10 * i, 255 - 8 * i, 90), np.uint8))
    for index in (0, 9, 20):
        frame = detect_real.frame_at(path, index / 30)
        assert frame.shape == (48, 64, 3)
        assert frame[24, 32] == pytest.approx((10 * index, 255 - 8 * index, 90), abs=12)


def test_annotating_draws_a_circle_per_detection_and_leaves_the_input_alone():
    frame = np.full((480, 640, 3), 128, np.uint8)
    shown = detect_real.annotate(frame, [(200.0, 300.0), (400.0, 250.0)], "x")
    assert (frame == 128).all()
    assert tuple(shown[300, 212]) == (0, 255, 0) or tuple(shown[300, 211]) == (0, 255, 0)  # on the ring, 12 px right
    assert tuple(shown[300, 200]) == (128, 128, 128)  # the middle of the seed stays visible
