"""Export one recorded LeRobot episode to an .npz the sim scripts read (states, actions, every Nth camera frame).

Run it with an interpreter that has `lerobot` (the competition venv or `lerobot/.venv`); the decoder falls back to
pyav when torchcodec cannot load. No MuJoCo needed here.

    python sim/export_episode.py --repo RafaelJaime/smartseed-grasp-d1-clean --episode 0 --out sim/out/ep0.npz
"""
from __future__ import annotations

import argparse

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="RafaelJaime/smartseed-grasp-d1-clean")
    ap.add_argument("--episode", type=int, default=0)
    ap.add_argument("--frame-step", type=int, default=10, help="keep every Nth camera frame (states are all kept)")
    ap.add_argument("--out", default="sim/out/ep0.npz")
    args = ap.parse_args()

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds = LeRobotDataset(args.repo, episodes=[args.episode])
    state, action, frames, top, wrist = [], [], [], [], []
    to_hwc = lambda t: (t.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
    for i in range(len(ds)):
        item = ds[i]
        state.append(item["observation.state"].numpy())
        action.append(item["action"].numpy())
        if i % args.frame_step == 0:
            frames.append(i)
            top.append(to_hwc(item["observation.images.top"]))
            wrist.append(to_hwc(item["observation.images.wrist"]))
    np.savez_compressed(args.out, state=np.array(state), action=np.array(action), fps=ds.fps,
                        frame_index=np.array(frames), top=np.array(top), wrist=np.array(wrist), repo=args.repo,
                        episode=args.episode)
    print(f"{args.out}: {len(state)} steps at {ds.fps} fps, {len(frames)} camera frames")


if __name__ == "__main__":
    main()
