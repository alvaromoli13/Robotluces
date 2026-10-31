from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

import cv2
import numpy as np

from . import scripted_grasp
from .act import ACT_START_FALLBACK, ActGrasp
from .calibration import Calibration, CalibrationError
from .kinematics import IKError, Kinematics
from .motion import MotionConfig, move_to
from .poses import COLOR_ID, PoseStore
from .robot import ARM_JOINTS, CameraUnavailable, RobotPort
from .seed_detector import detect_seeds, seeds_to_robot


class PlanError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class PlanBusy(PlanError):
    def __init__(self):
        super().__init__(409, "busy", "a plan is already running")


# full = grasp + place; grasp / place are the two halves, for debugging; auto = find the seeds with the top camera,
# grasp each with a scripted IK pick and place it in the next cell (cells: the targets, their colour picks the seeds)
MODES = ("full", "grasp", "place", "auto")
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
    release_wrist_tilt_deg: float = 5.0  # wrist_flex added over the cell just before opening (+ = tip further down)
    # auto mode (scripted grasp from the seed detector); the geometry is `scripted_grasp`
    held_above: float = 6.5  # gripper reading above this after closing = a seed in the jaws (real follower: empty 6.1, black 6.9, white 7.4)
    auto_attempts: int = 3  # grasp attempts per seed (a cell gets twice that, a pushed seed counts as a new one)
    scripted_open: float = 16.0  # gripper opening before the scripted grasp (the sim planner's)
    approach_height: float = 0.07  # m above the seed where the scripted grasp hovers before descending
    cartesian_speed: float = 0.08  # m/s mean of the straight descents and lifts (one IK waypoint per control period)
    settle_mm: float = 1.0  # a straight move ends when the tool is this close to its goal
    seed_z: float = 0.007  # m, tool height at the seed centres when the grasp calibration points carry no z
    seed_radius: dict[str, float] = field(default_factory=lambda: {"black": 0.0068, "white": 0.0074})


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
                 act: ActGrasp | None = None, grasp_calibration: Calibration | None = None,
                 seed_finder: Callable[[np.ndarray, str], list[tuple[float, float]]] = detect_seeds):
        self.robot, self.poses, self.calibration, self.kin = robot, poses, calibration, kin
        self.grasp_calibration = grasp_calibration or Calibration()
        self.seed_finder = seed_finder
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
        self._tray_px: tuple[list[tuple[float, float]], tuple[int, int]] = ([], (1, 1))
        self._exhausted: set[str] = set()  # auto mode: colours with no seed left to try
        self._tries: list[tuple[tuple[float, float], int]] = []  # auto mode: grasp attempts per seed position

    @property
    def running(self) -> bool:
        return self._state in ("running", "stopping")

    def status(self) -> dict:
        return {"state": self._state, "robot": self.mode, "plan_id": self._plan_id, "current_cell": self._current,
                "done": list(self._done), "failed": list(self._failed), "calibrated": self.calibration.fitted,
                "grasp_calibrated": self.grasp_calibration.fitted,
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
            self._exhausted, self._tries = set(), []
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
        if self._mode == "auto":  # seeds are found, not taught: needs the seed-height calibration and a pose to look from
            if not self.grasp_calibration.fitted:
                raise PlanError(409, "no_grasp_calibration",
                                "no grasp calibration fitted: calibrate at seed height (kind=grasp), >= 4 points, and fit")
            if self.poses.get("home") is None:
                raise PlanError(409, "missing_pose", "missing taught poses: home")
        elif self._mode != "place":  # releasing needs neither a policy nor a taught box
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
        self._robot_hook("begin_plan", plan_id)  # optional: the sim robot films each plan
        try:
            self._run_plan(plan, image_size, plan_id)
        finally:
            self._robot_hook("end_plan")

    def _robot_hook(self, name: str, *args) -> None:
        hook = getattr(self.robot, name, None)
        if hook is not None:
            hook(*args)

    def _run_plan(self, plan, image_size, plan_id) -> None:
        self.plan_start_index = len(self.events)
        self._tray_px = ([(c["u"], c["v"]) for c in plan], tuple(image_size))  # auto mode: where the tray is
        self._emit("plan_started", message=f"{len(plan)} cells", total=len(plan), mode=self._mode)
        try:
            for c in plan:
                if self._mode == "auto" and c["color"] in self._exhausted:
                    continue
                self._current = c["cell_index"]
                self._emit("cell_started", c["cell_index"], row=c["row"], col=c["col"], color=c["color"],
                           total=len(plan))
                if self._mode == "auto":
                    self._sow_auto(c, image_size)
                    continue
                empty = not self._plant(c, image_size)
                self._done.append(c["cell_index"])  # the arm always releases over the cell, seed or not
                if empty:
                    self._emit("cell_done", c["cell_index"], "grasp looked empty; released over the cell anyway",
                               empty=True)
                else:
                    self._emit("cell_done", c["cell_index"])
            self._current = None
            self._go_home(plan)
            self._emit("finished", message=f"{len(self._done)} done, {len(self._failed)} failed")
            self._state = "idle"
        except Stopped:
            self._current = None
            self._emit("stopped", message="stopped by user; the arm holds its position")
            self._state = "idle"
        except CameraUnavailable as exc:
            self._emit("error", self._current, f"{type(exc).__name__}: {exc}", code="camera_unavailable")
            self._state = "error"
        except Exception as exc:  # the arm holds position: never cut torque mid-air on our own
            self._emit("error", self._current, f"{type(exc).__name__}: {exc}")
            self._state = "error"

    def _go_home(self, plan) -> None:
        """A full plan with ACT cells ends at the taught home (gripper open), not at the grasp start pose."""
        home = self.poses.get("home")
        if home and self._mode == "full" and any(self._acts(c["color"]) for c in plan):
            self._move({**home, "gripper": self.cfg.gripper_open})

    def _acts(self, color: str) -> bool:
        return self.act is not None and self.act.has(color)

    def _holding(self) -> bool:
        if self._stop.wait(self.cfg.settle_s):
            raise Stopped
        return self.robot.read_joints()["gripper"] > self.cfg.held_above

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
        if cfg.release_wrist_tilt_deg:
            self._move({"wrist_flex": self.robot.read_joints()["wrist_flex"] + cfg.release_wrist_tilt_deg})
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

    # -- auto mode: detect -> scripted grasp -> place ---------------------------------------------------------
    SEED_MATCH_M = 0.012  # a detection this close to an earlier grasp attempt is the same seed

    def _sow_auto(self, c, image_size) -> None:
        """Fills the cell `c` with a seed of its colour: look, pick the nearest reachable seed, grasp it, release it
        over the cell; a failed grasp looks again. Ends the colour when no seed is left to try."""
        color, cell_attempts = c["color"], 0
        while cell_attempts < 2 * self.cfg.auto_attempts:
            seeds = self._detect(color)
            self._emit("seeds_detected", c["cell_index"], count=len(seeds), color=color)
            if not seeds:
                return self._give_up(c, "no_seeds")
            tool = np.array(self.kin.tool_xyz(self.robot.read_joints())[:2])
            todo = [s for s in seeds if self._tried(s) < self.cfg.auto_attempts]
            if not todo:
                return self._give_up(c, "gave_up")
            target = min(todo, key=lambda s: float(np.hypot(*(np.array(s) - tool))))
            attempt = self._bump(target)
            cell_attempts += 1
            others = [s for s in seeds if s is not target]
            cause = self._grasp_scripted(target, others, attempt, color)
            self._emit("grasp_attempt", c["cell_index"], x=target[0], y=target[1], attempt=attempt, result=cause or "held")
            if cause is None:
                self._release(c, image_size, {**self.poses.get("home"), "gripper": self.cfg.gripper_open})
                self._done.append(c["cell_index"])
                self._emit("cell_done", c["cell_index"])
                return
            self._emit("grasp_failed", c["cell_index"], cause=cause, x=target[0], y=target[1], attempt=attempt)
            if cause == "unreachable":
                self._tries.append((target, self.cfg.auto_attempts))  # no use trying that seed again
            else:
                self.retries.append(c["cell_index"])
        self._give_up(c, "gave_up")

    def _give_up(self, c, reason: str) -> None:
        """No seed of the cell's colour can be sown: the colour is finished for this plan."""
        if reason != "no_seeds":
            self._failed.append(c["cell_index"])
        self._exhausted.add(c["color"])
        self._emit("auto_stopped", c["cell_index"], f"{reason}: no more {c['color']} seeds to sow", color=c["color"],
                   reason=reason)

    def _tried(self, xy) -> int:
        return max((n for p, n in self._tries if np.hypot(xy[0] - p[0], xy[1] - p[1]) < self.SEED_MATCH_M), default=0)

    def _bump(self, xy) -> int:
        """Counts a grasp attempt on the seed at `xy`; returns its number, from 1."""
        n = self._tried(xy) + 1
        self._tries.append((tuple(xy), n))
        return n

    def _detect(self, color: str) -> list[tuple[float, float]]:
        """Back to the taught home (the arm out of the view), then the top frame -> base-frame (x, y) of each seed."""
        self._move({**self.poses.get("home"), "gripper": self.cfg.gripper_open})
        if self._stop.wait(self.cfg.settle_s):
            raise Stopped
        frame = self.robot.read_observation().get("observation.images.top")
        if frame is None:
            raise CameraUnavailable("the robot gives no top camera frame")
        size = (frame.shape[1], frame.shape[0])
        centres = [c for c in self.seed_finder(frame, color) if not self._on_tray(c, size)]
        return [(float(x), float(y)) for x, y in seeds_to_robot(self.grasp_calibration, centres, size)]

    def _on_tray(self, centre, frame_size) -> bool:
        """The tray is cardboard like the box floor, so the detector also sees seeds already sown. A detection is on
        the tray when it lies in the hull of the plan's cells or within 3/4 of the cell pitch (the median distance to
        the nearest other cell, 40 px for a single cell) of one of them."""
        cells, size = self._tray_px
        pts = (np.array(cells) * (frame_size[0] / size[0], frame_size[1] / size[1])).astype(np.float32)
        pitch = float(np.median([np.sort(np.hypot(*(pts - p).T))[1] for p in pts])) if len(pts) > 1 else 40.0
        if float(np.min(np.hypot(*(pts - np.array(centre, dtype=np.float32)).T))) < 0.75 * pitch:
            return True
        hull = cv2.convexHull(pts)
        return len(hull) >= 3 and cv2.pointPolygonTest(hull, (float(centre[0]), float(centre[1])), False) >= 0

    def _line(self, goal, spin: float, gripper: float) -> dict[str, float]:
        """Straight Cartesian move of the tool to `goal` (IK per waypoint at the wrist roll `spin`), then let the
        servos arrive; returns the last joint solution. Raises IKError."""
        cfg = self.cfg
        start, goal = np.array(self.kin.tool_xyz(self.robot.read_joints())), np.asarray(goal, dtype=float)
        n = max(1, math.ceil(float(np.linalg.norm(goal - start)) / (cfg.cartesian_speed / cfg.hz)))
        sol = {}
        for k in range(1, n + 1):
            u, now = k / n, self.robot.read_joints()  # smoothstep: no jerk at either end, so the jaws do not shove the seed
            sol = self.kin.solve(*(start + (goal - start) * u * u * (3 - 2 * u)), seed={j: now[j] for j in ARM_JOINTS},
                                 spin_deg=spin)
            self._move({**sol, "gripper": gripper})
        for _ in range(int(2 * cfg.hz)):  # the arm lags its goals, most of all after a wrist roll
            if np.linalg.norm(np.array(self.kin.tool_xyz(self.robot.read_joints())) - goal) < cfg.settle_mm / 1000:
                break
            self._move({**sol, "gripper": gripper})
        return sol

    def _grasp_z(self) -> float:
        z = self.grasp_calibration.mean_z
        return (self.cfg.seed_z if z is None else z) + scripted_grasp.TOOL_Z_OFFSET

    def _grasp_scripted(self, seed, others, attempt: int, color: str) -> str | None:
        """Hover over the seed, descend, close, lift to the release height; None when the gripper holds a seed after
        the lift, else the cause: `unreachable` (no jaw axis the arm reaches), `empty` (nothing in the jaws after
        closing), `dropped` (it let go during the lift). Each attempt starts from another jaw axis."""
        cfg, z = self.cfg, self._grasp_z()
        axes = scripted_grasp.jaw_axes(seed, others, cfg.seed_radius.get(color, 0.007))
        axes = axes[(attempt - 1) % len(axes):] + axes[:(attempt - 1) % len(axes)]
        opened, now = cfg.scripted_open, self.robot.read_joints()
        for spin, (x, y) in axes:
            try:
                hover = self.kin.solve(x, y, z + cfg.approach_height, seed={j: now[j] for j in ARM_JOINTS},
                                       spin_deg=spin)
                self._move({**hover, "gripper": opened})
                self._line((x, y, z), spin, opened)
            except IKError:
                continue
            if not self._close_on_seed():
                self._lift(x, y, spin)
                return "empty"
            held = self._lift(x, y, spin)
            return None if held else "dropped"
        return "unreachable"

    def _close_on_seed(self, max_s: float = 3.0, still_steps: int = 6) -> bool:
        """Keeps commanding the closed gripper until its reading stops changing (the jaws stalled on a seed or on the
        stop), then judges it: loaded when the reading is above `held_above`. Commanding, not sleeping, is what lets
        the sim's clock (and a servo's travel) advance."""
        cfg = self.cfg
        last, still = self.robot.read_joints()["gripper"], 0
        for _ in range(max(1, int(max_s * cfg.hz))):
            self._move({"gripper": cfg.gripper_closed})
            now = self.robot.read_joints()["gripper"]
            still = still + 1 if abs(now - last) < 0.05 else 0
            last = now
            if still >= still_steps:
                break
        return last > cfg.held_above

    def _lift(self, x: float, y: float, spin: float) -> bool:
        """Straight up to the height the release hovers at (the box walls and the tray clear); whether it still holds."""
        gripper = self.robot.read_joints()["gripper"]
        try:
            self._line((x, y, self._drop_z + self.cfg.approach_clearance), spin, gripper)
        except IKError:  # out of reach up there: just back to the hover height of the grasp
            self._line((x, y, self._grasp_z() + self.cfg.approach_height), spin, gripper)
        return self.robot.read_joints()["gripper"] > self.cfg.held_above
