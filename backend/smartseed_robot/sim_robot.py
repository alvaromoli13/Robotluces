"""`SimRobot`: the SO-101 + SmartSeed scene in MuJoCo behind the `RobotPort` contract.

Joint mapping (applied only here): arm joints are lerobot calibrated degrees <-> MJCF radians (the new-calibration
MJCF puts every joint zero at mid-range, like lerobot's `use_degrees`); the gripper is lerobot 0-100 <-> the jaw
angle through a linear map (`GRIPPER_JAW_RAD`).

Time: each `send_joints` applies one control period (1/hz s) of physics, so simulated time only moves when the
controller commands; the executor's own 30 Hz wall-clock sleeps make a plan play in real time. Cameras are rendered
offscreen on demand (one MuJoCo `Renderer`, hence one GL context, per calling thread)."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from .robot import ARM_JOINTS, CAMERAS, IMAGE_SHAPE, JOINTS

# Jaw angle (rad) at lerobot gripper 0 and 100. The slope is the real follower's calibrated span (2034..3497 ticks =
# 128.6 deg for 0-100), the offset is fitted against the real wrist frames (sim/fit_wrist_camera.py). The MJCF jaw
# joint stops at 100 deg (gripper ~87) and at -3.5 deg (gripper 6.0): the real follower's hard stop, where it reads
# closed empty. The jaw pads do not touch there (10.9 mm apart at the tip); a seed keeps the jaw off the stop by
# contact alone (sim/README.md).
GRIPPER_JAW_RAD = (-0.1954, 2.0488)
DEFAULT_SCENE = Path(__file__).resolve().parents[2] / "sim" / "scene.xml"
DEFAULT_HOME = dict(zip(JOINTS, (1.1, -102.7, 96.8, 47.7, -6.0, 6.3)))  # mean start of the recorded episodes


def deg_to_rad(deg):
    return np.deg2rad(deg)


def gripper_to_jaw(value: float) -> float:
    lo, hi = GRIPPER_JAW_RAD
    return lo + (hi - lo) * float(value) / 100.0


def jaw_to_gripper(rad: float) -> float:
    lo, hi = GRIPPER_JAW_RAD
    return 100.0 * (float(rad) - lo) / (hi - lo)


def joints_to_qpos(joints: dict[str, float]) -> np.ndarray:
    """lerobot joints (deg, gripper 0-100) -> MJCF qpos/ctrl in JOINTS order (rad)."""
    return np.array([*(deg_to_rad(joints[j]) for j in ARM_JOINTS), gripper_to_jaw(joints["gripper"])])


def qpos_to_joints(qpos) -> dict[str, float]:
    return {**{j: float(np.rad2deg(q)) for j, q in zip(ARM_JOINTS, qpos[:5])}, "gripper": jaw_to_gripper(qpos[5])}


class SimRobot:
    def __init__(self, initial: dict[str, float] | None = None, scene: str | Path | None = None, hz: float = 30.0,
                 max_relative_target: float = 8.0, record_dir: str | Path | None = None, viewer: bool = False):
        import mujoco

        self._mj = mujoco
        self._model = mujoco.MjModel.from_xml_path(str(scene or os.environ.get("SMARTSEED_SIM_SCENE") or DEFAULT_SCENE))
        self._data = mujoco.MjData(self._model)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._renderers: list = []
        self._substeps = max(1, round(1.0 / (hz * self._model.opt.timestep)))
        self._hz, self._max_rel = hz, max_relative_target
        self._qadr = [self._model.joint(j).qposadr[0] for j in JOINTS]
        self._ctrl = joints_to_qpos(DEFAULT_HOME | (initial or {}))
        self._data.qpos[self._qadr] = self._ctrl
        self._data.ctrl[:] = self._ctrl
        mujoco.mj_forward(self._model, self._data)
        self.torque_enabled = True
        self.closed = False
        self._record_dir = Path(record_dir) if record_dir else None
        self._writer = None
        self._viewer = self._launch_viewer() if viewer else None
        self.step_hook = None  # optional callable(model, data) run after every physics step (the wall monitor)

    # -- RobotPort ---------------------------------------------------------------------------------------
    @property
    def sim_time(self) -> float:
        return float(self._data.time)

    def read_joints(self) -> dict[str, float]:
        with self._lock:
            return qpos_to_joints(self._data.qpos[self._qadr])

    def read_observation(self) -> dict[str, np.ndarray]:
        with self._lock:
            state = qpos_to_joints(self._data.qpos[self._qadr])
            frame = {"observation.state": np.array([state[j] for j in JOINTS], dtype=np.float32)}
            return frame | {f"observation.images.{cam}": self.render(cam) for cam in CAMERAS}

    def cameras_ok(self) -> bool:
        return not self.closed

    def reconnect_cameras(self) -> None:
        """Nothing to reopen: the cameras are virtual."""

    def send_joints(self, target: dict[str, float]) -> None:
        """Same clamp as the real follower (each goal at most `max_relative_target` from the present position),
        then one control period of physics. A torque-off arm holds still (a limp arm is not simulated)."""
        with self._lock:
            if self.torque_enabled and target:
                present = qpos_to_joints(self._data.qpos[self._qadr])
                goal = {j: present[j] + float(np.clip(v - present[j], -self._max_rel, self._max_rel))
                        for j, v in target.items()}
                self._ctrl = joints_to_qpos(present | goal)
            elif not self.torque_enabled:
                self._ctrl = self._data.qpos[self._qadr].copy()
            self._step()

    def torque_off(self) -> None:
        with self._lock:
            self.torque_enabled = False
            self._ctrl = self._data.qpos[self._qadr].copy()

    def torque_on(self) -> None:
        with self._lock:  # hold where the arm is now, like the real follower
            self._ctrl = self._data.qpos[self._qadr].copy()
            self.torque_enabled = True

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.end_plan()
        if self._viewer is not None:
            self._viewer.close()
        for renderer in self._renderers:
            try:
                renderer.close()
            except Exception:  # a context owned by a thread that already ended
                pass
        self._renderers.clear()

    # -- physics -----------------------------------------------------------------------------------------
    def _step(self) -> None:
        self._data.ctrl[:] = self._ctrl
        for _ in range(self._substeps):
            self._mj.mj_step(self._model, self._data)
            if self.step_hook is not None:
                self.step_hook(self._model, self._data)
        if self._viewer is not None:
            self._viewer.sync()
        if self._writer is not None:
            self._writer.append_data(self.render("top"))

    # -- rendering, recording, viewer --------------------------------------------------------------------
    def render(self, camera: str) -> np.ndarray:
        """HWC uint8 RGB frame of `top` or `wrist` (a Renderer per calling thread)."""
        renderer = getattr(self._local, "renderer", None)
        if renderer is None:
            renderer = self._local.renderer = self._mj.Renderer(self._model, IMAGE_SHAPE[0], IMAGE_SHAPE[1])
            self._renderers.append(renderer)
        with self._lock:
            renderer.update_scene(self._data, camera=camera)
        return renderer.render().copy()

    def begin_plan(self, plan_id: str) -> None:
        """Executor hook: with a record dir, every plan is filmed from the top camera into `plan-<id>.mp4`."""
        if self._record_dir is not None:
            self.start_recording(self._record_dir / f"plan-{plan_id}.mp4")

    def end_plan(self) -> None:
        self.stop_recording()

    def start_recording(self, path: str | Path) -> None:
        import imageio.v2 as imageio

        self.stop_recording()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._writer = imageio.get_writer(str(path), fps=self._hz, codec="libx264", macro_block_size=1)

    def stop_recording(self) -> None:
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()

    def _launch_viewer(self):
        try:
            import mujoco.viewer

            return mujoco.viewer.launch_passive(self._model, self._data)
        except RuntimeError as exc:  # macOS: the passive viewer only works under `mjpython`
            raise RuntimeError(f"SMARTSEED_SIM_VIEWER=1 failed ({exc}); on macOS start the backend with "
                               "`uv run mjpython -m uvicorn ...` (see sim/README.md)") from exc
