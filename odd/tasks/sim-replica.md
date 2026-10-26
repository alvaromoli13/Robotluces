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
- [ ] T3 Run the real-trained ACT in sim and save a video per policy (route: delegated)
- [ ] T4 Scripted IK grasp demos -> LeRobotDataset (randomised seed/box positions, lighting) (route: delegated)
- [ ] T5 Train ACT on sim demos + `sim/eval.py` success metric (seed lifted > 3 cm, lands in target hole) (route: delegated)

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
