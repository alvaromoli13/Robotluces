"""Seed detector precision (A1): how far `seed_detector` plus a pixel -> base calibration puts each seed from the truth.

For N held-out narrow scenes (`eval.heldout_scenes`, seed 1000) the top camera is rendered at the start of the
episode exactly as the policy sees it (`SimRobot.read_observation` after `apply_scene`, the frame `eval.run_scene`
feeds the policy), the detector runs on that frame, and the detections are matched to the true seeds of the colour
(`EpisodeParams.seed_xy`, base-frame metres, the frame the planner uses). The scene's own top-camera randomisation
(+-5 mm, +-1 deg) is the realistic calibration error: the calibration below is the NOMINAL camera and never sees it.
`--no-camera-noise` renders the nominal camera, which isolates the detector's own error.

Calibration: sim mode's `config/calibration.json` is at the tray-top height (`make_config`), 4.7 cm above the seed
centres, which biases a seed by up to a centimetre. So the measurement uses `seed_plane_calibration`: the same
`Calibration` homography form (pixel, tool xy pairs), built from the nominal sim camera with the points at the height
of the seed centres, exactly what the web calibration gives when the tool tip is dragged at that height. Both are
reported with `--tray-plane`.

    backend/.venv/bin/python sim/detect_eval.py --episodes 50                  # both colours, narrow, seed 1000
    backend/.venv/bin/python sim/detect_eval.py --episodes 50 --no-camera-noise
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import eval as sim_eval, layout, make_dataset as md  # noqa: E402
from sim.measure_layout import project  # noqa: E402
from smartseed_robot import seed_detector  # noqa: E402
from smartseed_robot.calibration import Calibration  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

OUT_DIR = ROOT / "sim" / "out" / "detect"
GATE_M = 0.02  # a detection farther than this from every free truth seed is a false detection (a seed is 14 mm across)
IMAGE_SIZE = (640, 480)
CALIBRATION_GRID = [(x, y) for x in (0.15, 0.25, 0.35, 0.45) for y in (-0.15, 0.0, 0.15)]  # base-frame xy over the mat


@dataclass(frozen=True)
class Match:
    errors_mm: np.ndarray  # one per matched seed
    misses: int  # true seeds nobody detected
    false: int  # detections near no true seed

    @property
    def matched(self) -> int:
        return len(self.errors_mm)


@dataclass(frozen=True)
class SceneResult:
    match: Match
    frame: np.ndarray
    detected_xy: np.ndarray
    truth_xy: np.ndarray


def match_positions(detected: np.ndarray, truth: np.ndarray, gate_m: float = GATE_M) -> Match:
    """One-to-one assignment of detections to truth, minimising the summed distance among pairs within `gate_m`."""
    from scipy.optimize import linear_sum_assignment

    detected, truth = np.asarray(detected, float).reshape(-1, 2), np.asarray(truth, float).reshape(-1, 2)
    errors = []
    if len(detected) and len(truth):
        dist = np.linalg.norm(detected[:, None] - truth[None], axis=2)
        rows, cols = linear_sum_assignment(np.where(dist <= gate_m, dist, 1e3))  # pairs past the gate are never worth it
        errors = [dist[r, c] * 1000 for r, c in zip(rows, cols) if dist[r, c] <= gate_m]
    return Match(np.array(errors), len(truth) - len(errors), len(detected) - len(errors))


def summarize(errors_mm: np.ndarray) -> dict:
    if len(errors_mm) == 0:
        return {"median": None, "p90": None, "max": None}
    return {"median": float(np.median(errors_mm)), "p90": float(np.percentile(errors_mm, 90)),
            "max": float(np.max(errors_mm))}


def seed_plane_calibration(color: str) -> Calibration:
    """Pixel -> base xy homography of the NOMINAL sim top camera at the height of the `color` seed centres."""
    z = md.box_of(color).floor_z + layout.SEED_RADIUS[color]
    cal = Calibration()
    for x, y in CALIBRATION_GRID:
        u, v = project((x, y, z))
        cal.add_point(u, v, x, y, IMAGE_SIZE)
    cal.fit()
    return cal


def tray_plane_calibration() -> Calibration:
    """The calibration sim mode ships (`sim/config/calibration.json`, tool at the tray-top height)."""
    return Calibration.load(layout.SIM_DIR / "config" / "calibration.json")


def truth_xy(p: md.EpisodeParams) -> np.ndarray:
    state = p.white if p.color == "white" else p.black
    return np.array([p.seed_xy(p.color, i) for i, _, _ in state.seeds], float).reshape(-1, 2)


def top_frame(p: md.EpisodeParams) -> np.ndarray:
    """The top camera at the start of the episode, as the policy gets it."""
    robot = SimRobot(initial=sim_eval.start_pose(p))
    try:
        md.apply_scene(robot, p)
        return robot.read_observation()["observation.images.top"]
    finally:
        robot.close()


def measure_scene(p: md.EpisodeParams, *, camera_noise: bool = True, calibration: Calibration | None = None) -> SceneResult:
    if not camera_noise:
        p = dataclasses.replace(p, top_cam_shift=(0.0, 0.0, 0.0), top_cam_rot_deg=(0.0, 0.0, 0.0))
    frame = top_frame(p)
    cal = calibration or seed_plane_calibration(p.color)
    detected = seed_detector.seeds_to_robot(cal, seed_detector.detect_seeds(frame, p.color))
    truth = truth_xy(p)
    return SceneResult(match_positions(detected, truth), frame, detected, truth)


def annotate(result: SceneResult, p: md.EpisodeParams, path: Path) -> None:
    """Green circles: detections. Red crosses: where the nominal camera says each true seed should appear."""
    import cv2

    img = cv2.cvtColor(result.frame, cv2.COLOR_RGB2BGR)
    z = md.box_of(p.color).floor_z + layout.SEED_RADIUS[p.color]
    for u, v in seed_detector.detect_seeds(result.frame, p.color):
        cv2.circle(img, (round(u), round(v)), 12, (0, 255, 0), 1, cv2.LINE_AA)
    for x, y in result.truth_xy:
        u, v = project((x, y, z))
        cv2.drawMarker(img, (round(u), round(v)), (0, 0, 255), cv2.MARKER_CROSS, 10, 1, cv2.LINE_AA)
    errs = ", ".join(f"{e:.1f}" for e in result.match.errors_mm)
    cv2.putText(img, f"{p.color} attempt {p.attempt}: err mm [{errs}] miss {result.match.misses} false {result.match.false}",
                (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def evaluate(color: str, n: int, *, camera_noise: bool, tray_plane: bool = False, annotated: int = 0,
             out_dir: Path = OUT_DIR, seed: int = sim_eval.HELDOUT_SEED, tag: str = "") -> dict:
    cal = tray_plane_calibration() if tray_plane else None
    errors, misses, false, truth_n = [], 0, 0, 0
    for k, p in enumerate(sim_eval.heldout_scenes(color, n, seed=seed, layout_mode="narrow")):
        r = measure_scene(p, camera_noise=camera_noise, calibration=cal)
        errors.extend(r.match.errors_mm)
        misses, false, truth_n = misses + r.match.misses, false + r.match.false, truth_n + len(r.truth_xy)
        if k < annotated:
            annotate(r, p, out_dir / f"{color}{tag}_{k:02d}.png")
    return {"color": color, "scenes": n, "seeds": truth_n, "matched": len(errors), "misses": misses, "false": false,
            **summarize(np.array(errors))}


def row(res: dict, label: str) -> str:
    f = lambda v: "-" if v is None else f"{v:.1f}"  # noqa: E731
    return (f"| {res['color']} | {label} | {res['scenes']} | {res['seeds']} | {res['matched']} | {res['misses']} | "
            f"{res['false']} | {f(res['median'])} | {f(res['p90'])} | {f(res['max'])} |")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", type=int, default=50, help="held-out narrow scenes per colour")
    ap.add_argument("--colors", nargs="+", default=["black", "white"])
    ap.add_argument("--no-camera-noise", action="store_true", help="render the nominal camera (detector error alone)")
    ap.add_argument("--tray-plane", action="store_true", help="use sim/config/calibration.json (tray-top height)")
    ap.add_argument("--annotate", type=int, default=3, help="annotated PNGs per colour in sim/out/detect/")
    args = ap.parse_args(argv)
    label = ("nominal camera" if args.no_camera_noise else "camera noise") + (", tray-plane cal" if args.tray_plane else ", seed-plane cal")
    print("| colour | case | scenes | seeds | matched | misses | false | median mm | p90 mm | max mm |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for color in args.colors:
        res = evaluate(color, args.episodes, camera_noise=not args.no_camera_noise, tray_plane=args.tray_plane,
                       annotated=args.annotate, tag="_nominal" if args.no_camera_noise else "")
        print(row(res, label), flush=True)


if __name__ == "__main__":
    main()
