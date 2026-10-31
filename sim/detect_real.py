"""A4: the seed detector on REAL top-camera frames of the hackathon datasets (no ground truth, counts and pictures).

The first frame of the top camera of a sample of episodes of the real d1 (black seeds) and d2 (white seeds) LeRobot
datasets, read straight from the local copies under `HF_LEROBOT_HOME` (default `~/.cache/huggingface/lerobot`), is the
scene as it is before the arm moves: every seed of the box is in view. The detector (`seed_detector.detect_seeds`)
runs on it and the frame is saved annotated (green circle: a detection) to `sim/out/detect_real/` (git-ignored) next to
the untouched frame. Real frames have no seed positions, so what is reported is the detections per frame; the number of
seeds actually visible is counted by looking at the saved images (`--counts` takes those numbers for the final table).

    backend/.venv/bin/python sim/detect_real.py                      # 12 episodes of each dataset
    backend/.venv/bin/python sim/detect_real.py --episodes 24 --counts sim/detect_real_counts.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from smartseed_robot import seed_detector  # noqa: E402

OUT_DIR = ROOT / "sim" / "out" / "detect_real"
DATASETS = {"black": "RafaelJaime/smartseed-grasp-d1-clean", "white": "RafaelJaime/smartseed-grasp-d2-clean"}
TOP = "observation.images.top"


def lerobot_home() -> Path:
    return Path(os.environ.get("HF_LEROBOT_HOME") or Path.home() / ".cache" / "huggingface" / "lerobot")


def sample_episodes(total: int, n: int) -> list[int]:
    """`n` episode indices spread evenly over `total` (all of them when fewer)."""
    if n >= total:
        return list(range(total))
    return sorted({int(i) for i in np.linspace(0, total - 1, n)})


def frame_at(video: Path, timestamp: float) -> np.ndarray:
    """The decoded RGB frame of `video` at `timestamp` seconds (the first frame at or after it)."""
    import av

    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        container.seek(int(timestamp / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            if frame.time is not None and frame.time + 1e-6 >= timestamp:
                return frame.to_ndarray(format="rgb24")
    raise ValueError(f"no frame at {timestamp} s in {video}")


def first_frames(root: Path, episodes: list[int]) -> dict[int, np.ndarray]:
    """The first top frame of each episode of the dataset at `root` (a LeRobot v3 dataset: one mp4 holds many)."""
    import pandas as pd

    meta = pd.concat([pd.read_parquet(f) for f in sorted((root / "meta" / "episodes").rglob("*.parquet"))])
    meta = meta.set_index("episode_index")
    out = {}
    for ep in episodes:
        row = meta.loc[ep]
        video = root / "videos" / TOP / f"chunk-{int(row[f'videos/{TOP}/chunk_index']):03d}" / \
            f"file-{int(row[f'videos/{TOP}/file_index']):03d}.mp4"
        out[ep] = frame_at(video, float(row[f"videos/{TOP}/from_timestamp"]))
    return out


def annotate(frame: np.ndarray, centres, label: str) -> np.ndarray:
    """The frame (RGB) with a green circle on each detection and the label on top; returns RGB."""
    import cv2

    img = frame.copy()
    for u, v in centres:
        cv2.circle(img, (round(u), round(v)), 12, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(img, label, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, label, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def run(color: str, n: int, out_dir: Path = OUT_DIR, home: Path | None = None) -> dict[int, list[tuple[float, float]]]:
    import cv2

    root = (home or lerobot_home()) / DATASETS[color]
    total = json.loads((root / "meta" / "info.json").read_text())["total_episodes"]
    frames = first_frames(root, sample_episodes(total, n))
    out_dir.mkdir(parents=True, exist_ok=True)
    found = {}
    for ep, frame in frames.items():
        found[ep] = seed_detector.detect_seeds(frame, color)
        cv2.imwrite(str(out_dir / f"{color}_ep{ep:03d}_raw.png"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        shown = annotate(frame, found[ep], f"{color} ep {ep}: {len(found[ep])} detected")
        cv2.imwrite(str(out_dir / f"{color}_ep{ep:03d}.png"), cv2.cvtColor(shown, cv2.COLOR_RGB2BGR))
    return found


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", type=int, default=12, help="episodes sampled per dataset")
    ap.add_argument("--colors", nargs="+", default=["black", "white"])
    ap.add_argument("--counts", type=Path, default=None, help="JSON {colour: {episode: seeds you see}} for the summary")
    args = ap.parse_args(argv)
    seen = json.loads(args.counts.read_text()) if args.counts else {}
    print("| colour | episode | detected | visible |\n|---|---|---|---|")
    for color in args.colors:
        found = run(color, args.episodes)
        for ep, centres in found.items():
            print(f"| {color} | {ep} | {len(centres)} | {seen.get(color, {}).get(str(ep), '?')} |")
        total = sum(len(c) for c in found.values())
        print(f"| {color} | all {len(found)} | {total} | {sum(seen.get(color, {}).values()) if color in seen else '?'} |")


if __name__ == "__main__":
    main()
