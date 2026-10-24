from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np

from .robot import ARM_JOINTS

URDF = Path(__file__).resolve().parent.parent / "assets" / "so101" / "so101_new_calib.urdf"
TOLERANCE_M = 0.003


class IKError(ValueError):
    pass


def pose_above(x: float, y: float, z: float) -> np.ndarray:
    """Target pose with the gripper approach axis (frame z) pointing straight down, yawed towards (x, y)."""
    yaw = math.atan2(y, x)
    c, s = math.cos(yaw), math.sin(yaw)
    pose = np.eye(4)
    # frame x points back towards the base, y completes the right-handed frame
    pose[:3, :3] = np.column_stack([[-c, -s, 0], [-s, c, 0], [0, 0, -1]])
    pose[:3, 3] = (x, y, z)
    return pose


class Kinematics:
    """Thin wrapper over lerobot's placo RobotKinematics for the SO-101 arm joints (degrees)."""

    def __init__(self, urdf: Path = URDF):
        from lerobot.model.kinematics import RobotKinematics

        self._kin = RobotKinematics(str(urdf), "gripper_frame_link", list(ARM_JOINTS))
        self._lock = threading.Lock()  # placo keeps solver state

    @staticmethod
    def _vec(joints: dict[str, float]) -> np.ndarray:
        return np.array([joints[j] for j in ARM_JOINTS], dtype=float)

    def tool_pose(self, joints: dict[str, float]) -> np.ndarray:
        with self._lock:
            return np.array(self._kin.forward_kinematics(self._vec(joints)))

    def tool_xyz(self, joints: dict[str, float]) -> tuple[float, float, float]:
        x, y, z = self.tool_pose(joints)[:3, 3]
        return float(x), float(y), float(z)

    def solve(self, x: float, y: float, z: float, seed: dict[str, float], max_rounds: int = 6) -> dict[str, float]:
        target = pose_above(x, y, z)
        current = self._vec(seed)
        with self._lock:
            for _ in range(max_rounds):
                current = np.array(self._kin.inverse_kinematics(current, target))[: len(ARM_JOINTS)]
                reached = self._kin.forward_kinematics(current)[:3, 3]
                if np.linalg.norm(reached - target[:3, 3]) < TOLERANCE_M:
                    return dict(zip(ARM_JOINTS, map(float, current)))
        raise IKError(f"target ({x:.3f}, {y:.3f}, {z:.3f}) m is unreachable (missed by "
                      f"{np.linalg.norm(reached - target[:3, 3]) * 1000:.0f} mm)")


class LazyKinematics:
    """Loads the URDF on first use so starting the app (and the fake robot) stays cheap."""

    def __init__(self):
        self._kin: Kinematics | None = None
        self._lock = threading.Lock()

    def _get(self) -> Kinematics:
        with self._lock:
            if self._kin is None:
                self._kin = Kinematics()
            return self._kin

    def tool_pose(self, joints):
        return self._get().tool_pose(joints)

    def tool_xyz(self, joints):
        return self._get().tool_xyz(joints)

    def solve(self, x, y, z, seed, **kw):
        return self._get().solve(x, y, z, seed, **kw)
