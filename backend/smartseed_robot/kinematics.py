from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np

from .robot import ARM_JOINTS

URDF = Path(__file__).resolve().parent.parent / "assets" / "so101" / "so101_new_calib.urdf"
TOLERANCE_M = 0.003
PAN_AXIS_X = 0.0388  # m; the shoulder_pan axis is this far in front of the URDF base origin (see the URDF)
PITCHES_DEG = (0, 15, 30, 45, 60, 75, 90)  # tried in order: the most downward one that reaches wins
PITCH_TOLERANCE_DEG = 10.0
ORIENTATION_WEIGHT = 1.0  # high enough that placo honours the requested approach axis


class IKError(ValueError):
    pass


def pose_above(x: float, y: float, z: float) -> np.ndarray:
    """Target pose with the gripper approach axis (frame z) pointing straight down, yawed towards (x, y)."""
    yaw = math.atan2(y, x - PAN_AXIS_X)
    c, s = math.cos(yaw), math.sin(yaw)
    pose = np.eye(4)
    # frame x points back towards the base, y completes the right-handed frame
    pose[:3, :3] = np.column_stack([[-c, -s, 0], [-s, c, 0], [0, 0, -1]])
    pose[:3, 3] = (x, y, z)
    return pose


def pose_pitched(x: float, y: float, z: float, pitch_deg: float) -> np.ndarray:
    """Like `pose_above`, with the approach axis tilted `pitch_deg` from straight down, radially away from the
    pan axis (in the vertical plane through that axis and (x, y)): 0 = straight down, 90 = horizontal."""
    yaw, pitch = math.atan2(y, x - PAN_AXIS_X), math.radians(pitch_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    approach = np.array([math.sin(pitch) * c, math.sin(pitch) * s, -math.cos(pitch)])
    side = np.array([-s, c, 0.0])  # horizontal, perpendicular to that plane
    pose = np.eye(4)
    pose[:3, :3] = np.column_stack([np.cross(side, approach), side, approach])
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

    def _ik(self, current: np.ndarray, target: np.ndarray, orientation_weight: float) -> np.ndarray:
        # placo only refreshes its kinematics after a solve, not after set_joint: without this the first iteration
        # linearises around wherever the previous (maybe failed) attempt ended and the result depends on call order
        self._kin.forward_kinematics(current)
        return np.array(self._kin.inverse_kinematics(current, target, orientation_weight=orientation_weight)
                        )[: len(ARM_JOINTS)]

    def solve(self, x: float, y: float, z: float, seed: dict[str, float], max_rounds: int = 6,
              pitches: tuple[float, ...] = PITCHES_DEG) -> dict[str, float]:
        return self.solve_with_pitch(x, y, z, seed, max_rounds, pitches)[0]

    def solve_with_pitch(self, x: float, y: float, z: float, seed: dict[str, float], max_rounds: int = 6,
                         pitches: tuple[float, ...] = PITCHES_DEG) -> tuple[dict[str, float], float | None]:
        """Joints for the tool at (x, y, z) plus the pitch used, or None for the position-only fallback.

        The gripper points as far down as the arm allows: straight down first, then tilted outwards in
        steps (`pitches`); only when no tilt reaches does the orientation stop counting."""
        # a folded seed sends the solve to twisted wrists; also start from an arm reaching towards (x, y)
        reaching = np.array([-math.degrees(math.atan2(y, x - PAN_AXIS_X)), 0.0, 0.0, 60.0, seed["wrist_roll"]])  # +pan turns to -y
        starts = (reaching, self._vec(seed))
        position = np.array([x, y, z])
        with self._lock:
            for pitch in pitches:
                target = pose_pitched(x, y, z, pitch)
                for start in starts:
                    current = start
                    for _ in range(max_rounds):
                        current = self._ik(current, target, ORIENTATION_WEIGHT)
                        reached = self._kin.forward_kinematics(current)
                        if np.linalg.norm(reached[:3, 3] - position) < TOLERANCE_M and _angle_deg(
                                reached[:3, 2], target[:3, 2]) < PITCH_TOLERANCE_DEG:
                            return dict(zip(ARM_JOINTS, map(float, current))), float(pitch)
            target = pose_above(x, y, z)
            current = reaching
            for _ in range(max_rounds * 5):
                current = self._ik(current, target, 0.0)
                reached = self._kin.forward_kinematics(current)[:3, 3]
                if np.linalg.norm(reached - position) < TOLERANCE_M:
                    return dict(zip(ARM_JOINTS, map(float, current))), None
        raise IKError(f"target ({x:.3f}, {y:.3f}, {z:.3f}) m is unreachable (missed by "
                      f"{np.linalg.norm(reached - position) * 1000:.0f} mm)")


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(a @ b, -1.0, 1.0))))


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
