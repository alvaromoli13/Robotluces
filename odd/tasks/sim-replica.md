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
      https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black and `-white` (public, BraboRobots, in the HF
      collection); features identical to real d1/d2 `info.json` (checked from the Hub), `docs/media/sim-dataset-preview.png`,
      `docs/media/sim-dataset-coverage.png`. Commits: 5e748db, 5472152 and the docs commit after it.
- [ ] T5 Train ACT on sim demos + `sim/eval.py` success metric (seed lifted > 3 cm, lands in target hole) (route: delegated)
      To train on Brev (do not start it from this task): upload with `ssh <host> 'cat > ~/train_pair.sh' < scripts/brev/train_pair.sh`
      (not scp), then per colour `ssh <host> 'chmod +x ~/train_pair.sh && tmux new -d -s train "~/train_pair.sh RafaelJaime/smartseed-sim-grasp-black sim-black"'`
      (and `.../smartseed-sim-grasp-white sim-white`); it trains `act-sim-black-c100` / `-c50` (40k steps, batch 32, one per GPU)
      and pushes them under `RafaelJaime`; check `tmux ls; tail -5 ~/setup.log`, then `scripts/brev/watch_one.sh <host> RafaelJaime/act-sim-black-c100 40000`.

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
