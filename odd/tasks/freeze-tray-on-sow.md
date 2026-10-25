# Freeze tray detection while sowing

## Objective
Once **Sembrar** is pressed, the holes stay exactly where they were marked: no tray/hole detection requests and no overlay re-positioning until the run ends.

## Problem / why
`scanner.js` keeps calling `POST /vision/tray` (OWLv2 tray hint + depth holes + occupancy) every `MODEL_EVERY_MS` and ArUco detection every frame, and `draw()`/`layoutCells()` re-place the cell overlay on each result. During a run the drawn holes drift, and `buildPlan` read live centres.

## Scope
- `web/scanner.js`: `freeze()` snapshots cell centres + image size and stops marker/model detection, in-flight result application and corner dragging; `unfreeze()` resumes.
- `web/app.js`: `startRun` freezes before building the plan; the plan uses the snapshot; `finishRun` / `closeRun` (finished, failed, stopped, refused) unfreeze.
- `web/index.html`: cache-bust bump.
- Constraints: no stack start/stop, no arm, no POST /plan to the live backend. Backend untouched.

## TDD
Strict TDD enabled. Runner: `~/.claude/bin/testsem -- 'cd tests/web && npm test'`.

## Tasks
- [x] T1 Smoke tests first (frozen on Sembrar, plan uses snapshot, unfrozen on finish/stop/refusal) (route: direct inline) — RED: 3 failures (132/135, nobackend)
- [x] T2 scanner freeze/unfreeze + app wiring (route: direct inline) — GREEN: `npm test` 135/135 (nobackend) + 193/193 (robot)
- [x] T3 Cache-bust bump `?v=20261025b` + docs (route: direct inline)

## Acceptance
- Sembrar freezes the scanner; plan u,v come from the snapshot taken at that moment.
- No detection request or overlay move while the run is active (including cell_done updates).
- Finished, stopped, failed or refused run unfreezes; Stop button still works.
- `npm test` green in both modes.

## Progress
- Created 2026-10-25.
- Detection before: `scanner.js` loop ran ArUco every few frames and `POST /vision/tray` (OWLv2 hint + depth holes + occupancy) every `MODEL_EVERY_MS`; each result rewrote `holes`/`corners` and `draw()` re-placed the cells.
- Now: `freeze()` (called at the start of `startRun`) snapshots centres + image size; loop skips detection, late `/vision/tray` replies are dropped, corner drag is ignored. `buildPlan` reads the snapshot. `unfreeze()` runs in `finishRun` (finished/stopped/error/lost socket) and `closeRun` (refused plan). Stop button path unchanged.
- Not run: `npm run render` / `npm run camera`; jsdom has no camera, so the in-flight drop and loop guard are covered by review, not tests. Backend untouched.
