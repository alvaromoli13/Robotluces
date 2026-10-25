# ACT model selector

## Objective
Pick, from the web, which ACT policy (Hub model + checkpoint) the arm runs, without restarting the stack.

## Problem / why
Four new grasp models were trained on 2026-10-25 (`act-smartseed-d{1,2}-c{100,50}`, checkpoints 10k/20k/30k/40k)
plus the older merged model. Testing each on the real arm by editing `SMARTSEED_ACT_POLICIES` and restarting is slow.

## Scope
- Backend: list available models/checkpoints and switch the active policy for a bowl colour at runtime.
- Web: selector (model + checkpoint) that calls the backend.
- Constraints: no stack restart per switch; existing env config keeps working; tests stay hardware-free.

## TDD
Strict TDD enabled (session config). Runner: `cd backend && uv run pytest` (wrapped in `~/.claude/bin/testsem --`), web: `npm test`.

## Tasks
- [x] T1 Backend catalog + select endpoint, with tests (route: delegated, writer trigger: 2+ non-trivial files) — 49d1a3d; RED: `ModuleNotFoundError: smartseed_robot.catalog`; GREEN: `uv run pytest` 239 passed
- [x] T2 Web selector wired to the endpoint, with tests (route: delegated, same writer) — 1bbb1f6; RED: `actPanel` missing (112/113); GREEN: `npm test` 125/125 (nobackend) + 179/179 (robot)

## Acceptance
- Web shows all `RafaelJaime/act-smartseed-*` models with their checkpoints (final + intermediate).
- Choosing one makes the next ACT run use it; status shows the active one.
- `uv run pytest` and `npm test` green.

## Progress
- Created 2026-10-25.
- 2026-10-25: T1+T2 done. `GET /robot/act/models`, `POST /robot/act/select {color, repo, checkpoint|null}` (409 busy while a plan runs, 422 unknown model/checkpoint, 502 download failed). Hub catalog cached 5 min, offline falls back to stale cache or the env defaults. Intermediate checkpoints: lerobot cannot load a Hub subfolder, so `snapshot_download(allow_patterns=checkpoints/<step>/pretrained_model/*)` and the local `pretrained_model` dir is passed to `from_pretrained`. Download happens on select; the model loads on the next ACT run.
- Not run: `npm run render` / `npm run camera` (need CHROME_PATH), no real Hub call, no arm.
