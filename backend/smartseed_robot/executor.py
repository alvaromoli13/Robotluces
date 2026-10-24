from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .act import ACT_START_FALLBACK, ActGrasp
from .calibration import Calibration, CalibrationError
from .kinematics import IKError, Kinematics
from .motion import MotionConfig, move_to
from .poses import COLOR_ID, PoseStore
from .robot import ARM_JOINTS, RobotPort


class PlanError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class PlanBusy(PlanError):
    def __init__(self):
        super().__init__(409, "busy", "a plan is already running")


class Stopped(Exception):
    pass


@dataclass
class ExecutorConfig:
    hz: float = 30.0
    max_speed: float = 45.0
    settle_s: float = 0.3  # let the jaws settle before judging the grasp
    drop_z: float = 0.06  # tool height (m, robot base frame) above the cell when releasing
    gripper_open: float = 60.0
    gripper_closed: float = 0.0
    empty_below: float = 8.0  # gripper reading under this after closing = nothing inside
    retries: int = 1
    grasp_deltas: dict[str, float] = field(default_factory=dict)  # used when no grasp_<color> pose is taught


class Grasper(Protocol):
    def grasp(self, color: str, move: Callable[[dict[str, float]], None], current: Callable[[], dict[str, float]]) -> None:
        """From the above-box pose, close the gripper on a seed. `move` raises Stopped on stop."""


class TaughtGrasp:
    """Lower by a taught `grasp_<color>` pose or taught joint deltas, then close. Lifting is the executor's job."""

    def __init__(self, poses: PoseStore, cfg: ExecutorConfig):
        self.poses, self.cfg = poses, cfg

    def grasp(self, color, move, current):
        low = self.poses.get(f"grasp_{color}")
        if low:
            move({**low, "gripper": self.cfg.gripper_open})
        elif self.cfg.grasp_deltas:
            now = current()
            move({j: now[j] + d for j, d in self.cfg.grasp_deltas.items()})
        move({"gripper": self.cfg.gripper_closed})


class Executor:
    def __init__(self, robot: RobotPort, poses: PoseStore, calibration: Calibration, kin: Kinematics,
                 grasper: Grasper | None = None, config: ExecutorConfig | None = None, mode: str = "fake",
                 act: ActGrasp | None = None):
        self.robot, self.poses, self.calibration, self.kin = robot, poses, calibration, kin
        self.cfg = config or ExecutorConfig()
        self.grasper = grasper or TaughtGrasp(poses, self.cfg)
        self.mode, self.act = mode, act
        self.events: list[dict] = []
        self.plan_start_index = 0
        self.retries: list[int] = []
        self._motion = MotionConfig(self.cfg.hz, self.cfg.max_speed)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state, self._plan_id, self._current = "idle", None, None
        self._done: list[int] = []
        self._failed: list[int] = []

    @property
    def running(self) -> bool:
        return self._state in ("running", "stopping")

    def status(self) -> dict:
        return {"state": self._state, "robot": self.mode, "plan_id": self._plan_id, "current_cell": self._current,
                "done": list(self._done), "failed": list(self._failed), "calibrated": self.calibration.fitted,
                "poses": sorted(self.poses.all()), "policies": self.act.colors if self.act else []}

    def stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self._state = "stopping"
        self._stop.set()
        return True

    def join(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def start(self, plan: list[dict], image_size) -> str:
        plan_id = self._begin(plan, image_size)
        self._thread = threading.Thread(target=self._execute, args=(plan, image_size, plan_id), daemon=True)
        self._thread.start()
        return plan_id

    def run(self, plan: list[dict], image_size) -> str:
        plan_id = self._begin(plan, image_size)
        self._execute(plan, image_size, plan_id)
        return plan_id

    # -- validation -------------------------------------------------------------------------------------
    def _begin(self, plan, image_size) -> str:
        with self._lock:
            if self.running:
                raise PlanBusy
            self._validate(plan, image_size)
            self._stop.clear()
            self._state, self._plan_id, self._current = "running", uuid.uuid4().hex[:8], None
            self._done, self._failed, self.retries = [], [], []
            return self._plan_id

    def _validate(self, plan, image_size) -> None:
        keys = {"cell_index", "row", "col", "color", "u", "v"}
        if not plan or any(not keys <= set(c) for c in plan) or len(image_size) != 2:
            raise PlanError(422, "invalid", "plan needs image_size [w, h] and cells with " + ", ".join(sorted(keys)))
        bad = sorted({str(c["color"]) for c in plan if not COLOR_ID.fullmatch(str(c["color"]))})
        if bad:
            raise PlanError(422, "invalid", f"invalid colour id {bad}; expected lowercase letters, _ or -, up to 20")
        if not self.calibration.fitted:
            raise PlanError(409, "no_calibration", "no calibration fitted: add >= 4 points and fit first")
        missing = self.poses.missing(sorted({c["color"] for c in plan if not self._acts(c["color"])}))
        if missing:
            raise PlanError(409, "missing_pose", f"missing taught poses: {', '.join(missing)}")
        seed = self.poses.get("home")
        unreachable = []
        for c in plan:
            try:
                self.kin.solve(*self.calibration.pixel_to_robot(c["u"], c["v"], image_size), self.cfg.drop_z,
                               seed={j: seed[j] for j in ARM_JOINTS})
            except (IKError, CalibrationError):
                unreachable.append(c["cell_index"])
        if unreachable:
            raise PlanError(422, "unreachable", f"cells not reachable by the arm: {unreachable}")

    # -- execution --------------------------------------------------------------------------------------
    def _emit(self, type_: str, cell_index=None, message=None, **extra) -> None:
        self.events.append({"type": type_, "plan_id": self._plan_id, "cell_index": cell_index, "message": message,
                            **extra})

    def _move(self, target: dict[str, float]) -> None:
        if not move_to(self.robot, target, self._stop, self._motion):
            raise Stopped

    def _execute(self, plan, image_size, plan_id) -> None:
        self.plan_start_index = len(self.events)
        self._emit("plan_started", message=f"{len(plan)} cells", total=len(plan))
        try:
            for c in plan:
                self._current = c["cell_index"]
                self._emit("cell_started", c["cell_index"], row=c["row"], col=c["col"], color=c["color"],
                           total=len(plan))
                ok = self._plant(c, image_size)
                (self._done if ok else self._failed).append(c["cell_index"])
                self._emit("cell_done" if ok else "cell_failed", c["cell_index"],
                           None if ok else "gripper stayed empty after retry")
            self._current = None
            self._emit("finished", message=f"{len(self._done)} done, {len(self._failed)} failed")
            self._state = "idle"
        except Stopped:
            self._current = None
            self._emit("stopped", message="stopped by user; the arm holds its position")
            self._state = "idle"
        except Exception as exc:  # the arm holds position: never cut torque mid-air on our own
            self._emit("error", self._current, f"{type(exc).__name__}: {exc}")
            self._state = "error"

    def _acts(self, color: str) -> bool:
        return self.act is not None and self.act.has(color)

    def _holding(self) -> bool:
        if self._stop.wait(self.cfg.settle_s):
            raise Stopped
        return self.robot.read_joints()["gripper"] > self.cfg.empty_below

    def _plant_with_policy(self, c, image_size) -> bool:
        cfg = self.cfg
        start = self.poses.get("act_start") or ACT_START_FALLBACK
        self._move(start)
        if not self.act.run(c["color"], self.robot, self._stop, cfg.hz):
            raise Stopped
        now = self.robot.read_joints()  # the policy leaves the seed in the closed gripper
        x, y = self.calibration.pixel_to_robot(c["u"], c["v"], image_size)
        target = self.kin.solve(x, y, cfg.drop_z, seed={j: now[j] for j in ARM_JOINTS})
        self._move({**target, "gripper": now["gripper"]})
        self._move({"gripper": cfg.gripper_open})
        self._move(start)
        return True

    def _plant(self, c, image_size) -> bool:
        cfg, color = self.cfg, c["color"]
        if self._acts(color):
            return self._plant_with_policy(c, image_size)
        home, box = self.poses.get("home"), self.poses.get(f"above_box_{color}")
        opened = {"gripper": cfg.gripper_open}
        self._move({**home, **opened})
        for attempt in range(cfg.retries + 1):
            self._move({**box, **opened})
            self.grasper.grasp(color, self._move, self.robot.read_joints)
            if self._holding():
                break
            if attempt < cfg.retries:
                self.retries.append(c["cell_index"])
            else:
                self._move({**box, **opened})
                self._move({**home, **opened})
                return False
        self._move({**box, "gripper": self.robot.read_joints()["gripper"]})  # lift with the seed
        now = self.robot.read_joints()
        x, y = self.calibration.pixel_to_robot(c["u"], c["v"], image_size)
        target = self.kin.solve(x, y, cfg.drop_z, seed={j: now[j] for j in ARM_JOINTS})
        self._move({**target, "gripper": now["gripper"]})
        self._move(opened)
        self._move({**home, **opened})
        return True
