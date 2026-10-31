"""T5g: goal-conditioned ACT. Add the target seed position to a sim dataset as `observation.environment_state`.

    backend/.venv/bin/python sim/add_target.py --color black                       # v5-dart -> v5-target, 4 mm noise
    backend/.venv/bin/python sim/add_target.py --color white --target-noise-mm 0   # the exact position

ACT trained on the plain dataset misses the seed by about 2 cm even with one seed in the box: it cannot localise it from
the images. The scripted planner knows where the seed is; this gives the policy the same number. The new float32 feature
`observation.environment_state` has shape [2] (x, y of the seed the demonstration grasps, robot base frame, metres) and is
constant over each episode; lerobot's ACT takes it as `env_state_feature`. The position comes from the generation log
(`sim_generation.jsonl`): each kept episode's scene is redrawn with `make_dataset.sample_params` and read with
`EpisodeParams.seed_xy`, the very function the planner aims with. A Gaussian error (default 4 mm per axis, seeded by
episode index and colour, once per episode) stands in for a detector, so the policy tolerates one. Nothing is uploaded.

The copy is written with lerobot's `dataset_tools.add_features` (re-indexed data files, videos copied as they are); that
tool leaves the new feature out of `stats.json` and of the per-episode stats, so both are computed here with lerobot's
`compute_episode_stats` / `aggregate_stats`.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import make_dataset as md  # noqa: E402
from sim.run_policy import target_noise  # noqa: E402
from smartseed_robot.act import ENV_STATE_KEY  # noqa: E402

DATASETS = ROOT / "sim" / "out" / "datasets"
DEFAULT_SIGMA_MM = 4.0
FRAME = "robot base frame, metres"
FEATURE_INFO = {"dtype": "float32", "shape": [2], "names": ["x", "y"]}
NOISE_FILE, TARGETS_FILE = "target_noise.json", "sim_targets.jsonl"


def target_xy(p: md.EpisodeParams) -> np.ndarray:
    """(x, y) of the seed the demonstration of scene `p` grasps, base frame, metres (what `plan_actions` aims at)."""
    return p.seed_xy(p.color, p.target)


def episode_rng(episode_index: int, color: str) -> np.random.Generator:
    return np.random.default_rng([episode_index, zlib.crc32(color.encode())])


def target_name(source_name: str) -> str:
    return source_name.removesuffix("-dart") + "-target"


def episode_scenes(root: Path, color: str, total_episodes: int, layout_mode: str) -> list[md.EpisodeParams]:
    """The scene of every episode of the dataset at `root`, in episode order, from its generation log. Refuses a log that
    does not describe exactly the dataset's episodes (count, indices, colour, target, seeds present)."""
    kept = [r for r in md._read_log(root) if r["ok"]]
    if len(kept) != total_episodes:
        raise ValueError(f"the dataset has {total_episodes} episodes, its log keeps {len(kept)}")
    if [r.get("episode_index") for r in kept] != list(range(total_episodes)):
        raise ValueError("the log's kept episodes are not numbered 0..N-1 in order (a recovered or pruned episode?)")
    scenes = []
    for r in kept:
        p = md.sample_params(r["color"], r["seed"], r["attempt"], r.get("ik_rejections", 0), md.LAYOUTS[layout_mode])
        if r["color"] != color or p.target != r["target"] or list(p.present) != r["present"]:
            raise ValueError(f"episode {r['episode_index']}: the redrawn scene does not match its log line (layout {layout_mode}?)")
        scenes.append(p)
    return scenes


def _episode_stats(per_episode: np.ndarray, lengths: np.ndarray) -> list[dict]:
    from lerobot.datasets.compute_stats import compute_episode_stats

    features = {ENV_STATE_KEY: FEATURE_INFO}
    return [compute_episode_stats({ENV_STATE_KEY: np.tile(v, (n, 1))}, features) for v, n in zip(per_episode, lengths)]


def _write_stats(out: Path, stats: list[dict]) -> None:
    """The feature's global stats into `meta/stats.json`, its per-episode ones into the episodes metadata."""
    import pandas as pd
    from lerobot.datasets.compute_stats import aggregate_stats
    from lerobot.datasets.io_utils import write_stats

    path = out / "meta" / "stats.json"
    merged = {k: {s: np.asarray(v) for s, v in d.items()} for k, d in json.loads(path.read_text()).items()}
    merged |= aggregate_stats(stats)
    write_stats(merged, out)
    files = sorted((out / "meta" / "episodes").glob("*/*.parquet"))
    done = 0
    for f in files:
        df = pd.read_parquet(f)
        for stat in stats[0][ENV_STATE_KEY]:
            df[f"stats/{ENV_STATE_KEY}/{stat}"] = [np.asarray(s[ENV_STATE_KEY][stat]).tolist() for s in stats[done:done + len(df)]]
        done += len(df)
        df.to_parquet(f)
    assert done == len(stats)


def target_card(color: str, source_name: str, sigma_mm: float, episodes: int, frames: int, ranges: dict) -> str:
    return f"""---
license: apache-2.0
task_categories:
- robotics
tags:
- LeRobot
- BraboRobots
- smartseed
- robotekin-hackathon
- lerobot
- so101
- simulation
- mujoco
configs:
- config_name: default
  data_files: data/*/*.parquet
---

# {target_name(source_name)}

**Simulated** demonstrations of the SmartSeed grasp task ({color} seeds), generated in a MuJoCo twin of the scene; not
real recordings. This is [`{md.HF_USER}/{source_name}`](https://huggingface.co/datasets/{md.HF_USER}/{source_name}) with
one extra feature for a goal-conditioned ACT. Frames, actions, states and videos are the source's, unchanged
({episodes} episodes, {frames:,} frames at 30 fps); see its card for how they were generated and validated.

| feature | dtype | shape | meaning |
|---|---|---|---|
| `observation.environment_state` | float32 | [2] | x, y of the seed the episode grasps, **{FRAME}**, constant over the episode |

- **Frame and units**: the robot base frame the planner works in (x forward, y left of the arm), metres. Over the
  {episodes} episodes x is {ranges['x'][0]:.3f} to {ranges['x'][1]:.3f} m and y {ranges['y'][0]:.3f} to {ranges['y'][1]:.3f} m.
- **Noise**: the true seed position plus a Gaussian error of **{sigma_mm:g} mm per axis** (standard deviation), drawn once
  per episode from a generator seeded by (episode index, colour). It stands in for the error of a top-camera detector, so a
  policy trained on this tolerates one. `{NOISE_FILE}` records the sigma; `{TARGETS_FILE}` has the true and the noisy
  position of every episode.
- **Why**: an ACT trained on the source dataset misses the seed by about 2 cm even when it is alone in the box, because it
  cannot localise it from the images. With this input it only has to reach a given point.
- **Use**: lerobot's ACT takes `observation.environment_state` as its `env_state_feature` (no config change); at
  inference the caller must supply the same key (a detector's estimate on the real arm, the scene's seed in the twin).
- Created with `sim/add_target.py` of the SmartSeed repository (`lerobot.datasets.dataset_tools.add_features`).
"""


def add_target(src: Path, dst: Path, color: str, sigma_mm: float = DEFAULT_SIGMA_MM, layout_mode: str = "narrow") -> dict:
    """Write `dst`: the dataset at `src` plus `observation.environment_state`. Returns {episodes, frames, sigma_mm}."""
    import pandas as pd
    from lerobot.datasets.dataset_tools import add_features
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise FileExistsError(f"{dst} exists; refusing to overwrite it")
    ds = LeRobotDataset(f"local/{src.name}", root=src)
    n, frames = ds.meta.total_episodes, ds.meta.total_frames
    scenes = episode_scenes(src, color, n, layout_mode)
    lengths = np.array([int(v) for v in ds.meta.episodes["length"]])
    rows = pd.concat([pd.read_parquet(f, columns=["episode_index"]) for f in sorted((src / "data").glob("*/*.parquet"))])
    if lengths.sum() != frames or not np.array_equal(rows.episode_index.to_numpy(), np.repeat(np.arange(n), lengths)):
        raise ValueError("the data rows are not episodes 0..N-1 laid out one after the other")

    clean = np.array([target_xy(p) for p in scenes])
    noise = np.array([target_noise(episode_rng(i, color), sigma_mm) for i in range(n)])
    per_episode = (clean + noise).astype(np.float32)
    values = np.repeat(per_episode, lengths, axis=0)
    add_features(ds, {ENV_STATE_KEY: (values, FEATURE_INFO)}, output_dir=dst, repo_id=f"local/{dst.name}")
    _write_stats(dst, _episode_stats(per_episode, lengths))

    (dst / md.LOG_NAME).write_text((src / md.LOG_NAME).read_text())
    (dst / NOISE_FILE).write_text(json.dumps({
        "feature": ENV_STATE_KEY, "frame": FRAME, "color": color, "sigma_mm": sigma_mm, "source": src.name,
        "noise": "Gaussian per axis, once per episode, np.random.default_rng([episode_index, crc32(color)])"}, indent=2) + "\n")
    (dst / TARGETS_FILE).write_text("".join(
        json.dumps({"episode_index": i, "target_xy": clean[i].tolist(), "noise_xy": noise[i].tolist(),
                    "feature_xy": per_episode[i].tolist()}) + "\n" for i in range(n)))
    ranges = {"x": (float(per_episode[:, 0].min()), float(per_episode[:, 0].max())),
              "y": (float(per_episode[:, 1].min()), float(per_episode[:, 1].max()))}
    (dst / "README.md").write_text(target_card(color, src.name, sigma_mm, n, frames, ranges))
    return {"episodes": n, "frames": frames, "sigma_mm": sigma_mm}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--color", choices=["black", "white"], required=True)
    ap.add_argument("--source", type=Path, default=None, help="default: sim/out/datasets/smartseed-sim-grasp-<colour>-v5-dart")
    ap.add_argument("--out", type=Path, default=None, help="default: next to the source, -dart replaced by -target")
    ap.add_argument("--target-noise-mm", type=float, default=DEFAULT_SIGMA_MM,
                    help="Gaussian error on the target, mm per axis, once per episode (0 = the exact position)")
    ap.add_argument("--layout", choices=sorted(md.LAYOUTS), default="narrow", help="layout the source was generated with")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    src = args.source or DATASETS / md.dataset_name(args.color, "narrow", dart=True)
    out = args.out or src.with_name(target_name(src.name))
    summary = add_target(src, out, args.color, args.target_noise_mm, args.layout)
    print(f"{out}: {summary}")


if __name__ == "__main__":
    main()
