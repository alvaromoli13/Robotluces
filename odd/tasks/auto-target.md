# Auto target and precise grasp

## Objective
The robot finds the seeds by itself and grasps them precisely until the box is empty, so "Sembrar" needs no hand-set
position.

## Problem
ACT trained end to end on the sim demos stays at 6-9/30 (held-out, narrow): it misses the seed by about 2 cm, also when a
single seed is in the box (2026-10-31 diagnostic). A scripted IK grasp given the seed position works when that position is
good: 49/48 of 50 at 0 mm error, 37/37 at 5 mm, 10/7 at 10 mm, 4/3 at 15 mm (black/white, sim, 2026-10-31).

## Why
The deciding number is how far a top-camera detector plus the calibration puts the seed from where it really is:
under about 5 mm a scripted grasp is enough; around 1 cm a policy must correct with the wrist camera. Separately the user
wants an end-to-end Multi-Task DiT attempt (lerobot `multi_task_dit`) that finds the seed itself, aimed at precision.

## Scope
- Seed detector on the top image -> pixel centre per seed of a colour -> robot base xy through the existing
  `backend/smartseed_robot/calibration.py` `pixel_to_robot`; measured against sim truth.
- Multi-Task DiT preparation: plan, dataset/training/eval tooling, nothing trained.
- Later (not started): the backend loop detect -> grasp -> place -> repeat until empty.

## Constraints
- Local only. No Hub upload, no Brev, no real arm, never ports 8000/8080, without a new user OK.
- TDD on: pytest in `backend/.venv` through `~/.claude/bin/testsem`, RED first. Push to main after each task.
- One writer at a time (no parallel writers in this checkout).

## Tasks
- [x] A1 Seed detector + sim precision (route: delegated, one writer; trigger: 2+ non-trivial files plus reading to
      prepare it). Acceptance: per colour, on held-out narrow sim scenes, the error (mm) between the detected and the true
      base-frame xy of every seed (median, p90, max) and the miss/false-detection counts; same code path the real backend
      would use.
      Evidence (2026-10-31): route delegated, one writer. `backend/smartseed_robot/seed_detector.py` + `sim/detect_eval.py`;
      tests `test_seed_detector.py` (11) and `test_sim_detect_eval.py` (8). RED observed per test (ImportError, then the
      orange-arm and wall-chunk cases failed before the saturation cap and the 70 % surrounded-by-floor rule), GREEN after.
      Held-out narrow, 50 scenes per colour, seed-plane calibration: detector alone (nominal camera) black 133/133 and
      white 146/146 seeds, 0 false, median 0.8 / p90 1.1-1.0 / max 1.2-1.9 mm; with the sim's camera noise (+-5 mm, +-1 deg)
      black median 7.0 / p90 12.3 / max 15.3 mm, white 7.7 / 13.2 / 14.9 mm, 0 misses, 0 false. Calibration at the tray top
      (sim mode's file) is 15 mm and worse. Verdict: a scripted grasp needs the camera known to about 5 mm / 0.5 deg; at the
      sim's randomisation it is about half the seeds. Details: `sim/README.md` "Seed detector precision (A1)".
- [ ] A2 Multi-Task DiT preparation (route: delegated; read-only research first, then one writer after A1). Acceptance: a
      written plan (inputs, image resolution for precision, one model for both colours with a language task, batch/GPU,
      steps, eval) in `sim/README.md`; tooling to build its dataset and to train/eval it in sim; tests; not trained.
- [ ] A3 Backend auto-target loop (not started; needs the A1 number and the user's choice of grasp method).

## Progress
- 2026-10-31: created. Tolerance numbers above from a scratch run of the scripted planner (`eval.planner_ceiling` with a
  fixed-magnitude aim error; a planner refusal for a wall in the way counts as a failure).
- 2026-10-31: A1 done. The detector is about 1 mm; the 7-8 mm median under camera noise is calibration/pose error, not
  detection. The calibration plane must be the seed-centre height (tray-top costs 15 mm). Commit: see git log (feat(sim): seed detector).
