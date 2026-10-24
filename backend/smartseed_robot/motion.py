from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from .robot import RobotPort


@dataclass
class MotionConfig:
    hz: float = 30.0
    max_speed: float = 45.0  # deg/s (gripper units/s) on the slowest-limiting joint


def move_to(robot: RobotPort, target: dict[str, float], stop: threading.Event, cfg: MotionConfig) -> bool:
    """Linear joint-space move. Returns False if `stop` interrupted it (the arm then simply holds)."""
    if stop.is_set():
        return False
    start = robot.read_joints()
    delta = {j: v - start[j] for j, v in target.items()}
    longest = max((abs(d) for d in delta.values()), default=0.0)
    steps = max(1, math.ceil(longest / cfg.max_speed * cfg.hz))
    for i in range(1, steps + 1):
        robot.send_joints({j: start[j] + d * i / steps for j, d in delta.items()})
        if stop.wait(1 / cfg.hz) and i < steps:  # the wait doubles as the control-period sleep
            return False
    return True
