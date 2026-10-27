"""Replay the kept episodes of a generation log and measure how deep the arm goes into box and tray walls.

    backend/.venv/bin/python sim/audit_walls.py --log sim/out/datasets/smartseed-sim-grasp-black/sim_generation.jsonl

Every scene is redrawn from its log line (`sample_params` is a pure function of it), planned and played through the
physics of the checkout this script runs in, without rendering, with the wall monitor in `geometry` mode: the signed
distance of every arm geom to every wall geom after each 1/30 s control step, whatever the collision bits say. That
makes it usable on the v1 datasets, where the moving-jaw hull and the pads did not collide with walls:

    git worktree add ../Robotluces-v1 874e274 && cp sim/collision.py sim/audit_walls.py ../Robotluces-v1/sim/
    (cd ../Robotluces-v1 && backend/.venv/bin/python sim/audit_walls.py --log <the v1 log>)

(the v1 generator is deterministic, so the replay is the episode that went into the dataset). Prints one line per
episode and a summary: the share of episodes a v2 generator would reject (`valid` is the same rule it uses).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import collision, grasp_test, make_dataset as md  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402


def audit_episode(p: md.EpisodeParams, kin, plan=None) -> tuple[collision.WallReport, bool]:
    """(wall report, seed lifted and held) of the episode of `p`, planned by this checkout unless `plan` is given."""
    actions, marks = plan if plan is not None else md.plan_actions(kin, p)
    robot = SimRobot(initial=dict(zip(JOINTS, map(float, actions[0]))))
    try:
        md.apply_scene(robot, p)
        monitor = collision.WallMonitor(robot._model, mode="geometry", every=1)
        hold = robot.read_joints()
        for _ in range(md.SETTLE_STEPS):
            robot.send_joints(hold)
        seed_rest, peak = grasp_test.seed_xyz(robot, p.color, p.target), 0.0
        for row in actions:
            robot.send_joints(dict(zip(JOINTS, map(float, row))))
            monitor(robot._model, robot._data)
            peak = max(peak, float(grasp_test.seed_xyz(robot, p.color, p.target)[2] - seed_rest[2]))
        ok = md.episode_success(seed_rest, grasp_test.seed_xyz(robot, p.color, p.target), grasp_test.tool_xyz(robot), peak)
        return monitor.report(), ok
    finally:
        robot.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", required=True, help="sim_generation.jsonl of a dataset")
    ap.add_argument("--limit", type=int, default=None, help="audit only the first N kept episodes")
    args = ap.parse_args()
    log = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line.strip()]
    scenes = md.logged_scenes(log)[:args.limit]
    kin = md.Kinematics()
    pens, lifted = [], 0
    for i, p in enumerate(scenes):
        report, ok = audit_episode(p, kin)
        lifted += ok
        pens.append(1000 * report.max_penetration_m)
        print(f"{p.color} attempt {p.attempt:3d} seed {p.target}: lifted {ok}, max penetration {pens[-1]:6.1f} mm, "
              f"{report.contact_steps} overlapping control steps -> {'valid' if report.valid else 'REJECTED'}", flush=True)
    pens = np.array(pens)
    rejected = int((pens > 1000 * collision.MAX_PENETRATION_M).sum())
    print(json.dumps({"episodes": len(pens), "replayed_lifted": lifted, "rejected": rejected,
                      "rejected_pct": round(100 * rejected / max(len(pens), 1), 1),
                      "over_5mm_pct": round(100 * float((pens > 5).mean()), 1),
                      "median_mm": round(float(np.median(pens)), 2), "p90_mm": round(float(np.percentile(pens, 90)), 2),
                      "max_mm": round(float(pens.max()), 2)}))


if __name__ == "__main__":
    main()
