from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol

from .poses import COLOR_ID
from .robot import JOINTS, RobotPort

TASK = "grasp the seed below the gripper"
ROBOT_TYPE = "so101_follower"
# Mean start of the recorded episodes (pan, lift, elbow, wrist_flex, roll, gripper); used until `act_start` is taught.
ACT_START_FALLBACK = dict(zip(JOINTS, (1.1, -102.7, 96.8, 47.7, -6.0, 6.3)))


class PolicyRunner(Protocol):
    def reset(self) -> None: ...
    def step(self, observation: dict) -> dict[str, float]:
        """Policy frame (`observation.state`, `observation.images.<cam>`) -> joint targets in degrees."""


def _camera(value: str) -> int | str:
    return int(value) if value.isdigit() else value


@dataclass
class ActConfig:
    policies: dict[str, str] = field(default_factory=dict)  # colour -> Hub repo id or local path
    duration_s: float = 10.0
    cam_top: int | str = 0
    cam_wrist: int | str = 1
    device: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.policies)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ActConfig:
        env = os.environ if env is None else env
        raw = env.get("SMARTSEED_ACT_POLICIES", "").strip()
        policies = {}
        if raw:
            try:
                policies = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"SMARTSEED_ACT_POLICIES is not valid JSON: {exc}") from exc
            if not isinstance(policies, dict) or not all(
                    isinstance(k, str) and COLOR_ID.fullmatch(k) and isinstance(v, str) and v
                    for k, v in policies.items()):
                raise ValueError('SMARTSEED_ACT_POLICIES must be a JSON object {"<colour>": "<repo or path>"}')
        return cls(policies, float(env.get("SMARTSEED_ACT_DURATION_S", 10.0)),
                   _camera(env.get("SMARTSEED_CAM_TOP", "0")), _camera(env.get("SMARTSEED_CAM_WRIST", "1")),
                   env.get("SMARTSEED_POLICY_DEVICE") or None)


class ActGrasp:
    """Per-colour ACT policies, loaded on first use. `run` drives one policy closed loop."""

    def __init__(self, config: ActConfig, factory: Callable[[str], PolicyRunner] | None = None):
        self.config = config
        self._factory = factory or (lambda spec: LeRobotActPolicy(spec, config.device))
        self._cache: dict[str, PolicyRunner] = {}

    @property
    def colors(self) -> list[str]:
        return sorted(self.config.policies)

    def has(self, color: str) -> bool:
        return color in self.config.policies

    def policy(self, color: str) -> PolicyRunner:
        if color not in self._cache:
            self._cache[color] = self._factory(self.config.policies[color])
        return self._cache[color]

    def run(self, color: str, robot: RobotPort, stop: threading.Event, hz: float,
            duration_s: float | None = None) -> bool:
        """Closed loop at `hz` for the configured duration. False if `stop` interrupted it (the arm holds)."""
        policy = self.policy(color)
        policy.reset()
        steps = max(1, round((self.config.duration_s if duration_s is None else duration_s) * hz))
        deadline = time.monotonic()
        for _ in range(steps):
            if stop.is_set():
                return False
            action = policy.step(robot.read_observation())
            if stop.is_set():
                return False
            robot.send_joints(action)
            deadline += 1 / hz
            if stop.wait(max(0.0, deadline - time.monotonic())):
                return False
        return True


def pick_device(override: str | None = None) -> str:
    import torch

    if override:
        return override
    return "mps" if torch.backends.mps.is_available() else "cpu"


class LeRobotActPolicy:
    """A lerobot ACT policy with its pre/post processors, loaded the way lerobot's rollout does."""

    def __init__(self, spec: str, device: str | None = None, task: str = TASK):
        import torch
        from lerobot.configs import PreTrainedConfig
        from lerobot.policies import get_policy_class, make_pre_post_processors

        self._device_name = pick_device(device)
        self._device, self._task = torch.device(self._device_name), task
        cfg = PreTrainedConfig.from_pretrained(spec)
        cfg.pretrained_path, cfg.device = spec, self._device_name
        self._policy = get_policy_class(cfg.type).from_pretrained(spec, config=cfg).to(self._device).eval()
        self._pre, self._post = make_pre_post_processors(
            policy_cfg=cfg, pretrained_path=spec, preprocessor_overrides={"device_processor": {"device": self._device_name}})
        self._use_amp = bool(getattr(cfg, "use_amp", False))

    def reset(self) -> None:
        self._policy.reset()
        self._pre.reset()
        self._post.reset()

    def step(self, observation: dict) -> dict[str, float]:
        from lerobot.common.control_utils import predict_action

        action = predict_action(dict(observation), self._policy, self._device, self._pre, self._post,
                                self._use_amp, task=self._task, robot_type=ROBOT_TYPE)
        values = action.squeeze(0).cpu().tolist()
        return dict(zip(JOINTS, map(float, values)))
