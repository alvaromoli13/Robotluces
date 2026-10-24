# Feature: ACT grasp in the executor (full web → robot loop)

## Objective
"Sembrar" in the web plants the tray with the trained ACT policies: for each cell, the
colour's ACT policy picks a seed from its bowl and comes back, then IK carries it to the cell
and drops it.

## Problem / why
`RafaelJaime/act-smartseed-grasp` is trained (20k steps, 50 eps). The executor only knows
`TaughtGrasp` with taught above-box poses. Deadline Sunday 2026-10-25 13:00.

## Evidence from the datasets
- Episodes start near rest `[1, -103, 97, 48, -6, 6]` (pan, lift, elbow, wrist_flex, roll,
  gripper) and end back near rest with the seed held (gripper ~7). So the policy runs
  start pose → bowl → grasp → back; no above-box pose needed.
- Policy inputs: `observation.state` (6), `observation.images.top` and
  `observation.images.wrist` (3×480×640). ACT chunk 100, n_action_steps 100. Episodes 10 s.
- Second dataset `RafaelJaime/smartseed-grasp-2_20261024_151659` (46 eps, some failed, not
  trained yet) = second colour.

## Scope
- `ActGrasp` grasper: per colour policy repo (env `SMARTSEED_ACT_POLICIES` JSON
  `{"<color>": "<repo or path>"}`), move to taught `act_start` pose (fallback: episode-start
  mean), run policy at 30 Hz for `duration_s` (10 s default) reading both cameras, stop event
  checked every step. Gripper stays as the policy left it (closed) while moving to the cell.
- Executor sequence with ActGrasp: act_start → ACT pick → IK above cell → open → act_start.
- Real mode opens cameras top/wrist (env `SMARTSEED_CAM_TOP`, `SMARTSEED_CAM_WRIST`,
  640×480@30) only when ACT is configured. Fake mode never touches hardware.
- Docs: README "Ejecutor del robot" section.

## Constraints
- Writers never move the real robot. Hardware runs are with the user.
- Camera access must run from Terminal.app/VS Code (Unpeel has no camera permission).
- Same follower id `follower_01`, lerobot pinned e595b79.

## TDD
Strict TDD (user config). Runner: `~/.claude/bin/testsem -- 'cd backend && uv run pytest'`.

## Tasks
- [ ] T1 Standalone policy check on the real arm with `scripts/30_rollout.sh hub`
      (`DURATION=12`). Route: inline with the user.
- [x] T2 ActGrasp + executor sequence + env wiring + cameras, fake policy tests.
      Route: delegated writer (2+ non-trivial files).
- [ ] T3 Full loop with the user: real server, web Sembrar, one cell, then a full tray.
- [ ] T4 Second policy (clean dataset 2, train, add to `SMARTSEED_ACT_POLICIES`).

## Acceptance criteria
- With FakeRobot + fake policy, a plan runs act_start → N policy steps → IK cell → open →
  act_start per cell, emits progress events and stops within one control step.
- Colour without a configured policy is rejected by `/plan` (or falls back to TaughtGrasp if
  that colour has taught poses).

## Progress / evidence
- Model on Hub: tags incl. BraboRobots, checkpoints 5k/10k/15k/20k. Brev box deleted.

- T2 done (commit 189874c). Route: delegated writer. Strict TDD: RED = `ModuleNotFoundError: No
  module named 'smartseed_robot.act'` on the new tests; GREEN = `169 passed` (full backend
  suite via testsem). `import smartseed_robot.act` and the lerobot entry points (`predict_action`,
  `make_pre_post_processors`, `OpenCVCameraConfig`, `build_dataset_frame`) resolve with real
  lerobot. Not run on hardware: real policy load, cameras and `LeRobotFollower.read_observation`.
- Notes: no empty-grasp check on the ACT path (policy keeps gripper ~7 vs `empty_below` 8);
  placo IK is order-dependent across tests, so the ACT test uses the central cell.

## Next step
T1/T3 on the real arm with the user: run the server from Terminal.app (README "Sembrar con policy ACT").
