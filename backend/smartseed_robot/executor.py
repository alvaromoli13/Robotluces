from __future__ import annotations

import math
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


MODES = ("full", "grasp", "place")  # full = grasp + place; the others are the two halves, for debugging
DROP_Z_RANGE = (0.02, 0.25)  # m; accepted per-run override of ExecutorConfig.drop_z


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
    approach_clearance: float = 0.08  # m above drop_z where the arm hovers before descending (and lifts back to)
    place_tolerance_m: float = 0.005  # xy miss over the cell that is still accepted when releasing
    place_corrections: int = 2  # extra moves, aiming past the cell by the measured shortfall (servo sag)
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
        self._mode, self._drop_z = "full", self.cfg.drop_z
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

    def start(self, plan: list[dict], image_size, mode: str = "full", drop_z: float | None = None) -> str:
        plan_id = self._begin(plan, image_size, mode, drop_z)
        self._thread = threading.Thread(target=self._execute, args=(plan, image_size, plan_id), daemon=True)
        self._thread.start()
        return plan_id

    def run(self, plan: list[dict], image_size, mode: str = "full", drop_z: float | None = None) -> str:
        plan_id = self._begin(plan, image_size, mode, drop_z)
        self._execute(plan, image_size, plan_id)
        return plan_id

    # -- validation -------------------------------------------------------------------------------------
    def _begin(self, plan, image_size, mode="full", drop_z=None) -> str:
        with self._lock:
            if self.running:
                raise PlanBusy
            if mode not in MODES:
                raise PlanError(422, "invalid", f"mode must be one of {', '.join(MODES)}")
            if drop_z is not None and not DROP_Z_RANGE[0] <= drop_z <= DROP_Z_RANGE[1]:
                raise PlanError(422, "invalid", f"drop_z must be between {DROP_Z_RANGE[0]} and {DROP_Z_RANGE[1]} m")
            self._mode, self._drop_z = mode, self.cfg.drop_z if drop_z is None else drop_z
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
        if self._mode != "grasp" and not self.calibration.fitted:  # grasping never goes to a cell
            raise PlanError(409, "no_calibration", "no calibration fitted: add >= 4 points and fit first")
        if self._mode != "place":  # releasing needs neither a policy nor a taught box
            missing = self.poses.missing(sorted({c["color"] for c in plan if not self._acts(c["color"])}))
            if missing:
                raise PlanError(409, "missing_pose", f"missing taught poses: {', '.join(missing)}")
        if self._mode == "grasp":
            return
        seed = self.poses.get("home") or self.robot.read_joints()
        unreachable = []
        for c in plan:
            try:
                self.kin.solve(*self.calibration.pixel_to_robot(c["u"], c["v"], image_size), self._drop_z,
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
        self._emit("plan_started", message=f"{len(plan)} cells", total=len(plan), mode=self._mode)
        try:
            for c in plan:
                self._current = c["cell_index"]
                self._emit("cell_started", c["cell_index"], row=c["row"], col=c["col"], color=c["color"],
                           total=len(plan))
                empty = not self._plant(c, image_size)
                self._done.append(c["cell_index"])  # the arm always releases over the cell, seed or not
                if empty:
                    self._emit("cell_done", c["cell_index"], "grasp looked empty; released over the cell anyway",
                               empty=True)
                else:
                    self._emit("cell_done", c["cell_index"])
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

    def _release(self, c, image_size, back: dict[str, float]) -> None:
        """Hover over the cell, descend with the gripper as it is (closed-loop on the real tool position), open,
        lift back to the hover pose, then `back`. Without a reachable hover pose it drops straight from where it is."""
        cfg = self.cfg
        x, y = self.calibration.pixel_to_robot(c["u"], c["v"], image_size)
        aim, corrections = [x, y], 0
        hover_z = self._drop_z + cfg.approach_clearance
        hovering = self._move_hover(aim, hover_z)  # coming from above keeps the path from dipping into the tray
        while True:
            now = self.robot.read_joints()
            target = self.kin.solve(*aim, self._drop_z, seed={j: now[j] for j in ARM_JOINTS})
            self._move({**target, "gripper": now["gripper"]})
            if self._stop.wait(cfg.settle_s):
                raise Stopped
            reached = self.kin.tool_xyz(self.robot.read_joints())
            miss = (x - reached[0], y - reached[1])
            if math.hypot(*miss) <= cfg.place_tolerance_m or corrections >= cfg.place_corrections:
                break
            aim = [aim[0] + miss[0], aim[1] + miss[1]]  # aim past the cell by what the arm fell short
            corrections += 1
        self._emit("drop_pose", self._current, target=[x, y, self._drop_z], reached=list(reached),
                   error_mm=round(math.hypot(*miss) * 1000, 1), corrections=corrections)
        self._move({"gripper": cfg.gripper_open})
        if hovering:
            self._move_hover(aim, hover_z)
        self._move(back)

    def _move_hover(self, aim, hover_z) -> bool:
        """Moves the tool to (aim, hover_z) keeping the gripper; False when the arm cannot reach it."""
        now = self.robot.read_joints()
        try:
            target = self.kin.solve(*aim, hover_z, seed={j: now[j] for j in ARM_JOINTS})
        except IKError:
            return False
        self._move({**target, "gripper": now["gripper"]})
        return True

    def _grasp_with_policy(self, c, start) -> None:
        self._move(start)
        if not self.act.run(c["color"], self.robot, self._stop, self.cfg.hz):
            raise Stopped  # otherwise the policy leaves the seed in the closed gripper

    def _grasp_taught(self, c) -> bool:
        """home -> above the box -> grasp (with retries) -> lift; returns whether the gripper looked loaded."""
        cfg, color = self.cfg, c["color"]
        home, box = self.poses.get("home"), self.poses.get(f"above_box_{color}")
        opened = {"gripper": cfg.gripper_open}
        self._move({**home, **opened})
        holding = False
        for attempt in range(cfg.retries + 1):
            self._move({**box, **opened})
            self.grasper.grasp(color, self._move, self.robot.read_joints)
            holding = self._holding()
            if holding:
                break
            if attempt < cfg.retries:
                self.retries.append(c["cell_index"])
        self._move({**box, "gripper": self.robot.read_joints()["gripper"]})  # lift with the seed
        return holding

    def _plant(self, c, image_size) -> bool:
        """Runs the plan's mode for one cell; returns whether the gripper looked loaded (true when not judged)."""
        act_start = self.poses.get("act_start") or ACT_START_FALLBACK
        if self._mode == "place":  # half-test: no grasp, release with the gripper as it is, return to the grasp start
            self._release(c, image_size, act_start)
            return True
        if self._acts(c["color"]):
            self._grasp_with_policy(c, act_start)
            holding, back = True, act_start
        else:
            holding, back = self._grasp_taught(c), {**self.poses.get("home"), "gripper": self.cfg.gripper_open}
        if self._mode == "full":
            self._release(c, image_size, back)
        return holding
