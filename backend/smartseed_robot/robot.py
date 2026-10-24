from __future__ import annotations

from typing import Protocol

ARM_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
JOINTS = (*ARM_JOINTS, "gripper")  # degrees, gripper 0-100


class RobotPort(Protocol):
    def read_joints(self) -> dict[str, float]: ...
    def send_joints(self, target: dict[str, float]) -> None: ...
    def torque_off(self) -> None: ...
    def close(self) -> None: ...


class FakeRobot:
    """Instant fake arm that records every command. Never touches hardware.

    `grasp_script` is consumed once per gripper closing: True = the seed stops the jaws (gripper stays
    open at `held_value`), False = empty grasp (jaws close fully). Once exhausted every grasp succeeds.
    """

    CLOSING_BELOW = 10.0

    def __init__(self, initial: dict[str, float] | None = None, grasp_script: list[bool] | None = None,
                 held_value: float = 25.0):
        self._state = dict.fromkeys(JOINTS, 0.0) | (initial or {})
        self._script = list(grasp_script or [])
        self._held_value = held_value
        self._closing = False
        self._holding = False
        self.commands: list[dict[str, float]] = []
        self.history: list[dict[str, float]] = []
        self.torque_enabled = True
        self.closed = False

    def read_joints(self) -> dict[str, float]:
        return dict(self._state)

    def send_joints(self, target: dict[str, float]) -> None:
        self.commands.append(dict(target))
        state = self._state | target
        if "gripper" in target:
            state["gripper"] = self._gripper(target["gripper"])
        self._state = state
        self.history.append(dict(state))

    def _gripper(self, value: float) -> float:
        if value > self.CLOSING_BELOW:
            self._closing = self._holding = False
            return value
        if not self._closing:
            self._closing = True
            self._holding = self._script.pop(0) if self._script else True
        return max(value, self._held_value) if self._holding else value

    def torque_off(self) -> None:
        self.torque_enabled = False

    def close(self) -> None:
        self.closed = True


class LeRobotFollower:
    """Adapter over lerobot's SO101Follower. Imports lerobot lazily so tests never need hardware."""

    def __init__(self, port: str, robot_id: str = "follower_01", max_relative_target: float = 8.0):
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        config = SO101FollowerConfig(port=port, id=robot_id, use_degrees=True,
                                     max_relative_target=max_relative_target,
                                     disable_torque_on_disconnect=False)
        self._robot = SO101Follower(config)
        self._robot.connect(calibrate=False)

    def read_joints(self) -> dict[str, float]:
        obs = self._robot.get_observation()
        return {j: float(obs[f"{j}.pos"]) for j in JOINTS}

    def send_joints(self, target: dict[str, float]) -> None:
        self._robot.send_action({f"{j}.pos": float(v) for j, v in target.items()})

    def torque_off(self) -> None:
        self._robot.bus.disable_torque()

    def close(self) -> None:
        self._robot.disconnect()
