<p align="center">
  <img src="docs/media/smartseed-logo.svg" alt="SmartSeed" width="420">
</p>

<p align="center">
  <a href="https://huggingface.co/collections/RafaelJaime/smartseed-so-101-act-seed-sowing-6adf0632f7e93bb112d73e8c"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-models%20%26%20datasets-ffcc4d.svg" alt="Hugging Face collection"></a>
  <a href="docs/media/smartseed-video.mp4"><img src="https://img.shields.io/badge/%E2%96%B6-project%20video-197647.svg" alt="Project video"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="docs/media/smartseed-video.mp4"><img src="docs/media/smartseed-video.gif" alt="SmartSeed project video" width="720"></a><br>
  <sub>🔇 Silent preview · ▶ <a href="docs/media/smartseed-video.mp4">watch with sound</a> (46 s, Spanish audio) ·
  🤗 <a href="https://huggingface.co/collections/RafaelJaime/smartseed-so-101-act-seed-sowing-6adf0632f7e93bb112d73e8c">All models and datasets on Hugging Face</a></sub>
</p>

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

### LeRobot toolchain (`lerobot/`)

Everything that talks to the arm outside the web app (find ports and cameras, calibrate,
teleoperate, record, train, standalone rollout) is wrapped in small scripts in
[`lerobot/`](lerobot/), with `make` shortcuts. It has its **own** venv (`lerobot/.venv`, separate
from `backend/.venv`) with lerobot checked out at the same pinned commit `e595b79`
(`LEROBOT_REF` overrides it). Run everything from that folder.

```bash
cd lerobot
cp .env.example .env     # git-ignored; ports, camera ids, task, training settings
make install             # uv + Python 3.12 + ffmpeg + lerobot into lerobot/.venv (macOS arm64)
source .venv/bin/activate && hf auth login   # token with WRITE permission
make verify              # PASS/WARN/FAIL environment check
make prefetch            # optional: pre-download weights and the example dataset
make smoke               # 50 ACT steps on a public dataset, no robot
make help                # every target
```

`.env` is read by `scripts/lib.sh`; a variable given on the command line wins over `.env`
(`TASK_NAME=smartseed-grasp-white ./scripts/11_record.sh`). Ports, camera ids and `HF_USER` are
placeholders or auto-detected (`HF_USER` comes from `hf auth whoami` when empty).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SMARTSEED_ROBOT` | `fake` (`real` in `scripts/stack.sh`) | `fake` opens no serial port or camera; `real` moves the arm; `sim` drives the MuJoCo twin of the arm and scene (see [Simulator](#simulator-no-arm-needed)) |
| `SMARTSEED_ROBOT_PORT` | none (event port in `stack.sh`) | follower serial port, required when `real`. Find yours: `ls /dev/tty.usbmodem*` (macOS) or `/dev/ttyACM*` (Linux), unplug/replug the follower to see which entry changes |
| `SMARTSEED_ACT_POLICIES` | empty (no ACT) | JSON `{"<colour>": "<HF repo or local path>"}`, e.g. `{"black":"RafaelJaime/act-smartseed-d1-c100","white":"RafaelJaime/act-smartseed-d2-c100"}` |
| `SMARTSEED_ACT_DURATION_S` | `10` | seconds of policy per cell (match the episode length used for training) |
| `SMARTSEED_ACT_DEBUG_DIR` | none | if set, the ACT loop logs timing and first frames there |
| `SMARTSEED_CAM_TOP` / `SMARTSEED_CAM_WRIST` | `0` / `1` | OpenCV index or path of each camera |
| `SMARTSEED_POLICY_DEVICE` | `mps` if available, else `cpu` | inference device |
| `SMARTSEED_DATA_DIR` | `backend/data/` (`sim/config/` when `sim`) | where `poses.json` and `calibration.json` live (git-ignored) |
| `SMARTSEED_SIM_VIEWER` | none | `1` opens the live MuJoCo window in `sim` mode (macOS: `backend/run.sh` then uses `mjpython`) |
| `SMARTSEED_SIM_RECORD_DIR` | none | in `sim` mode, saves one `plan-<id>.mp4` of the top camera per plan there |
| `SMARTSEED_SIM_SCENE` | `sim/scene.xml` | alternative MJCF scene for `sim` mode |
| `SMARTSEED_DISABLE_MODEL` | none | `1` skips OWLv2 and depth (contour only), for quick tests |
| `SMARTSEED_WEB_PORT` | `8080` | web port used by `scripts/stack.sh` |

## Simulator (no arm needed)

`SMARTSEED_ROBOT=sim` replaces the arm with a MuJoCo replica of the arm, mat, tray, seed boxes and the `top` and
`wrist` cameras (`sim/`, details and accuracy in `sim/README.md`). The executor, the ACT loop and the web run
unchanged against it. Works on Apple Silicon and Linux, no GPU or display needed:

```bash
cd backend && uv sync                          # installs the `sim` group (mujoco, imageio) by default
SMARTSEED_ROBOT=sim SMARTSEED_SIM_RECORD_DIR=/tmp/smartseed-sim ./run.sh   # backend on 127.0.0.1:8000
SMARTSEED_ROBOT=sim ../scripts/stack.sh        # same, plus the web on :8080 (add SMARTSEED_ACT_POLICIES=... for ACT)
SMARTSEED_ROBOT=sim SMARTSEED_SIM_VIEWER=1 ./run.sh                        # live MuJoCo window (macOS: mjpython)
```

Without `SMARTSEED_DATA_DIR` it uses the committed `sim/config/` (a camera-robot calibration made from the sim
camera plus the real `home`/`act_start` poses), so a fresh clone can run it. Calibrating in the web in this mode
rewrites those files.

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

1. **Find ports and cameras, then calibrate the arms** (from `lerobot/`). Put the ports and camera
   ids in `.env`, and keep the **same id** everywhere (`FOLLOWER_ID=follower_01`, which is how the
   backend opens the follower; `LEADER_ID=leader_01` was used for recording). A different id means
   a different calibration file and policies will not transfer.
   ```bash
   make hardware                       # scripts/03_hardware.sh: serial ports (lerobot-find-port) + cameras
   make cameras                        # scripts/06_cameras.sh: live tiled view with OpenCV indices; q quits
   make calibrate                      # follower, then leader (lerobot-calibrate, ids from .env)
   # ./scripts/04_setup_motors.sh follower|leader   only for arms whose motor ids were never set
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
cd lerobot
make teleop                                            # leader -> follower with camera view: check calibration and framing
TASK_NAME=smartseed-grasp-black ./scripts/11_record.sh # dataset <HF_USER>/smartseed-grasp-black (lerobot adds a _stamp)
make replay                                            # replay episode 0 on the follower: mechanical repeatability test
```

`.env.example` already holds the values we used (`TASK_PROMPT="grasp the seed below the gripper"`,
100 episodes, 10 s episodes, 5 s reset, 640x480@30, our Hub tags). `scripts/11_record.sh` runs
`lerobot-record` with `--robot.cameras` generated by `build_cameras` in `scripts/lib.sh`, so
record and rollout always use the same camera names. Keys while recording: `n`/`->` next episode,
`r`/`<-` re-record, `q`/`Esc` finish and upload.

Camera names **must** be `top` and `wrist` (the backend feeds the policy
`observation.images.top` / `.wrist`). Stop the backend in `real` mode before recording: both
use the follower port. lerobot 0.6 appends a `_YYYYMMDD_HHMMSS` stamp to new dataset ids; to add
episodes, resume with the full stamped name:
`REPO=<user>/<name>_<YYYYMMDD_HHMMSS> RESUME=1 EPISODES=<how many more> ./scripts/11_record.sh`.

### Clean the recorded episodes

After watching the recording (<https://huggingface.co/spaces/lerobot/visualize_dataset>), bad
episodes were removed with lerobot's dataset edit tool, `lerobot-edit-dataset` with the
`delete_episodes` operation (present at the pinned commit `e595b79`, installed by `make install`).
It writes a **new** dataset with the remaining episodes re-indexed from 0 (videos and parquet
files are copied and re-indexed); indices are those of the *source* dataset.

```bash
# d1-clean: 100 episodes - [1, 15, 26, 34] = 96
lerobot-edit-dataset \
  --repo_id <user>/smartseed-grasp-d_20261025_002427 \
  --new_repo_id <user>/smartseed-grasp-d1-clean \
  --operation.type delete_episodes \
  --operation.episode_indices "[1, 15, 26, 34]" \
  --push_to_hub true

# d2-clean: 100 episodes - [0, 1, 2, 3, 4, 18, 66, 84, 96] = 91
lerobot-edit-dataset \
  --repo_id <user>/smartseed-grasp-d_20261025_010641 \
  --new_repo_id <user>/smartseed-grasp-d2-clean \
  --operation.type delete_episodes \
  --operation.episode_indices "[0, 1, 2, 3, 4, 18, 66, 84, 96]" \
  --push_to_hub true
```

The flags above were checked against `src/lerobot/scripts/lerobot_edit_dataset.py` at `e595b79`;
`--root` / `--new_root` select exact folders instead of `$HF_LEROBOT_HOME/<repo_id>`, and giving
the same `--repo_id` and `--new_repo_id` edits in place after making a backup. The tool also
supports `split`, `merge`, `remove_feature`, `modify_tasks` and more (`--help`). Both source
datasets have 100 episodes (`meta/info.json` on the Hub).

## Train

```bash
cd lerobot
TASK_NAME=smartseed-grasp-black make train   # lerobot-train on MPS; policy repo <HF_USER>/act-smartseed-grasp-black
RESUME=1 ./scripts/20_train_local.sh         # resume a cut run from checkpoints/last
make train-cloud                             # same CLI on Hugging Face Jobs GPUs (JOB_TARGET in .env, billed per second)
```

**Local (Apple Silicon, MPS):** `.env.example` sets `DEVICE=mps`, `BATCH_SIZE=8`, `STEPS=30000`.
That is about 1.06 s/step, so 30k steps take ~8 h: run it overnight. `scripts/20_train_local.sh`
sets `PYTORCH_ENABLE_MPS_FALLBACK=1` and stays in fp32 (no AMP/bf16, no `torch.compile`). Output
goes to `lerobot/outputs/train/act-<TASK_NAME>` and the last checkpoint is pushed to the Hub.
`make train-cloud` (`scripts/21_train_cloud.sh`) is the Hugging Face Jobs route; the published
models were trained on Brev instead (below).

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

**Datasets** (task `grasp the seed below the gripper`, 10 s episodes, cleaned with `lerobot-edit-dataset`, see [Record datasets](#record-datasets))

| Dataset | Episodes | Origin |
|---|---|---|
| [`smartseed-grasp-d1-clean`](https://huggingface.co/datasets/RafaelJaime/smartseed-grasp-d1-clean) | 96 × 10 s | `smartseed-grasp-d_20261025_002427` without episodes 1, 15, 26, 34 |
| [`smartseed-grasp-d2-clean`](https://huggingface.co/datasets/RafaelJaime/smartseed-grasp-d2-clean) | 91 × 10 s | `smartseed-grasp-d_20261025_010641` without episodes 0-4, 18, 66, 84, 96 |
| [`smartseed-sim-grasp-black-v2`](https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v2) | 100 × ~9.8 s (29,503 frames) | **simulated**, collision-valid (no arm geom more than 1 mm inside a wall): scripted demos in the MuJoCo twin, black seeds, randomised scenes, same schema as `d1-clean` (`sim/make_dataset.py`) |
| [`smartseed-sim-grasp-white-v2`](https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white-v2) | 100 × ~9.8 s (29,508 frames) | **simulated**, collision-valid: same for white seeds, same schema as `d2-clean` |
| [`smartseed-sim-grasp-black-v4-dart`](https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v4-dart) | 600 × ~9.8 s (176,997 frames) | **simulated**, narrow layout (boxes and tray within 3 cm / 30 deg of the real scene), DART recovery demos (4 deg noise), wall-valid, black seeds, schema of `d1-clean`. The arm could pass through the table in this version (v5 fixes it and replaces it on the Hub); the `-v3-narrow` datasets were removed from the Hub, regenerable from commit 3f392cc (`make_dataset.py --layout narrow --episodes 300`) |
| [`smartseed-sim-grasp-white-v4-dart`](https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white-v4-dart) | 600 × ~9.8 s (176,724 frames) | **simulated**, narrow layout, DART recovery demos, wall-valid, white seeds, schema of `d2-clean` |

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

**Rollout without the web app.** To watch a policy drive the arm on its own (no vision, no
sowing), from `lerobot/` with the backend stopped:

```bash
./scripts/30_rollout.sh RafaelJaime/act-smartseed-d1-c100   # Hub repo id or a local pretrained_model path
./scripts/30_rollout.sh                                     # local: outputs/train/act-<TASK_NAME>/checkpoints/last
DURATION=30 ./scripts/30_rollout.sh hub                     # <HF_USER>/act-<TASK_NAME> from the Hub
```

It runs `lerobot-rollout` with the same camera names as recording, `TASK_PROMPT`, and
`DURATION` seconds (default 60). Keep a hand on the follower's power cable.

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

## Simulation (roadmap)

Replicating the experiment in a simulator (MuJoCo with the SO-101 model, a `SimRobot` behind the
same `RobotPort`, scripted demos and evaluation) is planned but **not implemented**:
[docs/simulation.md](docs/simulation.md).

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

## Safety

The published web never controls the robot. Only the local backend on the laptop connected to
the arm sends motion. Keep the follower's power cable at hand the first time you test any change.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 BraboRobots (SmartSeed team). Third-party material
keeps its own terms: the SO-101 URDF and meshes (`backend/assets/so101/SOURCE.md`), js-aruco2
(`web/vendor/`) and the fonts (`web/fonts/LICENSE.txt`).

## Credits

Team **BraboRobots**. Repository: <https://github.com/alvaromoli13/Robotluces>. Policies and
datasets: <https://huggingface.co/RafaelJaime>. Built on [LeRobot](https://github.com/huggingface/lerobot)
(Hugging Face) and the SO-101 arm design; OWLv2 and Depth Anything V2 for vision; js-aruco2
vendored in `web/vendor/`; DM Sans and Manrope fonts (`web/fonts/LICENSE.txt`).
