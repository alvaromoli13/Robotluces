# Camera reconnect

## Objective
An ACT plan survives a USB camera glitch: the backend reopens the two lerobot cameras (top + wrist) itself, and if it cannot, the plan fails with a clear message.

## Problem / why
Observed twice on the real stack (2026-10-25): lerobot's `OpenCVCamera(N)` background thread logs `read failed (status=False)`, then `RuntimeError: ... exceeded maximum consecutive read failures.` and exits. The thread never restarts. From then on `robot.get_observation()` -> `cam.read_latest()` raises `read thread is not running`, `ActGrasp.run` propagates it, the executor ends in `error` ("RuntimeError: ...") at the first ACT cell. POST /plan still answers 202, the arm does not move. macOS shows the devices again; only a backend restart fixed it.

## Scope
- `robot.py`: `CameraUnavailable`; `RobotPort.cameras_ok()` / `reconnect_cameras()`; `LeRobotFollower` implements them (disconnect + connect each camera, bounded attempts, backoff); `FakeRobot` simulates a dead camera.
- `act.py`: check cameras before an ACT run and retry the observation once after a reconnect.
- `executor.py`: `CameraUnavailable` -> `error` event with `code: camera_unavailable`.
- `api.py`: `GET /robot/status` gains `cameras` (bool).
- `web/app.js` + `index.html` cache-bust: Spanish message for that code.
- Constraints: no hardware in tests, same camera config/indices, never touch the live stack.

## TDD
Strict TDD enabled (session config). Runners: `~/.claude/bin/testsem -- 'cd backend && uv run pytest'`, `~/.claude/bin/testsem -- 'cd tests/web && npm test'`.

## Tasks
- [x] T1 Backend reconnect + camera_unavailable + status (route: inline, one coherent change over 4 small files) — RED: `ImportError: cannot import name 'CameraUnavailable'`; GREEN: `uv run pytest` 253 passed
- [x] T2 Web message for `camera_unavailable` (route: inline) — RED: smoke 195/196 (generic error text); GREEN: `npm test` 135/135 (nobackend) + 196/196 (robot)

## Acceptance
- Dead camera before/during an ACT run: cameras reopened, run continues.
- Reconnect failing after the bounded attempts: plan state `error`, event `code: camera_unavailable`, web shows "cámara desconectada: revisa el USB".
- Both suites green.

## Progress
- Created 2026-10-25.
- 2026-10-25: done. Root failure: lerobot read thread dies for good (`_read_loop` re-raises after max consecutive failures); `is_connected` stays true, so `get_observation` -> `read_latest` raises `read thread is not running`. `ActGrasp.run` checks `cameras_ok()` (thread alive) before the loop and, on a failed read with dead cameras, calls `reconnect_cameras()` (disconnect + connect each, 3 attempts, 0.5 s/1.0 s backoff) and retries the read once; non-camera errors are not masked. Failure -> `CameraUnavailable` -> `error` event `code: camera_unavailable`; web toast "cámara desconectada, revisa el USB". `GET /robot/status` has `cameras`. Cache-bust `?v=20261025c`.
- Not run: real cameras (needs a backend restart to load), `npm run render` / `npm run camera` (need CHROME_PATH). A frame that is stale with a live thread is not detected (lerobot's `read_latest` raises after 500 ms, which takes the same reconnect path).
