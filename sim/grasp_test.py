"""Scripted IK grasp of one seed by contact physics only (no weld, no attach): open, descend, close, lift, hold.

    backend/.venv/bin/python sim/grasp_test.py                 # 20 jittered trials per colour, prints success rates
    backend/.venv/bin/python sim/grasp_test.py --trials 5 --video-dir sim/out

A trial succeeds when, after the lift and a 2 s hold, the seed is more than `LIFT_MIN` above where it started and
is still between the jaws (its distance to the tool frame did not grow by more than `SLIP_MAX`). The seed rides on
friction alone: the jaws, the seed, the table and the arm are plain MuJoCo contact geoms, see `sim/layout.py` for the
contact parameters and `sim/README.md` for the reasoning.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import layout  # noqa: E402
from smartseed_robot.kinematics import Kinematics  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

HZ = 30.0
LIFT_M = 0.05  # how far the arm lifts the seed
LIFT_MIN = 0.03  # success: the seed rose at least this much ...
SLIP_MAX = 0.008  # ... and moved at most this far relative to the tool frame
HOLD_S = 2.0
OPEN_G = 16.0  # gripper opening before the grasp (the recorded grasps open to ~30)
CLOSE_G = 4.5  # commanded close, below the empty stop (the recorded action goes to ~4.8 while the state stays ~7)
APPROACH_Z = 0.07  # tool height of the pre-grasp pose, clears the box walls (top at +0.027)
TOOL_Z_OFFSET = -0.0003  # MEASURED: the recorded grasp closes with the tool frame this far below the seed centre
FACE_GAP = 0.0035  # the open fixed-jaw face starts this far from the seed surface (> the 3 mm perception error)
CAMERA = "top"  # camera filmed when a trial records frames
FOOT_NEAR, FOOT_FAR, FOOT_SIDE = 0.018, 0.040, 0.016  # open-jaw footprint around the seed along / across the jaw axis
SEED_CLEAR = 0.010  # a neighbouring seed (radius plus slack) must stay out of the footprint
WALL_MARGIN = 0.004  # required clearance of that footprint to the box walls
SETTLE_MM = 0.8  # a Cartesian move ends when the tool is this close to its goal
SPEED = 0.08  # m/s of the Cartesian moves (mean; the smoothstep peaks at 1.5x)


@dataclass
class Trial:
    color: str
    jitter: tuple[float, float]
    success: bool = False
    lift_mm: float = 0.0
    slip_mm: float = 0.0
    gripper: float = 0.0  # reading while holding, after the lift
    frames: list = field(default_factory=list, repr=False)


def seed_joint(robot: SimRobot, color: str, index: int = 2):
    j = robot._model.joint(f"seed_{color}_{index}_free")
    return j.qposadr[0], j.dofadr[0]


def seed_xyz(robot: SimRobot, color: str, index: int = 2) -> np.ndarray:
    adr, _ = seed_joint(robot, color, index)
    return robot._data.qpos[adr:adr + 3].copy()


def tool_xyz(robot: SimRobot) -> np.ndarray:
    return robot._data.site_xpos[robot._model.site("gripperframe").id].copy()


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _clearance(seed: np.ndarray, phi: float, box: layout.OpenBox, others=(), box_yaw: float = 0.0) -> float:
    """Smallest distance from the open jaws' footprint (a rectangle along the jaw axis `phi`) to the inner box walls
    and to the other seeds (negative: the footprint overlaps one). `box_yaw` turns the box about its centre."""
    bx, by = layout.to_board(seed[:2])
    c, s = math.cos(phi - layout.BOARD_YAW), math.sin(phi - layout.BOARD_YAW)  # jaw axis in the board frame
    margin = np.inf
    for along, across in ((-FOOT_NEAR, -FOOT_SIDE), (-FOOT_NEAR, FOOT_SIDE), (FOOT_FAR, -FOOT_SIDE), (FOOT_FAR, FOOT_SIDE)):
        x, y = bx + c * along - s * across, by + s * along + c * across
        dx, dy = x - box.center[0], y - box.center[1]
        cy, sy = math.cos(box_yaw), math.sin(box_yaw)
        dx, dy = cy * dx + sy * dy, -sy * dx + cy * dy  # into the box frame
        margin = min(margin, box.inner_half[0] - abs(dx), box.inner_half[1] - abs(dy))
    for other in others:
        ox, oy = layout.to_board(other[:2])
        a, b = c * (ox - bx) + s * (oy - by), -s * (ox - bx) + c * (oy - by)  # the other seed in the jaw frame
        da, db = max(-FOOT_NEAR - a, a - FOOT_FAR), abs(b) - FOOT_SIDE  # signed distances to the two rectangle sides
        outside = math.hypot(max(da, 0.0), max(db, 0.0)) if max(da, db) > 0 else max(da, db)
        margin = min(margin, outside - SEED_CLEAR)
    return margin


def grasp_pose(seed: np.ndarray, radius: float, box: layout.OpenBox, others=(), box_yaw: float = 0.0
               ) -> tuple[np.ndarray, float]:
    """Tool target and wrist spin (deg) for a seed. The jaws open along the radial line from the shoulder (spin 0) or,
    when the open jaws would hit a box wall, along the nearest axis of the board that clears it (the recorded grasp of
    episode 0 does the same, with its wrist rolled 20 degrees), the moving jaw on the far side. The tool frame sits on
    the fixed-jaw face, so the seed is one radius (plus `FACE_GAP`) beyond the tool along the jaw axis. A box turned
    by `box_yaw` (radians, board frame) has its own axes as candidates."""
    radial = math.atan2(seed[1], seed[0] - layout.BASE_PAN_AXIS[0])
    candidates = [radial] + [layout.BOARD_YAW + box_yaw + math.radians(15 * k) for k in range(24)]
    scored = []
    for phi in candidates:
        u = np.array([math.cos(phi), math.sin(phi)])
        tool_xy = np.asarray(seed[:2]) - u * (radius + FACE_GAP)
        radial_tool = math.degrees(math.atan2(tool_xy[1], tool_xy[0] - layout.BASE_PAN_AXIS[0]))
        spin = _wrap_deg(radial_tool - math.degrees(phi))  # the jaw axis follows the radial one minus the spin
        scored.append((_clearance(seed, phi, box, others, box_yaw), spin, tool_xy))
    free = [c for c in scored if c[0] > WALL_MARGIN]
    margin, spin, tool_xy = min(free, key=lambda c: abs(c[1])) if free else max(scored, key=lambda c: c[0])
    return np.array([*tool_xy, seed[2] + TOOL_Z_OFFSET]), spin


TRACE = None  # optional callable(robot) run after every control step (debugging)


def _hold(robot: SimRobot, target: dict, steps: int, frames=None) -> None:
    for _ in range(steps):
        robot.send_joints(target)
        if TRACE is not None:
            TRACE(robot)
        if frames is not None:
            frames.append(robot.render(CAMERA))


def _close(robot: SimRobot, target: dict, frames=None, max_s: float = 3.0) -> None:
    """Hold the close command until the gripper reading stops changing (the jaw stalled on the seed or the stop)."""
    last, still = robot.read_joints()["gripper"], 0
    for _ in range(int(max_s * HZ)):
        _hold(robot, target, 1, frames)
        now = robot.read_joints()["gripper"]
        still = still + 1 if abs(now - last) < 0.01 else 0
        last = now
        if still >= 6:
            break
    _hold(robot, target, 6, frames)  # let the squeeze settle


def _move(robot: SimRobot, kin: Kinematics, goal_xyz, seed: dict, gripper: float, spin: float = 0.0,
          frames=None) -> dict:
    """Straight Cartesian move of the tool to `goal_xyz` with IK per waypoint; returns the last joint solution."""
    start = np.array(kin.tool_xyz(robot.read_joints()))
    goal = np.asarray(goal_xyz, dtype=float)
    n = max(1, int(np.ceil(np.linalg.norm(goal - start) / SPEED * HZ)))
    sol = seed
    for k in range(1, n + 1):
        u = k / n
        p = start + (goal - start) * (u * u * (3 - 2 * u))  # smoothstep: no jerk at either end
        sol = kin.solve(*p, seed=sol, spin_deg=spin)
        sol = {**sol, "gripper": gripper}
        robot.send_joints(sol)
        if TRACE is not None:
            TRACE(robot)
        if frames is not None:
            frames.append(robot.render(CAMERA))
    for _ in range(int(2 * HZ)):  # let the servos arrive: the arm lags the waypoints, most of all after a wrist roll
        if np.linalg.norm(tool_xyz(robot) - goal) < SETTLE_MM / 1000:
            break
        _hold(robot, sol, 1, frames)
    _hold(robot, sol, 3, frames)
    return sol


def run_trial(robot: SimRobot, kin: Kinematics, color: str, jitter=(0.0, 0.0), index: int = 2,
              record: bool = False) -> Trial:
    """One grasp on `seed_<color>_<index>` shifted by `jitter` (x, y metres). The robot is used as is."""
    trial = Trial(color, tuple(jitter))
    frames = trial.frames if record else None
    adr, dof = seed_joint(robot, color, index)
    nominal = seed_xyz(robot, color, index)  # where the planner believes the seed is
    robot._data.qpos[adr:adr + 2] += np.asarray(jitter)  # where it actually is: a perception error of up to 3 mm
    robot._data.qvel[dof:dof + 6] = 0
    _hold(robot, {}, 10, frames)  # the seed settles on the floor
    seed0 = seed_xyz(robot, color, index)
    box = layout.WHITE_BOX if color == "white" else layout.BLACK_BOX
    others = [p for k, p in enumerate(layout.seed_positions(color)) if k != index]
    grasp, spin = grasp_pose(nominal, layout.SEED_RADIUS[color], box, others)
    above = grasp + np.array([0.0, 0.0, APPROACH_Z])
    home = robot.read_joints()
    start_xyz = np.array(kin.tool_xyz(home))

    sol = _move(robot, kin, [start_xyz[0], start_xyz[1], APPROACH_Z], home, OPEN_G, spin, frames)
    sol = _move(robot, kin, above, sol, OPEN_G, spin, frames)
    sol = _move(robot, kin, grasp, sol, OPEN_G, spin, frames)
    _hold(robot, sol, 15, frames)
    _close(robot, {**sol, "gripper": CLOSE_G}, frames)
    held_at = seed_xyz(robot, color, index) - tool_xyz(robot)  # seed position in the (translating) tool frame
    sol = _move(robot, kin, grasp + np.array([0.0, 0.0, LIFT_M]), sol, CLOSE_G, spin, frames)
    _hold(robot, {**sol, "gripper": CLOSE_G}, int(HOLD_S * HZ), frames)

    seed1 = seed_xyz(robot, color, index)
    trial.lift_mm = float(seed1[2] - seed0[2]) * 1000
    trial.slip_mm = float(np.linalg.norm(seed1 - tool_xyz(robot) - held_at)) * 1000
    trial.gripper = robot.read_joints()["gripper"]
    trial.success = trial.lift_mm > LIFT_MIN * 1000 and trial.slip_mm < SLIP_MAX * 1000
    return trial


def save_media(trial: Trial, out_dir: Path) -> None:
    """mp4 of the whole trial plus a PNG strip of six moments (approach, descent, closed, lifted, held)."""
    import imageio.v2 as imageio

    out_dir.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(str(out_dir / f"grasp_{trial.color}.mp4"), fps=HZ, codec="libx264", macro_block_size=1) as w:
        for f in trial.frames:
            w.append_data(f)
    n = len(trial.frames)
    picks = [int(n * q) for q in (0.30, 0.45, 0.55, 0.65, 0.80, 0.99)]
    strip = np.hstack([trial.frames[i][::2, ::2] for i in picks])  # half resolution
    imageio.imwrite(str(out_dir / f"grasp_{trial.color}_strip.png"), strip)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--jitter", type=float, default=0.003, help="seed placement error in x and y, metres")
    ap.add_argument("--index", type=int, default=2, help="which seed of the box to grasp (0-3)")
    ap.add_argument("--video-dir", default=None, help="write grasp_<colour>.mp4 and a PNG strip of the first success")
    ap.add_argument("--colors", nargs="*", default=["black", "white"])
    args = ap.parse_args()
    kin = Kinematics()
    rng = np.random.default_rng(0)
    for color in args.colors:
        results, saved = [], False
        for i in range(args.trials):
            robot = SimRobot()
            record = bool(args.video_dir) and not saved
            t = run_trial(robot, kin, color, rng.uniform(-args.jitter, args.jitter, 2), index=args.index, record=record)
            robot.close()
            results.append(t)
            if record and t.success:
                save_media(t, Path(args.video_dir))
                saved = True
            t.frames = []
            print(f"{color} {i:2d} jitter {t.jitter[0]*1000:+.1f},{t.jitter[1]*1000:+.1f} mm lift {t.lift_mm:6.1f} mm "
                  f"slip {t.slip_mm:5.1f} mm grip {t.gripper:5.2f} {'OK' if t.success else 'FAIL'}")
        ok = [t for t in results if t.success]
        print(f"{color} seed {args.index}: {len(ok)}/{len(results)} succeeded; holding reading "
              f"{np.mean([t.gripper for t in ok]) if ok else float('nan'):.2f}, lift "
              f"{np.mean([t.lift_mm for t in ok]) if ok else float('nan'):.1f} mm")


if __name__ == "__main__":
    main()
