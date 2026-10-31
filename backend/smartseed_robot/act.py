from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .catalog import resolve_spec
from .poses import COLOR_ID
from .robot import JOINTS, RobotPort

TASK = "grasp the seed below the gripper"
ROBOT_TYPE = "so101_follower"
# Goal-conditioned ACT (T5g): the target seed (x, y), robot base frame, metres. A policy trained with it declares it in
# its config (`env_state_feature`); the caller then adds this key to the observation.
ENV_STATE_KEY = "observation.environment_state"
# Mean start of the recorded episodes (pan, lift, elbow, wrist_flex, roll, gripper); used until `act_start` is taught.
ACT_START_FALLBACK = dict(zip(JOINTS, (1.1, -102.7, 96.8, 47.7, -6.0, 6.3)))


class PolicyRunner(Protocol):
    def reset(self) -> None: ...
    def step(self, observation: dict) -> dict[str, float]:
        """Policy frame (`observation.state`, `observation.images.<cam>`, and `observation.environment_state` for a
        policy that sets `wants_environment_state`) -> joint targets in degrees."""


def _camera(value: str) -> int | str:
    return int(value) if value.isdigit() else value


@dataclass
class ActConfig:
    policies: dict[str, str] = field(default_factory=dict)  # colour -> Hub repo id or local path
    duration_s: float = 10.0
    cam_top: int | str = 0
    cam_wrist: int | str = 1
    device: str | None = None
    debug_dir: Path | None = None  # per-run loop timing and the first camera frames, for diagnosis

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
                   env.get("SMARTSEED_POLICY_DEVICE") or None,
                   Path(env["SMARTSEED_ACT_DEBUG_DIR"]) if env.get("SMARTSEED_ACT_DEBUG_DIR") else None)


class ActGrasp:
    """Per-colour ACT policies, loaded on first use. `run` drives one policy closed loop. `select` swaps the
    policy of a colour at runtime; the env config stays the default."""

    def __init__(self, config: ActConfig, factory: Callable[[str], PolicyRunner] | None = None,
                 resolver: Callable[[str, str | None], str] | None = None):
        self.config = config
        self._factory = factory or (lambda spec: LeRobotActPolicy(spec, config.device))
        self._resolver = resolver or resolve_spec
        self._cache: dict[str, PolicyRunner] = {}
        self._chosen: dict[str, tuple[str, str | None, str]] = {}  # colour -> (repo, checkpoint, spec to load)
        self._lock = threading.Lock()

    @property
    def colors(self) -> list[str]:
        return sorted(self.config.policies)

    def has(self, color: str) -> bool:
        return color in self.config.policies

    def active(self) -> dict[str, dict]:
        with self._lock:
            return {c: self._describe(c) for c in self.colors}

    def _describe(self, color: str) -> dict:
        repo, checkpoint, _ = self._chosen.get(color, (self.config.policies[color], None, None))
        return {"repo": repo, "checkpoint": checkpoint,
                "default": (repo, checkpoint) == (self.config.policies[color], None)}

    def select(self, color: str, repo: str, checkpoint: str | None = None) -> None:
        """Use `repo` (at `checkpoint`, None = the final model) for `color` from the next run. Resolving may download;
        if it fails nothing changes. The model itself loads lazily."""
        if color not in self.config.policies:
            raise KeyError(color)
        spec = self._resolver(repo, checkpoint)
        with self._lock:
            self._chosen[color] = (repo, checkpoint, spec)
            self._cache.pop(color, None)

    def policy(self, color: str) -> PolicyRunner:
        with self._lock:
            if color not in self._cache:
                spec = self._chosen[color][2] if color in self._chosen else self.config.policies[color]
                self._cache[color] = self._factory(spec)
            return self._cache[color]

    def run(self, color: str, robot: RobotPort, stop: threading.Event, hz: float,
            duration_s: float | None = None) -> bool:
        """Closed loop at `hz` for the configured duration. False if `stop` interrupted it (the arm holds)."""
        policy = self.policy(color)
        policy.reset()
        steps = max(1, round((self.config.duration_s if duration_s is None else duration_s) * hz))
        period, late, worst, done = 1 / hz, 0, 0.0, 0
        deadline = time.monotonic()
        try:
            if not robot.cameras_ok():
                robot.reconnect_cameras()
                deadline = time.monotonic()
            for done in range(steps):
                if stop.is_set():
                    return False
                started = time.monotonic()
                observation = self._observe(robot)
                if done == 0:
                    self._save_frames(color, observation)
                action = policy.step(observation)
                if stop.is_set():
                    return False
                robot.send_joints(action)
                worst = max(worst, time.monotonic() - started)
                deadline += period
                if deadline < time.monotonic():  # behind: restart the period instead of bursting the backlog
                    late, deadline = late + 1, time.monotonic() + period
                if stop.wait(max(0.0, deadline - time.monotonic())):
                    return False
            done = steps
            return True
        finally:
            self._log(color, done, late, worst)

    @staticmethod
    def _observe(robot: RobotPort) -> dict:
        """One observation; if a camera died (or a frame went stale) reopen the cameras and read again once."""
        try:
            return robot.read_observation()
        except Exception:
            if robot.cameras_ok():
                raise
            robot.reconnect_cameras()
            return robot.read_observation()

    def _log(self, color: str, steps: int, late: int, worst: float) -> None:
        if self.config.debug_dir:
            self.config.debug_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config.debug_dir / "act_timing.log", "a") as log:
                log.write(f"{time.strftime('%H:%M:%S')} {color} steps={steps} late={late} max_ms={worst * 1000:.0f}\n")

    def _save_frames(self, color: str, observation: dict) -> None:
        if not self.config.debug_dir:
            return
        import cv2

        self.config.debug_dir.mkdir(parents=True, exist_ok=True)
        for key, image in observation.items():
            if key.startswith("observation.images."):
                cam = key.rsplit(".", 1)[1]
                cv2.imwrite(str(self.config.debug_dir / f"act_{color}_{cam}.png"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))


def pick_device(override: str | None = None) -> str:
    import torch

    if override:
        return override
    return "mps" if torch.backends.mps.is_available() else "cpu"


def apply_inference_overrides(cfg, n_action_steps: int | None = None, temporal_ensemble_coeff: float | None = None):
    """Change how a trained ACT executes its chunks (no retraining). By default it plays all `chunk_size` actions open
    loop; fewer steps re-plan more often, and temporal ensembling (the ACT paper's mode) re-plans every step."""
    if temporal_ensemble_coeff is not None:
        if n_action_steps not in (None, 1):
            raise ValueError("temporal ensembling runs one action per inference: n_action_steps must be 1")
        cfg.temporal_ensemble_coeff, cfg.n_action_steps = temporal_ensemble_coeff, 1
    elif n_action_steps is not None:
        if not 1 <= n_action_steps <= cfg.chunk_size:
            raise ValueError(f"n_action_steps must be within 1..{cfg.chunk_size}, got {n_action_steps}")
        cfg.n_action_steps = n_action_steps
    return cfg


class LeRobotActPolicy:
    """A lerobot ACT policy with its pre/post processors, loaded the way lerobot's rollout does."""

    def __init__(self, spec: str, device: str | None = None, task: str = TASK, *,
                 n_action_steps: int | None = None, temporal_ensemble_coeff: float | None = None):
        import torch
        from lerobot.configs import PreTrainedConfig
        from lerobot.policies import get_policy_class, make_pre_post_processors

        self._device_name = pick_device(device)
        self._device, self._task = torch.device(self._device_name), task
        cfg = PreTrainedConfig.from_pretrained(spec)
        cfg.pretrained_path, cfg.device = spec, self._device_name
        apply_inference_overrides(cfg, n_action_steps, temporal_ensemble_coeff)
        self._policy = get_policy_class(cfg.type).from_pretrained(spec, config=cfg).to(self._device).eval()
        self._pre, self._post = make_pre_post_processors(
            policy_cfg=cfg, pretrained_path=spec, preprocessor_overrides={"device_processor": {"device": self._device_name}})
        self._use_amp = bool(getattr(cfg, "use_amp", False))
        self.wants_environment_state = cfg.env_state_feature is not None

    def reset(self) -> None:
        self._policy.reset()
        self._pre.reset()
        self._post.reset()

    def step(self, observation: dict) -> dict[str, float]:
        from lerobot.common.control_utils import predict_action

        if self.wants_environment_state and ENV_STATE_KEY not in observation:
            raise ValueError(f"this policy takes the target seed position: the observation needs {ENV_STATE_KEY}")
        action = predict_action(dict(observation), self._policy, self._device, self._pre, self._post,
                                self._use_amp, task=self._task, robot_type=ROBOT_TYPE)
        values = action.squeeze(0).cpu().tolist()
        return dict(zip(JOINTS, map(float, values)))
