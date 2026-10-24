# Feature: robot executor in the backend

## Objective
Let the local backend plant a tray: receive the plan from the web, move the SO-101 follower
to each box and cell, grasp, drop, report progress and stop safely.

## Problem / why
The backend only does vision (`/vision/tray`). Nothing moves the robot. Deadline Sunday
2026-10-25 13:00; started Saturday 09:30.

## Scope
- New package `backend/smartseed_robot/` in the existing uv project (`backend/`).
  - `robot.py`: `RobotPort` protocol (read joints, send joints, torque off) with a
    `FakeRobot` (tests, dry runs) and a `LeRobotFollower` adapter over lerobot
    `SO101Follower` (port, id `follower_01`, `max_relative_target` set, degrees).
  - `kinematics.py`: wrapper over `lerobot.model.kinematics.RobotKinematics` with the SO-101
    URDF `so101_new_calib.urdf` (TheRobotStudio/SO-ARM100) vendored in `backend/assets/`.
  - `calibration.py`: pixel → robot (x, y) homography from ≥4 pairs, saved to JSON.
  - `poses.py`: named taught joint poses (home, above_box_red/yellow/green/purple), JSON.
  - `motion.py`: joint-space interpolation at ~30 Hz, cancellable.
  - `executor.py`: planting sequence per cell (home → above box → grasp → lift → above cell
    via IK → open → home), gripper check with one retry, stop event, progress events.
    Grasp step behind a `Grasper` interface: `TaughtGrasp` now, `ActGrasp` (lerobot ACT
    policy) later.
  - API on the same FastAPI app: `POST /plan`, `POST /stop`, `GET /robot/status`,
    `WS /robot/progress`, `GET /robot/joints`, `POST /robot/poses/{name}` (teach from current
    joints), `POST /robot/calibration/points` + `POST /robot/calibration/fit`.
- Robot backend selected by env: `SMARTSEED_ROBOT=fake` (default) or `real` with
  `SMARTSEED_ROBOT_PORT`. Default never touches hardware.
- Docs: README + CLAUDE.md (how to teach poses, calibrate, run a plan, stop).

Out of scope for now: web "Sembrar" wiring (T5), ACT grasp (T6), real-tray tuning.

## Constraints
- Writers must **not move the real robot**; hardware steps are run with the user.
- Same follower id `follower_01` and calibration as recording/rollout.
- Dependency on lerobot pinned to the same version as `vendor/lerobot` (0.6.2, commit
  e595b79) with extras `feetech,kinematics`; transformers must stay compatible
  (lerobot wants >=5.4,<5.6).

## TDD
- Mode: strict TDD enabled (user global config). Runner: `uv run pytest` in `backend/`,
  wrapped with `~/.claude/bin/testsem --`.

## Tasks
- [x] T1 Robot core: dependency + URDF, RobotPort/FakeRobot/LeRobotFollower, kinematics,
      calibration, poses, motion, executor with fake robot; tests. Route: delegated writer.
- [x] T2 API endpoints + progress WebSocket + env-selected robot; tests. Route: same writer.
- [ ] T3 Hardware check with the user: FK vs real arm, teach home + 4 box poses. Route: inline.
- [ ] T4 Camera-robot calibration with the user + 10-cell drop test. Route: inline.
- [ ] T5 Web "Sembrar" → `POST /plan` with cell pixel centres + progress view.
- [ ] T6 ACT grasp once a policy exists.

## Acceptance criteria
- With `FakeRobot`, a plan of N cells produces the expected sequence of joint targets,
  progress events per cell, one retry on an empty grasp, and stops within one control step.
- IK target for a known FK pose round-trips within a few mm.
- Default config cannot open a serial port.

## Progress / evidence
- T1 (c7b96bb): RED = collection error `No module named smartseed_robot`; GREEN = 54 passed (robot, motion,
  kinematics round trip <3 mm, calibration, poses, executor). Dependency: lerobot@e595b79 [feetech,kinematics],
  transformers pinned 5.5.4 (>=5.4,<5.6), torch index override for macOS; URDF + STL vendored (SOURCE.md).
- T2 (579a523): RED = `No module named smartseed_robot.api`; GREEN = full suite 126 passed (vision included).
- Dry run (uvicorn + fake robot, API-fitted calibration, poses.json pre-seeded): POST /plan 202, 3 cells
  events plan_started/cell_started/cell_done x3/finished; second plan: busy 409 code=busy, POST /stop ->
  stopped event, state idle. Contract (status/plan/ws shapes) covered by tests/test_robot_api.py.
- Finding: straight-down approach reaches only ~0.28 m radius at z=0.05-0.08 m; default drop_z 0.06.

## Next step
T3 with the user: FK check, teach home + 4 box poses (README "Ejecutor del robot").
