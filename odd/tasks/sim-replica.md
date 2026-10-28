# Simulated replica of the SmartSeed scene

## Objective
Replicate the real SmartSeed scene (SO-101, mat, 3x4 tray, black/white seed boxes, seeds, top + wrist cameras)
in MuJoCo, watch our ACT policies act in it, and generate simulated demos to retrain ACT.

## Problem / why
After the hackathon there is no arm at hand. A simulated twin lets anyone replay, evaluate and retrain the
grasp policy without hardware. Plan and research: `docs/simulation.md`.

## Scope
- MuJoCo (runs on Apple Silicon), SO-101 new-calib MJCF from TheRobotStudio SO-ARM100 (Apache-2.0).
- `SimRobot` implementing the backend `RobotPort` contract so the executor and the web drive the sim arm
  unchanged (`SMARTSEED_ROBOT=sim`).
- Scripted IK demos recorded as a LeRobotDataset with the same keys/fps as the real datasets; ACT training reuses
  `scripts/brev/` and `lerobot/`.
- Constraints: real-robot paths unchanged; tests hardware-free; no real-arm commands.

## TDD
Strict TDD (session config). Runner: `cd backend && uv run pytest` (via `~/.claude/bin/testsem --`); web: `cd tests/web && npm test`.

## Tasks
- [x] T1 Scene: MJCF with arm, mat, tray, boxes, seeds; top + wrist cameras at 640x480 matched to the real
      frames; joint mapping (deg, gripper 0-100) verified by replaying a recorded episode (route: delegated)
      Evidence: replay of episode 0: tool vs FK 0.0016 mm max; top overlay chamfer 5.5 px; `sim/README.md`
- [x] T2 `SimRobot(RobotPort)` + `SMARTSEED_ROBOT=sim` + viewer/recording of runs (route: delegated, same writer)
      Evidence: `uv run pytest` 297 passed (sim tests included, mujoco in default uv group); web `npm test` 196/196; a `place` plan runs through the executor on the sim arm (tool within 3 mm of target) and writes an mp4
- [x] T2b Contact-physics grasp: jaws close on a seed and hold it while lifting (real-like stop at gripper ~7),
      no weld/attach trick; the user chose physics tuning over attach (route: delegated)
      Evidence: `sim/grasp_test.py` 100/100 black, 100/100 white (+-3 mm, readings 6.88 / 7.44 vs real 6.93 / 7.37); recorded ep0 actions lift the seed; `uv run pytest` 310 passed (RED first: 9 of 11 new tests failed on the old scene). Real readings are ~7, not 12: the jaw stop is a hard stop. Weak: black seed 3 0/20
- [x] T3 Run the real-trained ACT in sim and save a video per policy (route: delegated)
      Evidence: `sim/run_policy.py` (stub-policy tests, RED first); 40 episodes: d1-c100 0/10, d1-c100-80k 1/10 (a real
      grasp-and-lift to 11.5 cm held 0.8 s, then dropped), d2-c100 0/10, d2-c50 0/10; policies reach the right box but do not close
      on a seed; table, videos, `docs/media/sim-vs-real-obs.png` in `sim/README.md`. Side fix: `shoulder_lift` range widened to -103
- [x] T4 Scripted IK grasp demos -> LeRobotDataset (randomised seed/box positions, lighting) (route: delegated)
      Evidence: `sim/make_dataset.py`; RED first (ImportError on `sim.make_dataset`, later the box-yaw `geom_xmat` test
      caught MuJoCo ignoring runtime `geom_quat`); 100 episodes per colour kept of 132 (black) / 136 (white) attempts
      (generator success 75.8 % / 73.5 %), 29,497 / 29,502 frames; scope change: boxes, tray and seeds anywhere in the top
      view (placement: geometry 1.95 % / 1.77 % of drawn objects, planner reaches 29 % / 28.5 % of valid scenes). Hub:
      `RafaelJaime/smartseed-sim-grasp-black` and `-white` (v1, public at the time, later withdrawn and deleted: the
      gripper passed through walls, see T4b; BraboRobots, were in the HF collection); features identical to real d1/d2 `info.json` (checked from the Hub), `docs/media/sim-dataset-preview.png`,
      `docs/media/sim-dataset-coverage.png`. Commits: 5e748db, 5472152 and the docs commit after it.
- [x] T4b Collision-correct demos (reopens T4): the user saw the jaw pass through a seed-box wall (episode 0). Cause:
      the moving jaw hull has `contype="0"` and the pads only touch seeds, and the planner never checks walls. Make every
      jaw geom collide with box/tray walls (not the floors), make the planner choose a jaw yaw/approach that clears walls
      or redraw the scene, and discard any episode in which an arm geom penetrates a wall; regenerate both datasets as
      `-v2` Hub repos (route: delegated)
      Evidence: RED first (ImportError on `sim.collision`; 7 physics tests failed on the old scene; a pose with the tool
      inside a moved wall gave no contact). Found on the way: MuJoCo's static broad phase ignores runtime `geom_pos`
      edits, so in v1 moved boxes/tray had no wall collisions at all; boxes and tray are now bodies moved via `body_pos`.
      Walls get their own bit (`wall` class, conaffinity 19), jaw hull contype 16, pads 24: every jaw geom stops at walls
      (30-40 N push, 0.4 mm penetration), floors unchanged. `sim/collision.py` monitors arm-wall contacts per physics step
      (valid = max penetration <= 1 mm and force <= 2 N). Planner: 25 jaw axes, swept forward-kinematics check of the whole
      motion (5 mm in the grasp, 2 cm in transit), `NoFit` redraws the scene. `sim/audit_walls.py` on the v1 datasets: 24 % of
      the black and 37 % of the white kept episodes have an arm geom > 1 mm in a wall (max 22 / 25 mm; 4 % / 9 % in the grasp, the
      rest the folded arm or the transit); the v2 planner redraws 58 of those 61 scenes. v2: black 114 attempts / 100 kept,
      white 112 / 100; 0 collision rejections, 543 / 666 placement rejections (204 / 269 no fit); audit of the 200 kept: 0 overlaps.
      Hub: https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v2 and `-white-v2` (public, BraboRobots, features
      identical to real `info.json`, 100 episodes, 29,503 / 29,508 frames; reloaded from the Hub); the HF collection now lists v2
      and not v1 (v1 repos since withdrawn and deleted). `grasp_test.py`: seed 2 20/20 both colours and every other seed unchanged except
      black seed 0 20/20 -> 0/20 (13 mm from a wall: v1 flew the jaw through it). `uv run pytest` 380 passed (was 350).
      Media: `docs/media/sim-wall-check.png`, regenerated `sim-dataset-preview.png`, `sim-dataset-coverage.png`; mp4 of 5 episodes per
      colour in `sim/out/v2_videos/` (gitignored).
- [x] T4c Brev hardening after the 2026-10-27 failed run (box idle ~2.5 h): fix root-owned `~/.cache` on hyperstack,
      watcher deletes the box on setup failure or stalled training, check the Brev session before delete (route: inline)
      Evidence: `scripts/brev/launch_two.sh` (chown cache before the token, upload check, tmux check), `train_two.sh`
      (cache chown, EXIT trap writes FAILED-setup + TRAIN_DONE), `watch_pair.sh` (deletes on setup failure, failed run,
      no step in 40 min, step stalled 20 min, unreachable 10 min; exit 3 LOGIN NEEDED if the Brev session expired; saves
      logs to ~/brev-logs). Watcher paths exercised with fake ssh/brev: setup failed, logged out, run failed, no step,
      stalled -> all delete except logged out (exit 3). shellcheck clean on the three scripts.
- [ ] T5 Train ACT on sim demos + `sim/eval.py` success metric (seed lifted > 3 cm, lands in target hole) (route: delegated)
      To train on Brev (do not start it from this task), use the `-v2` datasets (v1 had wall pass-through) and
      `scripts/brev/train_two.sh` on a 2-GPU box, one ACT (chunk 100, 40k steps, batch 32) per GPU: `scripts/brev/launch_two.sh <host>
      RafaelJaime/smartseed-sim-grasp-black-v2 sim-black RafaelJaime/smartseed-sim-grasp-white-v2 sim-white` (it uploads the script with
      `ssh ... 'cat >'`, not scp, and starts tmux; the models are pushed as `RafaelJaime/act-sim-black` / `act-sim-white`), then
      `PYTHON=backend/.venv/bin/python scripts/brev/watch_pair.sh <host> RafaelJaime/act-sim-black RafaelJaime/act-sim-white`.
- [ ] T5b Withdraw the v1 links and add a narrow layout mode (route: delegated). The v1 Hub datasets
      `smartseed-sim-grasp-black` / `-white` were deleted by the user; remove every link to them (README, sim/README,
      docs/simulation.md, this file, `dataset_card()` + its test) and say v1 was withdrawn because the gripper passed through
      walls, regenerable from git history (commit before a279c23); re-upload the README of the two v2 Hub repos. Add
      `--layout narrow` to `sim/make_dataset.py` and `sim/eval.py`: boxes and tray near their nominal positions, yaw within
      +-30 deg, ranges chosen from the planner acceptance rate, all T4b wall rules kept.
- [ ] T5c Generate 300 kept episodes per colour in narrow mode and publish them as `-v3-narrow` Hub repos (public, in the HF
      collection), measure the scripted planner's success on held-out narrow scenes (the ceiling), 3 mp4 per colour in
      `sim/out/v3_videos/`, coverage png in `docs/media`, docs. Next step (NOT started here): train on Brev with
      `scripts/brev/launch_two.sh <host> RafaelJaime/smartseed-sim-grasp-black-v3-narrow sim-black-narrow-c100
      RafaelJaime/smartseed-sim-grasp-white-v3-narrow sim-white-narrow-c100`, then `sim/eval.py --layout narrow`.

## Acceptance
- `SMARTSEED_ROBOT=sim ./scripts/stack.sh` runs the web + executor against the simulated arm.
- Replay of a real episode in sim lines up with the real top-camera frames (overlay image saved).
- A sim dataset on the Hub trains an ACT that reaches a measured success rate in sim.

## Progress
- 2026-10-26: created; research summarised in `docs/simulation.md`.
- 2026-10-26: T1+T2 done by one delegated writer (trigger: 2+ non-trivial files plus reading to prepare the write).
  Strict TDD: tests first (RED: ImportError on `sim.layout`/`sim_robot`, executor hook tests failing), then GREEN.
  Limits: jaw grasp physics is weak (seed not held), real calibration clicks disagree with the arm-fitted camera, servo
  gains untuned. Details in `sim/README.md`. Commits: see `git log` (feat(sim) scene+SimRobot, docs).
- 2026-10-27: T2b done (pads, servo and seed tuning, `Kinematics.solve(spin_deg)`); details in `sim/README.md`.
- 2026-10-27: T3 done: real ACT policies run in the twin (1/40 episodes lifted a seed); see `sim/README.md`.
- 2026-10-27: T4 done: 100 sim episodes per colour on the Hub; see `sim/README.md`, "Generating sim datasets".
- 2026-10-27: T4b done: jaws collide with walls, wall-aware planner, wall monitor, v2 datasets on the Hub; see `sim/README.md`, "Collision model (T4b)".
- 2026-10-28: T5 partial (task stays open): `sim/eval.py` (RED first) measures 20 held-out scenes (seed 1000), success = seed
  lifted > 3 cm (no target-hole check: the demos never place the seed). ACT c100 40k: black 1/20 held-out (12/20 on training
  scenes), white 2/20 (4/20); checkpoint 020000 1/20 and 1/20. Observation path verified identical to the dataset (no mismatch);
  the 0/10 of `run_policy.py` came from the single nominal scene. Cause: too few demos for the layout diversity; recommendation in
  `sim/README.md`, "Evaluating sim-trained policies (T5)".
