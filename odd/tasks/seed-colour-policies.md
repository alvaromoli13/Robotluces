# Seed colour policies (Tomate = black, Pimiento = white)

## Objective
Tomate resolves to the black bowl and Pimiento to the white one, each with its own ACT model
(`d1-c100` black, `d2-c100` white), and **Sembrar** runs grasp then drop for every cell, one after the other.

## Problem / why
Defaults were Tomate=red, Pimiento=green and the stack only configured a black policy
(`act-smartseed-grasp-merged`, 15 s). The new d1/d2 models were trained on 10 s episodes.

## Scope
- `web/app.js`: default seeds + migration of stored built-in seeds that still carry the old default colours
  (never touch user-created seeds, never create a duplicate colour).
- `scripts/stack.sh`: default policies and ACT duration (10 s).
- Backend executor: verify (and fix if needed) that a full plan = ACT grasp from the seed colour, release over the
  cell, cell by cell, then home; stop stays safe (arm holds position).
- Constraints: no stack start/stop, no arm, tests hardware-free.

## TDD
Strict TDD enabled. Runners: `~/.claude/bin/testsem -- 'cd backend && uv run pytest'`,
`~/.claude/bin/testsem -- 'cd tests/web && npm test'`.

## Tasks
- [x] T1 Web default colours + stored-seed migration, tests first (route: direct inline) — RED: 7 smoke failures (122/129); GREEN: `npm test` 129/129 (nobackend) + 183/183 (robot)
- [x] T2 stack.sh default policies/duration (route: direct inline) — `bash -n` ok
- [x] T3 Sow flow audit + test (route: direct inline) — RED: 3 failed (final pose not home); GREEN: `uv run pytest` 240 passed
- [x] T4 Docs (README/CLAUDE.md/guide.md) mentions of old defaults

## Acceptance
- Fresh load: `TOMATE:black,PIMIENTO:white`; stored `TOMATE:red` / `PIMIENTO:green` resolve to the new colours,
  custom seeds untouched, colour never duplicated.
- stack.sh default policies `{"black": d1-c100, "white": d2-c100}`, 10 s.
- A full plan with ACT does grasp then drop per cell in order, then home.
- Full `uv run pytest` and `npm test` green.

## Progress
- Created 2026-10-25.
- 2026-10-25: Sow flow audit: **Sembrar** posts `mode: 'full'` (web `test || 'full'`); `Executor._plant` already ran ACT grasp
  from the cell colour's policy then `_release` over the cell, cell by cell, nothing skipped. Gap fixed: a full plan with ACT
  cells ended at `act_start`; it now goes to taught `home` (gripper open) after the last cell. Stop unchanged (arm holds, no home).
  New test covers two colours (white then black policy, drop between, home at the end).
- Migration (`migrateDefaultColors` in `loadSeeds`): stored `TOMATE` red -> black and `PIMIENTO` green -> white, persisted;
  skipped when the colour is already owned by another seed or the user recoloured the seed. UI wording stays "caja negra/blanca".
- Not run: `npm run render` / `npm run camera`, no arm, stack untouched (running policies need a restart to pick up the new defaults).
