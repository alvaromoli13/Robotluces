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


def _episode_rows(root: Path) -> pd.DataFrame:
    files = sorted((root / "data").glob("*/*.parquet"))
    return pd.concat([pd.read_parquet(f, columns=["episode_index"]) for f in files], ignore_index=True)


def alignment_problems(root: Path) -> list[str]:
    """Per-episode alignment: every episode is one contiguous run of rows (first and last row carry its index) and the
    rows add up to `info.json`'s `total_frames`. Returns human-readable problems, empty when aligned."""
    import json

    ep = _episode_rows(root).episode_index.to_numpy()
    problems = []
    bounds = np.flatnonzero(np.diff(ep) != 0) + 1
    starts, ends = np.r_[0, bounds], np.r_[bounds, len(ep)] - 1
    seen: set[int] = set()
    for a, b in zip(starts, ends):
        index = int(ep[a])
        if index in seen:
            problems.append(f"episode {index}: its rows are not contiguous")
        seen.add(index)
        if ep[b] != ep[a]:
            problems.append(f"episode {index}: first row {ep[a]}, last row {ep[b]}")
    total = json.loads((root / "meta" / "info.json").read_text())["total_frames"]
    if total != len(ep):
        problems.append(f"total_frames {total} != {len(ep)} rows")
    # an episode run must also be the index it claims: indices go 0, 1, 2, ... in file order
    order = [int(ep[a]) for a in starts]
    for i, index in enumerate(order):
        if index != i and f"episode {index}" not in " ".join(problems):
            problems.append(f"episode {index}: appears at position {i}")
    return problems


def log_violations(root: Path) -> dict[int, str]:
    """Kept episodes whose generation-log record is over a limit (wall 1 mm / 2 N, table 2 mm): {episode: why}."""
    from sim import make_dataset as md

    out = {}
    for r in md._read_log(root):
        if not r.get("ok") or r.get("episode_index") is None:
            continue
        i = r["episode_index"]
        if r.get("wall_max_penetration_mm", 0) > 1000 * collision.MAX_PENETRATION_M:
            out[i] = f"wall {r['wall_max_penetration_mm']:.1f} mm"
        elif r.get("wall_max_force_n", 0) > collision.MAX_FORCE_N:
            out[i] = f"wall force {r['wall_max_force_n']:.1f} N"
        elif r.get("table_max_penetration_mm", 0) > 1000 * collision.MAX_TABLE_PENETRATION_M:
            out[i] = f"table {r['table_max_penetration_mm']:.1f} mm"
    return out


def table_violations(root: Path, every: int = 3) -> dict[int, str]:
    """Episodes whose recorded states put an arm geom more than 2 mm into the table, paper or mat."""
    files = sorted((root / "data").glob("*/*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "observation.state"]) for f in files])
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_SCENE))
    per = episode_penetrations(model, mujoco.MjData(model), np.stack(df["observation.state"].to_numpy()),
                               df.episode_index.to_numpy(), every)
    return {int(ep): f"table {1000 * v[0]:.1f} mm ({v[2]})" for ep, v in per.items() if v[0] > collision.MAX_TABLE_PENETRATION_M}


def gate(root: Path, every: int = 3) -> dict:
    """Everything the v5 datasets must pass: {"alignment": [...], "episodes": {index: why}}; empty means clean."""
    bad = {**log_violations(root), **table_violations(root, every)}
    return {"alignment": alignment_problems(root), "episodes": dict(sorted(bad.items()))}


def prune(root: Path, episodes: list[int]) -> None:
    """Remove episodes with lerobot's own tool (`dataset_tools.delete_episodes`): writes a re-indexed copy next to the
    dataset, swaps it in, keeps the original as `<name>.pre-prune` and rewrites the log's indices to match."""
    import json
    import shutil

    from lerobot.datasets.dataset_tools import delete_episodes
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    from sim import make_dataset as md

    new, backup = root.with_name(root.name + ".pruned"), root.with_name(root.name + ".pre-prune")
    delete_episodes(LeRobotDataset(f"local/{root.name}", root=root), episodes, output_dir=new, repo_id=f"local/{root.name}")
    gone = set(episodes)
    log = md._read_log(root)
    remap = {i: i - sum(g < i for g in gone) for i in range(max((r.get("episode_index") or 0) for r in log) + 1) if i not in gone}
    lines = []
    for r in log:
        i = r.get("episode_index")
        if i is not None and i in gone:
            r = r | {"ok": False, "reason": "pruned by the audit", "episode_index": None}
        elif i is not None:
            r = r | {"episode_index": remap[i]}
        lines.append(json.dumps(r))
    (new / md.LOG_NAME).write_text("\n".join(lines) + "\n")
    root.rename(backup)
    new.rename(root)
    print(f"pruned {len(gone)} episodes from {root.name}; original kept as {backup.name}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("datasets", nargs="+", type=Path)
    ap.add_argument("--every", type=int, default=3, help="audit every Nth frame (the first of each episode always)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N episodes")
    ap.add_argument("--gate", action="store_true", help="also check alignment and the generation log; exit 1 on a violation")
    ap.add_argument("--prune", action="store_true", help="with --gate: delete the violating episodes (lerobot tool), then re-audit")
    args = ap.parse_args(argv)
    failed = False
    for root in args.datasets:
        print(f"{root.name}: {audit(root, args.every, args.limit)}", flush=True)
        if not (args.gate or args.prune):
            continue
        result = gate(root, args.every)
        if result["episodes"] and args.prune:
            prune(root, sorted(result["episodes"]))
            print(f"{root.name}: pruned {len(result['episodes'])}: {result['episodes']}", flush=True)
            result = gate(root, args.every)
        print(f"{root.name}: gate violations {len(result['episodes'])} episodes, {len(result['alignment'])} alignment problems"
              f" {result['alignment'] or ''} {result['episodes'] or ''}", flush=True)
        failed |= bool(result["episodes"] or result["alignment"])
    sys.exit(int(failed))


if __name__ == "__main__":
    main()
