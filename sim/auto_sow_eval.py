"""A3c: the backend's auto mode end to end in the twin (`SMARTSEED_ROBOT=sim`, in process, no HTTP server).

For N held-out narrow scenes per colour (`eval.heldout_scenes`, seed 1000) a `SimRobot` is built with the scene applied
and driven by the real `Executor` in plan mode `auto`, with the config the sim backend ships (`sim/config`: the
tray-height place calibration, the seed-height grasp calibration, the taught poses) and the real seed detector. Cells:
the first `--cells` of the scene's tray, their pixels taken from the scene's own top camera (the shifted and tilted one)
at the tray-top height, so the place calibration carries the same camera error a real one would. The seed detector reads
the rendered top frame; the grasp calibration is the nominal camera (`--no-camera-noise` renders it too, which
isolates everything but the camera error).

After the plan the true seed positions decide what happened: in a tray cell (sown), still in its box, on the tray rim or a
divider (missed the cell) or elsewhere (out of the box onto the table).
The executor's events give the attempts and why the run stopped. The controller clock is not real time: the executor's
stop event is swapped for one whose `wait` returns at once, simulated time still advances 1/30 s per command.

    backend/.venv/bin/python sim/auto_sow_eval.py --episodes 20                 # both colours, narrow, seed 1000
    backend/.venv/bin/python sim/auto_sow_eval.py --episodes 1 --colors black --video-dir sim/out
"""
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import eval as sim_eval, layout, make_dataset as md  # noqa: E402
from smartseed_robot.calibration import Calibration  # noqa: E402
from smartseed_robot.executor import Executor, ExecutorConfig, PlanError  # noqa: E402
from smartseed_robot.kinematics import Kinematics  # noqa: E402
from smartseed_robot.poses import PoseStore  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

CONFIG = ROOT / "sim" / "config"
IMAGE_SIZE = (640, 480)
CELL_RADIUS_M = 0.02  # a seed this close (xy) to a cell centre, below the tray rim, lies in that cell
IN_CELL_Z = layout.TRAY_TOP_Z - 0.008


class FastEvent(threading.Event):
    """The executor's stop flag with a clock that does not wait: its 30 Hz sleeps return at once."""

    def wait(self, timeout=None):
        return self.is_set()


def scene_projector(robot: SimRobot):
    """World point -> top-camera pixel with the camera as the scene has it (shifted and tilted), not the nominal one."""
    m, d = robot._model, robot._data
    cid = m.camera("top").id
    pos, rot = d.cam_xpos[cid].copy(), d.cam_xmat[cid].reshape(3, 3).copy()  # columns: right, up, backwards
    f = 0.5 * IMAGE_SIZE[1] / math.tan(math.radians(m.cam_fovy[cid]) / 2)

    def project(point) -> tuple[float, float]:
        p = rot.T @ (np.asarray(point, dtype=float) - pos)
        return IMAGE_SIZE[0] / 2 + f * p[0] / -p[2], IMAGE_SIZE[1] / 2 - f * p[1] / -p[2]

    return project


def tray_cells(p: md.EpisodeParams) -> list[tuple[int, int, np.ndarray]]:
    """(row, col, base-frame xy) of every cell of the scene's tray, row-major."""
    px, py = layout._pitch()
    c, s = math.cos(math.radians(p.tray.yaw_deg)), math.sin(math.radians(p.tray.yaw_deg))
    cells = []
    for row in range(layout.TRAY_ROWS):
        for col in range(layout.TRAY_COLS):
            dx, dy = (layout.TRAY_ROWS / 2 - 0.5 - row) * px, (layout.TRAY_COLS / 2 - 0.5 - col) * py
            board = (p.tray.center[0] + c * dx - s * dy, p.tray.center[1] + s * dx + c * dy)
            cells.append((row, col, np.array(layout.to_world(board))))
    return cells


def seed_positions(robot: SimRobot, color: str) -> list[np.ndarray]:
    out = []
    for i in range(layout.SEEDS_PER_BOX):
        adr = robot._model.joint(f"seed_{color}_{i}_free").qposadr[0]
        out.append(robot._data.qpos[adr:adr + 3].copy())
    return out


def in_box(p: md.EpisodeParams, color: str, xyz) -> bool:
    state, box = (p.white if color == "white" else p.black), md.box_of(color)
    bx, by = layout.to_board(xyz[:2])
    c, s = math.cos(math.radians(state.yaw_deg)), math.sin(math.radians(state.yaw_deg))
    dx, dy = bx - state.center[0], by - state.center[1]
    lx, ly = c * dx + s * dy, -s * dx + c * dy
    return abs(lx) < box.inner_half[0] and abs(ly) < box.inner_half[1] and xyz[2] < box.top_z


def on_tray(p: md.EpisodeParams, xyz) -> bool:
    bx, by = layout.to_board(xyz[:2])
    c, s = math.cos(math.radians(p.tray.yaw_deg)), math.sin(math.radians(p.tray.yaw_deg))
    dx, dy = bx - p.tray.center[0], by - p.tray.center[1]
    lx, ly = c * dx + s * dy, -s * dx + c * dy
    return abs(lx) < layout.TRAY_OUTER_HALF[0] and abs(ly) < layout.TRAY_OUTER_HALF[1]


def where(p: md.EpisodeParams, color: str, xyz, cells) -> str:
    """`cell`, `box`, `tray` (on the rim or a divider: it missed the cell) or `elsewhere` for a seed's final position."""
    if xyz[2] < IN_CELL_Z and any(np.hypot(*(xyz[:2] - c)) < CELL_RADIUS_M for _, _, c in cells):
        return "cell"
    if in_box(p, color, xyz):
        return "box"
    return "tray" if on_tray(p, xyz) else "elsewhere"


def make_plan(robot: SimRobot, p: md.EpisodeParams, n_cells: int) -> list[dict]:
    project = scene_projector(robot)
    plan = []
    for k, (row, col, xy) in enumerate(tray_cells(p)[:n_cells]):
        u, v = project((*xy, layout.TRAY_TOP_Z))
        plan.append({"cell_index": k, "row": row, "col": col, "color": p.color, "u": u, "v": v})
    return plan


def make_executor(robot: SimRobot, kin: Kinematics) -> Executor:
    ex = Executor(robot, PoseStore(CONFIG / "poses.json"), Calibration.load(CONFIG / "calibration.json"), kin,
                  config=ExecutorConfig(), mode="sim", grasp_calibration=Calibration.load(CONFIG / "grasp_calibration.json"))
    ex._stop = FastEvent()
    return ex


def run_scene(p: md.EpisodeParams, kin: Kinematics, *, n_cells: int = 6, camera_noise: bool = True,
              video: Path | None = None) -> dict:
    import dataclasses

    if not camera_noise:
        p = dataclasses.replace(p, top_cam_shift=(0.0, 0.0, 0.0), top_cam_rot_deg=(0.0, 0.0, 0.0))
    robot = SimRobot(initial=PoseStore(CONFIG / "poses.json").get("home"))
    t0 = time.time()
    try:
        md.apply_scene(robot, p)
        for _ in range(15):  # the seeds settle
            robot.send_joints({})
        ex, plan, refused = make_executor(robot, kin), make_plan(robot, p, n_cells), None
        if video:
            robot.start_recording(video)
        while True:  # a cell the arm cannot reach is dropped, as a user would not target it
            try:
                ex.run(plan, IMAGE_SIZE, mode="auto")
                break
            except PlanError as exc:
                if exc.code != "unreachable":
                    refused = exc.code
                    break
                bad = {int(i) for i in exc.detail.split("[")[1].split("]")[0].split(",")}
                plan = [c for c in plan if c["cell_index"] not in bad]
                if not plan:
                    refused = "unreachable"
                    break
        robot.stop_recording()
        cells = tray_cells(p)
        positions = seed_positions(robot, p.color)
        final = Counter(where(p, p.color, positions[i], cells) for i in p.present)  # absent seeds are parked away
        return {"color": p.color, "attempt": p.attempt, "present": len(p.box.seeds), "sown": final["cell"],
                "in_box": final["box"], "tray": final["tray"], "elsewhere": final["elsewhere"], "plan_cells": len(plan), "refused": refused,
                "state": ex.status()["state"], "seconds": time.time() - t0, **summarise_events(ex.events)}
    finally:
        robot.close()


def summarise_events(events: list[dict]) -> dict:
    attempts = [e for e in events if e["type"] == "grasp_attempt"]
    stops = [e["reason"] for e in events if e["type"] == "auto_stopped"]
    return {"attempts": len(attempts), "held": sum(e["result"] == "held" for e in attempts),
            "empty": sum(e["result"] == "empty" for e in attempts), "dropped": sum(e["result"] == "dropped" for e in attempts),
            "unreachable": sum(e["result"] == "unreachable" for e in attempts),
            "stops": stops, "error": next((e["message"] for e in events if e["type"] == "error"), None)}


def failure_causes(r: dict) -> Counter:
    """Why the seeds of a scene that are not in a cell are not: by what the run did about them."""
    causes = Counter()
    if r["refused"]:
        causes[f"plan refused ({r['refused']})"] += r["present"] - r["sown"]
        return causes
    if r["error"]:
        causes["executor error"] += r["present"] - r["sown"]
        return causes
    causes["on the tray rim or a divider (missed the cell)"] += r["tray"]
    causes["out of the box onto the table (pushed or dropped)"] += r["elsewhere"]
    if r["in_box"]:
        causes["still in the box: " + ("not detected (against a wall or in a corner)" if "no_seeds" in r["stops"] and "gave_up" not in r["stops"]
                                       else "given up after failed grasps")] += r["in_box"]
    return +causes


def evaluate(color: str, n: int, *, n_cells: int, camera_noise: bool, video_dir: Path | None, kin: Kinematics,
             log=print) -> list[dict]:
    results = []
    for k, p in enumerate(sim_eval.heldout_scenes(color, n, kin=kin, layout_mode="narrow")):
        video = (video_dir / f"auto_sow_{color}.mp4") if video_dir and k == 0 else None
        r = run_scene(p, kin, n_cells=n_cells, camera_noise=camera_noise, video=video)
        results.append(r)
        log(f"{color} scene {k:2d}: sown {r['sown']}/{r['present']} (box {r['in_box']}, tray {r['tray']}, elsewhere {r['elsewhere']}) "
            f"attempts {r['attempts']} held {r['held']} empty {r['empty']} dropped {r['dropped']} "
            f"unreachable {r['unreachable']} stops {r['stops']} {r['seconds']:.0f}s" + (f" ERROR {r['error']}" if r["error"] else ""))
    return results


def summary_row(color: str, results: list[dict], label: str) -> str:
    present, sown = sum(r["present"] for r in results), sum(r["sown"] for r in results)
    full = sum(r["sown"] == r["present"] for r in results)
    attempts = sum(r["attempts"] for r in results)
    return (f"| {color} | {label} | {len(results)} | {present} | {sown} ({100 * sown / max(present, 1):.0f} %) | {full} | "
            f"{attempts} | {sum(r['held'] for r in results)} | {sum(r['empty'] for r in results)} | "
            f"{sum(r['dropped'] for r in results)} | {sum(r['unreachable'] for r in results)} |")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", type=int, default=20, help="held-out narrow scenes per colour")
    ap.add_argument("--colors", nargs="+", default=["black", "white"])
    ap.add_argument("--cells", type=int, default=6, help="target cells of the tray per scene (more than seeds present)")
    ap.add_argument("--no-camera-noise", action="store_true", help="render the nominal camera (calibrations exact)")
    ap.add_argument("--video-dir", type=Path, default=None, help="film the first scene of each colour: auto_sow_<colour>.mp4")
    args = ap.parse_args(argv)
    kin = Kinematics()
    label = "nominal camera" if args.no_camera_noise else "camera noise"
    rows, causes = [], {}
    for color in args.colors:
        results = evaluate(color, args.episodes, n_cells=args.cells, camera_noise=not args.no_camera_noise,
                           video_dir=args.video_dir, kin=kin)
        rows.append(summary_row(color, results, label))
        causes[color] = sum((failure_causes(r) for r in results), Counter())
    print("\n| colour | case | scenes | seeds | sown | scenes emptied | attempts | held | empty | dropped | unreachable |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    for color, c in causes.items():
        print(f"{color} seeds not in a cell: " + ("; ".join(f"{n} {why}" for why, n in c.items()) or "none"))


if __name__ == "__main__":
    main()
