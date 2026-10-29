"""How deep do the arm's collision geoms go into the table, the paper and the mat in a recorded dataset? (T5f)

Replays the recorded `observation.state` of every episode (no physics) through the twin's forward kinematics and reads
the contact list against the table, the paper and the mat. It works on any dataset, including the ones generated before
the arm collided with the ground: the ground geoms are opened to the arm's bits here, at the geom AND the body level
(MuJoCo's broad phase filters on the body bits, which are fixed when the model is compiled).

    backend/.venv/bin/python sim/audit_table.py sim/out/datasets/smartseed-sim-grasp-black-v5-dart [--every 3] [--limit 600]

Prints the per-episode maximum penetration (median, p90, max, how many episodes are over 2 / 5 / 10 mm), the worst
arm geom, and the penetration at the first frame of every episode (the start pose).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

import mujoco  # noqa: E402
import pandas as pd  # noqa: E402

from sim import collision  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import DEFAULT_SCENE, joints_to_qpos  # noqa: E402

ARM_BITS = 1 | 8 | 16  # hulls, pads, moving-jaw hull


def open_ground_to_the_arm(model) -> list[int]:
    """Make the ground collide with the arm whatever the scene says; returns the ground geom ids."""
    ground = collision.table_geoms(model)
    for g in ground:
        model.geom_conaffinity[g] |= ARM_BITS
        model.body_conaffinity[model.geom_bodyid[g]] |= ARM_BITS
    return ground


def episode_penetrations(model, data, states: np.ndarray, episodes: np.ndarray, every: int = 1) -> dict:
    """{episode: (max penetration m, penetration at its first frame m, worst arm geom name)}."""
    ground = set(open_ground_to_the_arm(model))
    arm = set(collision.arm_geoms(model))
    adr = [model.joint(j).qposadr[0] for j in JOINTS]
    out: dict = {}
    first_seen = set()
    for i, (ep, st) in enumerate(zip(episodes, states)):
        first = ep not in first_seen
        if not first and i % every:
            continue
        first_seen.add(ep)
        data.qpos[adr] = joints_to_qpos(dict(zip(JOINTS, st)))
        mujoco.mj_forward(model, data)
        pen, worst = 0.0, ""
        for k in range(data.ncon):
            c = data.contact[k]
            a, b = (c.geom1, c.geom2) if c.geom1 in arm else (c.geom2, c.geom1)
            if a in arm and b in ground and -c.dist > pen:
                pen, worst = -float(c.dist), model.geom(a).name or model.body(model.geom_bodyid[a]).name
        prev = out.get(ep, (0.0, 0.0, ""))
        out[ep] = (max(prev[0], pen), pen if first else prev[1], worst if pen > prev[0] else prev[2])
    return out


def summarise(per_episode: dict) -> str:
    v = np.array([p[0] for p in per_episode.values()]) * 1000
    s = np.array([p[1] for p in per_episode.values()]) * 1000
    worst: dict[str, int] = {}
    for pen, _, geom in per_episode.values():
        if pen > 0.002:
            worst[geom] = worst.get(geom, 0) + 1
    return (f"episodes {len(v)}; max penetration per episode: median {np.median(v):.2f} mm, p90 {np.percentile(v, 90):.2f}, "
            f"max {v.max():.2f}; episodes >2 mm {int((v > 2).sum())}, >5 mm {int((v > 5).sum())}, >10 mm {int((v > 10).sum())}; "
            f"start pose: max {s.max():.2f} mm; worst geoms over 2 mm: {worst or 'none'}")


def audit(root: Path, every: int = 3, limit: int | None = None) -> str:
    files = sorted((root / "data").glob("*/*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "observation.state"]) for f in files])
    if limit is not None:
        df = df[df.episode_index < limit]
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_SCENE))
    data = mujoco.MjData(model)
    return summarise(episode_penetrations(model, data, np.stack(df["observation.state"].to_numpy()),
                                          df.episode_index.to_numpy(), every))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("datasets", nargs="+", type=Path)
    ap.add_argument("--every", type=int, default=3, help="audit every Nth frame (the first of each episode always)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N episodes")
    args = ap.parse_args(argv)
    for root in args.datasets:
        print(f"{root.name}: {audit(root, args.every, args.limit)}", flush=True)


if __name__ == "__main__":
    main()
