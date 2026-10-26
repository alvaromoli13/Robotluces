# SmartSeed 🌱

An **SO-101** robot arm sows seeds into a seedling tray. The grower designs the tray in a
cinema-seat-style web UI on top of a live camera image, and the robot sows every cell with the
chosen seed.

Built by team **BraboRobots** at the Robotekin LeRobot hackathon (Vitoria-Gasteiz, 23-25 October
2026). The event is over; this repository is the finished, replicable result.

> **The web UI is in Spanish.** It is the product UI used at the event, so labels such as
> *Escanear* (scan), *Sembrar* (sow), *Parar* (stop) and *Ajustes* (settings) are kept as they
> were. Everything else (code, docs, API) is in English. Project idea, architecture and the
> original plan: [guide.md](guide.md).

## How it works

A **hybrid** approach: only the hard perception part is learned, the geometry is computed.

```
web UI (web/)  ──scan──►  vision backend (OWLv2 + depth)  ──►  tray, holes, occupied holes
      │
      └──Sembrar──► POST /plan ──► robot backend (backend/smartseed_robot)
                                     per cell:
                                       act_start pose
                                       → ACT policy (one per seed-box colour) grasps a seed
                                       → IK moves over the hole, closed-loop drop correction
                                       → wrist +5°, open gripper → act_start   (last cell → home)
```

- **Vision** (`backend/smartseed_vision`): OWLv2 box + OpenCV geometry, and Depth Anything V2
  Small to find holes as basins enclosed by walls. No markers are needed on the tray (the web
  also supports ArUco markers, ids 0-3 = TL/TR/BR/BL, as an optional higher-priority source).
- **Robot** (`backend/smartseed_robot`): placo IK on the SO-101 URDF, pixel→robot homography,
  taught poses, ACT policy closed loop at 30 Hz, plan validated *before* any motor moves.
- **Policies**: one ACT policy per seed-box colour (black box = Tomate, white box = Pimiento),
  so the policy looks for "its" box by colour, wherever it is placed.

## Hardware

| Item | Notes |
|---|---|
| SO-101 **follower** + **leader** arms | leader is only needed to record datasets (teleoperation) |
| **Top camera** (`top`) | fixed overview of the table, USB, 640x480@30 |
| **Wrist camera** (`wrist`) | mounted on the gripper, USB, 640x480@30 |
| **Seed boxes**, black and white | one colour per seed type; they can be moved within their zone |
| **Seedling tray** | any shape; located by vision without markers. Cameras and robot must not move after calibration |
| ArUco markers (optional) | `ARUCO_MIP_36h12`, ids 0-3 at the tray corners; not required |
| Mac with Apple Silicon (used here) | MPS for inference; CPU works but is slow. Linux + CUDA works for training |

## Software setup

Requirements: macOS/Linux, **Python 3.12** and [uv](https://docs.astral.sh/uv/), a recent Node LTS only
for the web tests.

```bash
git clone https://github.com/alvaromoli13/Robotluces.git && cd Robotluces
cd backend && uv sync        # first time: torch, transformers, OpenCV, lerobot into backend/.venv
```

- **lerobot** is pinned to commit **`e595b79`** (`backend/pyproject.toml`), the same one the
  policies were trained with (`scripts/brev/*.sh` check it out too). Do not bump it without
  re-validating the policies.
- The SO-101 URDF and meshes are in `backend/assets/so101/` (provenance in `SOURCE.md`).
- The web has no build step and loads nothing from a CDN (`web/fonts`, `web/vendor`).
- On macOS, run the stack from **Terminal.app or VS Code**: camera permission goes to the app
  that launches the process.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SMARTSEED_ROBOT` | `fake` (`real` in `scripts/stack.sh`) | `fake` opens no serial port or camera; `real` moves the arm |
| `SMARTSEED_ROBOT_PORT` | none (event port in `stack.sh`) | follower serial port, required when `real`. Find yours: `ls /dev/tty.usbmodem*` (macOS) or `/dev/ttyACM*` (Linux), unplug/replug the follower to see which entry changes |
| `SMARTSEED_ACT_POLICIES` | empty (no ACT) | JSON `{"<colour>": "<HF repo or local path>"}`, e.g. `{"black":"RafaelJaime/act-smartseed-d1-c100","white":"RafaelJaime/act-smartseed-d2-c100"}` |
| `SMARTSEED_ACT_DURATION_S` | `10` | seconds of policy per cell (match the episode length used for training) |
| `SMARTSEED_ACT_DEBUG_DIR` | none | if set, the ACT loop logs timing and first frames there |
| `SMARTSEED_CAM_TOP` / `SMARTSEED_CAM_WRIST` | `0` / `1` | OpenCV index or path of each camera |
| `SMARTSEED_POLICY_DEVICE` | `mps` if available, else `cpu` | inference device |
| `SMARTSEED_DATA_DIR` | `backend/data/` | where `poses.json` and `calibration.json` live (git-ignored) |
| `SMARTSEED_DISABLE_MODEL` | none | `1` skips OWLv2 and depth (contour only), for quick tests |
| `SMARTSEED_WEB_PORT` | `8080` | web port used by `scripts/stack.sh` |

## Quick start

```bash
# No hardware: fake robot, vision on 127.0.0.1:8000
cd backend && ./run.sh
open web/index.html          # or: python3 -m http.server 8080 -d web

# Full local stack with the real arm and the default policies (backend + web at :8080)
SMARTSEED_ROBOT_PORT=/dev/tty.usbmodemXXXX scripts/stack.sh
```

`scripts/stack.sh` serves the backend on `127.0.0.1:8000` and the web on
`http://localhost:8080/`, defaults to `black`→`act-smartseed-d1-c100` and
`white`→`act-smartseed-d2-c100`, and refuses to start if a port is busy. Ctrl-C stops both.
If the backend runs elsewhere, set in the browser console:
`localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')`.

The published GitHub Pages site (<https://alvaromoli13.github.io/Robotluces/>) runs in **demo
mode** and never sends robot commands; only a local backend controls the arm.

## One-time robot setup

1. **Calibrate the arms** with lerobot (`lerobot-calibrate`), using the **same id** everywhere
   (the backend opens the follower as `follower_01`; leader `leader_01` was used for recording).
   A different id means a different calibration file and policies will not transfer.
   ```bash
   lerobot-calibrate --robot.type=so101_follower --robot.port=<follower port> --robot.id=follower_01
   lerobot-calibrate --teleop.type=so101_leader --teleop.port=<leader port> --teleop.id=leader_01
   ```
2. **Scene**: mark the tray zone and one zone per box colour, fix `top` and `wrist` cameras. From
   here on cameras and robot do not move.
3. **Camera-robot calibration** (in the web): *Escanear* → *Calibrar robot* → *Soltar brazo*
   (torque off), move the gripper tip to a visible point on the tray and click that point in the
   image. With at least 4 spread points press *Ajustar*; it reports the error in mm. Same thing
   by HTTP: `POST /robot/calibration/points {"u","v","image_size":[w,h]}` then
   `POST /robot/calibration/fit`. Check it with a 10-hole test before continuing.
4. **Teach poses** (torque off, place the arm, then `POST /robot/poses/<name>` or the *Guardar*
   buttons):
   - `act_start`: the arm where the training episodes begin. Without it the mean of the recorded
     episodes `[1.1, -102.7, 96.8, 47.7, -6.0, 6.3]` is used.
   - `home`: resting pose; the plan ends there.
   - Colours **without** a policy also need `above_box_<colour>` and `grasp_<colour>`.
   Then `POST /robot/torque-on` (it first targets the current position, so the arm does not jump)
   and check each pose with `POST /robot/goto/<name>`. While torque is off, `goto` and `/plan`
   answer `409 torque_off`.
5. **Sanity-check forward kinematics**: `GET /robot/joints` returns angles and `tool` (x, y, z in
   metres from the base); measure the tip with a ruler.

## Record datasets

One ACT policy per box colour, each with its own dataset. An episode starts at `act_start`,
goes to the box of that colour, grasps a seed and returns. Put both boxes on the table and
swap them between episodes, and vary the light, so the policy learns to find its colour.
The final datasets used 10 s episodes and the task `grasp the seed below the gripper`.

```bash
lerobot-record \
  --robot.type=so101_follower --robot.port=<follower port> --robot.id=follower_01 \
  --robot.cameras='{top: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' \
  --teleop.type=so101_leader --teleop.port=<leader port> --teleop.id=leader_01 \
  --dataset.repo_id=<user>/smartseed-grasp-<colour> \
  --dataset.single_task="grasp the seed below the gripper" \
  --dataset.num_episodes=100 --dataset.episode_time_s=10 --dataset.reset_time_s=5 \
  --dataset.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101"]'
```

Camera names **must** be `top` and `wrist` (the backend feeds the policy
`observation.images.top` / `.wrist`). Stop the backend in `real` mode before recording: both
use the follower port. lerobot 0.6 appends a `_YYYYMMDD_HHMMSS` stamp to new dataset ids; to add
episodes, resume with the full stamped name. Episodes were then cleaned by hand (see the
datasets table). We recorded with a separate helper environment (wrapper scripts around the
commands above); only plain lerobot commands are needed.

## Train

```bash
lerobot-train \
  --policy.type=act --policy.device=mps \
  --dataset.repo_id=<user>/smartseed-grasp-<colour> \
  --batch_size=8 --steps=30000 \
  --output_dir=outputs/train/act-smartseed-<colour> \
  --job_name=act-smartseed-<colour> \
  --policy.repo_id=<user>/act-smartseed-<colour> \
  --policy.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101"]'
```

**Local (Apple Silicon, MPS):** about 1.06 s/step at batch 8, so 30k steps take ~8 h: run it
overnight. Set `PYTORCH_ENABLE_MPS_FALLBACK=1`, use fp32 (no AMP/bf16, no `torch.compile`).
Resume a cut run with `lerobot-train --config_path=<output_dir>/checkpoints/last/pretrained_model/train_config.json --resume=true`.

**Cloud (Brev, 2x H100):** the published models were trained this way, one variant per GPU at
~6.3 steps/s: 40,000 steps, batch 32, ~1 h 45, checkpoint to the Hub every 10,000 steps.
`train_pair.sh` and `resume.sh` run **on the Brev machine** and read the Hugging Face token from
that machine's cache (log in there with `hf auth login`); no secret is in the repo.

| Script | Purpose |
|---|---|
| `scripts/brev/train_pair.sh <dataset> <prefix>` | installs lerobot at `e595b79`, trains two ACT policies in parallel: `act-<prefix>-c100` (chunk 100) and `act-<prefix>-c50` (`chunk_size` = `n_action_steps` = 50). `HF_USER` sets the Hub account. Writes `~/DONE-<variant>` / `~/FAILED-<variant>` and `~/TRAIN_DONE` |
| `scripts/brev/resume.sh <src repo> <step> <total steps> <new repo>` | 1-GPU machine: resumes a policy from a Hub checkpoint (optimizer state included) to more steps and pushes it to a new repo. Writes `~/DONE` / `~/FAILED` |
| `scripts/brev/watch_one.sh <host> <repo> <final step>` | from your laptop: waits for `DONE`/`FAILED` over ssh and deletes the machine **only after the final checkpoint is verified on the Hub**. Needs the `brev` CLI; `PYTHON` points to a Python with `huggingface_hub` |

```bash
# upload with ssh (scp reported OK but the file never reached ~ on Brev)
ssh <host> 'cat > ~/train_pair.sh' < scripts/brev/train_pair.sh
ssh <host> 'chmod +x ~/train_pair.sh && tmux new -d -s train "~/train_pair.sh <user>/smartseed-grasp-<colour> smartseed-d1"'
ssh <host> 'tmux ls; tail -5 ~/setup.log'      # confirm it really started
scripts/brev/watch_one.sh <host> <user>/act-smartseed-d1-c100 40000

# resume 40k -> 80k from the Hub checkpoint
ssh <host> 'cat > ~/resume.sh' < scripts/brev/resume.sh
ssh <host> 'chmod +x ~/resume.sh && tmux new -d -s train "~/resume.sh <user>/act-smartseed-d1-c100 <step> 80000 <user>/act-smartseed-d1-c100-80k"'
```

(`<step>` is the folder name under `checkpoints/` in the model repo, exactly as listed there.)

## Models & datasets

All under <https://huggingface.co/RafaelJaime>, tagged `BraboRobots`. Collection:
<https://huggingface.co/collections/RafaelJaime/smartseed-so-101-act-seed-sowing-6adf0632f7e93bb112d73e8c>

**Models (ACT policies)**

| Model | Trained on | Chunk | Steps | Notes |
|---|---|---|---|---|
| [`act-smartseed-d1-c100`](https://huggingface.co/RafaelJaime/act-smartseed-d1-c100) | d1-clean | 100 | 40k | **default for black** (Tomate) |
| [`act-smartseed-d2-c100`](https://huggingface.co/RafaelJaime/act-smartseed-d2-c100) | d2-clean | 100 | 40k | **default for white** (Pimiento) |
| [`act-smartseed-d1-c50`](https://huggingface.co/RafaelJaime/act-smartseed-d1-c50) | d1-clean | 50 | 40k | shorter chunk |
| [`act-smartseed-d2-c50`](https://huggingface.co/RafaelJaime/act-smartseed-d2-c50) | d2-clean | 50 | 40k | shorter chunk |
| [`act-smartseed-d1-c100-80k`](https://huggingface.co/RafaelJaime/act-smartseed-d1-c100-80k) | d1-clean | 100 | 80k | `d1-c100` resumed 40k→80k; checkpoints 50k-80k |
| [`act-smartseed-grasp-merged`](https://huggingface.co/RafaelJaime/act-smartseed-grasp-merged) | merged grasp data | n/a | 100k | earlier single-policy iteration |
| [`act-smartseed-grasp`](https://huggingface.co/RafaelJaime/act-smartseed-grasp) | first grasp data | n/a | n/a | earlier iteration |

**Datasets** (task `grasp the seed below the gripper`, 10 s episodes, cleaned by hand)

| Dataset | Episodes | Origin |
|---|---|---|
| [`smartseed-grasp-d1-clean`](https://huggingface.co/datasets/RafaelJaime/smartseed-grasp-d1-clean) | 96 × 10 s | `smartseed-grasp-d_20261025_002427` without episodes 1, 15, 26, 34 |
| [`smartseed-grasp-d2-clean`](https://huggingface.co/datasets/RafaelJaime/smartseed-grasp-d2-clean) | 91 × 10 s | `smartseed-grasp-d_20261025_010641` without episodes 0-4, 18, 66, 84, 96 |

## Run

1. `scripts/stack.sh` (see Quick start). The web forces Tomate = `black` and Pimiento = `white`
   on load. For other policies: `SMARTSEED_ACT_POLICIES='{"<colour>":"<repo>"}' scripts/stack.sh`.
2. Open `http://localhost:8080/`, **Escanear**, calibrate and teach poses if you have not yet
   (see setup), then **Bloquear brazo**.
3. Scan the tray, assign seeds to cells, press **Sembrar**. Detection freezes while sowing and
   resumes when the run ends, fails or is stopped. Seeds are user-defined in the UI (name, emoji,
   box colour); `Cell.color` accepts any `^[a-z][a-z_-]{0,19}$`, and a colour with no policy or
   taught poses is refused with `409`.
4. **Parar** (`POST /stop`) cuts the sequence; the arm **stays in place with torque on**. Use
   `POST /robot/torque-off` only when it is somewhere safe.

The **Ajustes** (gear) panel adds debugging tools: drop height (`drop_z`, default 6 cm), *Probar
coger* (grasp half only, `mode: "grasp"`), *Probar dejar* (place half only, `mode: "place"`, no
policy needed) and the **ACT model/checkpoint selector** (applies on the next run, no restart).
If a grasp comes out empty the arm still goes to the cell, opens and continues; the cell counts
as done and the UI warns the gripper looked empty.

**Drop placement.** IK prefers a vertical gripper and otherwise tilts it outward in 15° steps.
The tip approaches 8 cm above the cell; because servos sag with the arm extended, the executor
measures the tip with forward kinematics and re-aims until it is within 5 mm (up to 2
corrections), then tilts the wrist +5° and opens. The final error travels in the WS event
`drop_pose` (`target`, `reached`, `error_mm`, `corrections`).

### API (backend, `127.0.0.1:8000`)

| Endpoint | Purpose |
|---|---|
| `GET /health` | service status and whether models are loaded |
| `POST /vision/tray` | frame → corners, rows × cols, holes and which are occupied. Optional `tray_hint` (previous corners) skips OWLv2 and searches around it (`source: "hint"`) |
| `GET /robot/status` | executor state, torque, poses, calibration, cameras, colours with a policy |
| `GET /robot/joints` | joint angles and tool position (forward kinematics) |
| `GET /robot/poses` · `POST /robot/poses/{name}` | list / teach poses |
| `POST /robot/goto/{name}` | move to a taught pose |
| `POST /robot/calibration/points` · `/fit` · `DELETE …/points` | camera-robot calibration and its error in mm |
| `POST /robot/torque-on` · `/robot/torque-off` | enable / release motors |
| `GET /robot/act/models` · `POST /robot/act/select` | Hub ACT catalog with checkpoints; hot-swap a colour's policy (`409 busy`, `422` unknown, `502` download failed) |
| `POST /plan` · `POST /stop` | sow a plan (optional `mode`, `drop_z`) / stop it |
| `WS /robot/progress` | cell-by-cell progress (late clients get the history) |

`POST /plan` is validated entirely before any motor moves and refused with a code
(`unreachable`, `no_calibration`, `missing_pose`, `torque_off`, `busy`). Body: `image_size` plus a
list of `{cell_index,row,col,color,u,v}`.

## Tests

No hardware needed: a fake robot and synthetic trays/depth maps stand in.

```bash
cd backend && uv run pytest             # vision, kinematics, calibration, ACT, executor, API
cd tests/web && npm install && npm test # UI smoke tests in jsdom: demo mode, then stubbed robot
CHROME_PATH=".../Google Chrome" npm run render   # real Chromium, desktop and phone sizes
CHROME_PATH=".../Google Chrome" npm run camera   # synthetic webcam: scan flow
```

Tests never download a model or open a serial port. The smoke tests assert some Spanish UI
strings; that is expected. Details: [guide.md](guide.md#automated-tests).

## Known issues and lessons

- **USB camera drop**: lerobot's camera read thread can die for good mid-run. The ACT loop now
  checks the cameras, reopens them (3 attempts, 0.5 s / 1.0 s backoff) and retries once; if that
  fails the run ends with `camera_unavailable` ("check the USB" in the UI).
- **`act_start` mismatch**: the taught `act_start` had `wrist_flex` ≈ 72° while the d1/d2 episodes
  start near 47°. If the policy hesitates at the start, compare these two first.
- **Brev**: upload scripts with `ssh host 'cat > ~/f' < f` (scp silently failed), confirm `tmux`
  and the log after launching, and let `watch_one.sh` delete the machine.
- **MPS throughput**: ~1.06 s/step at batch 8 on an M-series Mac; train long runs overnight.
  All model inference shares one lock because two threads on MPS at once abort the process.
- **Servo sag**: with the arm stretched the servos give under gravity; that is why the drop is
  corrected in closed loop.
- **macOS camera permission** goes to the launching app (Terminal.app / VS Code, not other
  wrappers).
- **GitHub Pages** is set to deploy from `main`, so every push publishes the whole repo: never
  commit secrets. `.github/workflows/pages.yml` is an older, competing deployment of `web/` only.
- **No LICENSE file yet**: the owner has not chosen one, so reuse terms are undefined.

## Safety

The published web never controls the robot. Only the local backend on the laptop connected to
the arm sends motion. Keep the follower's power cable at hand the first time you test any change.

## Credits

Team **BraboRobots**. Repository: <https://github.com/alvaromoli13/Robotluces>. Policies and
datasets: <https://huggingface.co/RafaelJaime>. Built on [LeRobot](https://github.com/huggingface/lerobot)
(Hugging Face) and the SO-101 arm design; OWLv2 and Depth Anything V2 for vision; js-aruco2
vendored in `web/vendor/`; DM Sans and Manrope fonts (`web/fonts/LICENSE.txt`).
