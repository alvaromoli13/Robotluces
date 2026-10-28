"""Planner acceptance of candidate narrow-layout ranges (T5b evidence).

    backend/.venv/bin/python sim/scan_layout.py --attempts 40
    backend/.venv/bin/python sim/scan_layout.py --jitter 0.03 --yaw 30 --attempts 100

For each (centre jitter, yaw) pair draws `attempts` scenes per colour exactly like `build_dataset` (a placement the
scripted planner cannot grasp in is redrawn as the next `resample`) and prints the acceptance: `scenes / (scenes +
rejected placements)`, the number the dataset log calls `ik_acceptance`, with the share of the rejections that were a
`NoFit` (no jaw yaw clears the walls) and the geometric draw acceptance. Planning only, no physics.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import make_dataset as md  # noqa: E402
from smartseed_robot.kinematics import Kinematics  # noqa: E402


def scan(color: str, r: md.Randomisation, attempts: int, seed: int = 0, kin: Kinematics | None = None) -> dict:
    kin = kin or Kinematics()
    rejected = no_fit = draws = 0
    for attempt in range(attempts):
        resample = 0
        while True:
            p = md.sample_params(color, seed, attempt, resample, r)
            draws += p.proposals
            try:
                md.plan_actions(kin, p)
                break
            except md.Unreachable as exc:
                resample, no_fit = resample + 1, no_fit + isinstance(exc, md.NoFit)
        rejected += resample
    scenes = attempts + rejected
    return {"attempts": attempts, "planner_acceptance": attempts / scenes, "no_fit_share": no_fit / max(rejected, 1),
            "draw_acceptance": 3 * scenes / draws}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--attempts", type=int, default=40)
    ap.add_argument("--jitter", type=float, nargs="*", default=[0.02, 0.03, 0.04, 0.05], help="centre jitter, metres")
    ap.add_argument("--yaw", type=float, nargs="*", default=[15.0, 30.0], help="yaw bound, degrees")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    kin = Kinematics()
    print("jitter_cm yaw_deg colour planner_acceptance no_fit_share_of_rejections draw_acceptance")
    for j in args.jitter:
        for y in args.yaw:
            r = replace(md.RANDOM, anchor_jitter_m=j, anchor_yaw_deg=y)
            for color in ("black", "white"):
                s = scan(color, r, args.attempts, args.seed, kin)
                print(f"{100 * j:5.0f} {y:5.0f} {color:6s} {100 * s['planner_acceptance']:5.1f} % "
                      f"{100 * s['no_fit_share']:5.1f} % {100 * s['draw_acceptance']:5.1f} %", flush=True)


if __name__ == "__main__":
    main()
