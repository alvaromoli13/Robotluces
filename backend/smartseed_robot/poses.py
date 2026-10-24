from __future__ import annotations

import json
import re
from pathlib import Path

from .robot import RobotPort

# Bowl colours are user-defined in the web UI: any id of this shape is a colour. The four
# defaults only decide which poses are required by default.
COLOR_ID = re.compile(r"[a-z][a-z_-]{0,19}")
POSE_NAME = re.compile(r"(?:above_box|grasp)_" + COLOR_ID.pattern)
COLORS = ("red", "yellow", "green", "purple")
REQUIRED_POSES = ("home", *(f"above_box_{c}" for c in COLORS))


class PoseError(ValueError):
    pass


def valid_name(name: str) -> bool:
    return name == "home" or bool(POSE_NAME.fullmatch(name))


class PoseStore:
    """Named joint poses taught by hand, stored as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._poses: dict[str, dict[str, float]] = {}
        if self.path.exists():
            try:
                self._poses = json.loads(self.path.read_text())
            except json.JSONDecodeError as exc:
                raise PoseError(f"{self.path} is corrupt: {exc}") from exc

    def set(self, name: str, joints: dict[str, float]) -> dict[str, float]:
        if not valid_name(name):
            raise PoseError(f"unknown pose '{name}'")
        self._poses[name] = {k: float(v) for k, v in joints.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._poses, indent=2))
        return self._poses[name]

    def teach(self, name: str, robot: RobotPort) -> dict[str, float]:
        return self.set(name, robot.read_joints())

    def get(self, name: str) -> dict[str, float] | None:
        pose = self._poses.get(name)
        return dict(pose) if pose else None

    def all(self) -> dict[str, dict[str, float]]:
        return {k: dict(v) for k, v in self._poses.items()}

    def missing(self, colors: list[str] | tuple[str, ...] = COLORS) -> list[str]:
        needed = ["home", *(f"above_box_{c}" for c in colors)]
        return [n for n in needed if n not in self._poses]
