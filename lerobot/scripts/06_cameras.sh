#!/usr/bin/env bash
# Live camera viewer: one window with every camera tiled and its OpenCV index on top.
# Use it to find out which index is each camera (CAM_TOP / CAM_WRIST in .env) and to frame them.
#
# Usage: ./scripts/06_cameras.sh            -> tries indices 0..5
#        ./scripts/06_cameras.sh 0 2        -> only those indices
# Keys: q / Esc to quit, s to save a frame of each camera to data/snapshots/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv

python - "${ROOT}" "${CAM_TOP:-}" "${CAM_WRIST:-}" "$@" <<'PY'
import sys, time, pathlib
import cv2
import numpy as np

root, cam_top, cam_wrist, *args = sys.argv[1:]
indices = [int(a) for a in args] if args else list(range(6))
names = {}
if cam_top != "": names[int(cam_top)] = "top"
if cam_wrist != "": names[int(cam_wrist)] = "wrist"

caps = {}
for i in indices:
    cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
    if cap.isOpened() and cap.read()[0]:
        caps[i] = cap
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"camera {i}: {w}x{h} {('(' + names[i] + ' in .env)') if i in names else ''}")
    else:
        cap.release()
if not caps:
    sys.exit("no camera opens — check the connection and Camera permission for the Terminal")

TILE_W, TILE_H = 640, 480
cols = 2 if len(caps) > 1 else 1
snap_dir = pathlib.Path(root) / "data" / "snapshots"
last, fps = time.time(), 0.0
while True:
    tiles = []
    for i, cap in caps.items():
        ok, frame = cap.read()
        frame = cv2.resize(frame, (TILE_W, TILE_H)) if ok else np.zeros((TILE_H, TILE_W, 3), np.uint8)
        label = f"idx {i}" + (f"  [{names[i]}]" if i in names else "")
        cv2.putText(frame, label, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
        cv2.putText(frame, label, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        tiles.append(frame)
    while len(tiles) % cols:
        tiles.append(np.zeros((TILE_H, TILE_W, 3), np.uint8))
    grid = np.vstack([np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)])
    now = time.time(); fps = 0.9 * fps + 0.1 / max(now - last, 1e-6); last = now
    cv2.putText(grid, f"{fps:.0f} fps  q=quit s=snapshot", (12, grid.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imshow("cameras", grid)
    key = cv2.waitKey(1) & 0xFF
    if key in (ord("q"), 27):
        break
    if key == ord("s"):
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        for i, t in zip(caps, tiles):
            cv2.imwrite(str(snap_dir / f"cam{i}_{stamp}.png"), t)
        print(f"snapshots saved in {snap_dir}")

for cap in caps.values():
    cap.release()
cv2.destroyAllWindows()
PY
