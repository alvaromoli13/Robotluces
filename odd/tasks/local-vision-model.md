# Feature: local vision model for tray detection

## Objective
Detect the seed tray, its 4 corners and its rows × columns from the top camera **without
internet and without markers**, using an open model running locally on the Mac (MPS), and
feed the result to the live scanner in the web.

## Problem / why
- The web scanner (`web/scanner.js`) only locates the tray with ArUco markers or manual
  corner dragging, and rows/cols are typed by hand.
- The team chose option B (local open model) over a cloud VLM so the demo does not depend
  on the event wifi.

## Scope
- `backend/`: Python FastAPI service on `http://localhost:8000`.
  - `GET /health`, `POST /vision/tray` (JPEG/PNG frame → corners, rows, cols, confidence).
  - Tray localisation: OWLv2 open-vocabulary detection (`google/owlv2-base-patch16-ensemble`,
    prompt e.g. "a black plastic seed tray") → bbox; OpenCV refinement inside the bbox →
    4 corners; perspective warp → rows/cols by periodicity of the cell pattern.
  - CORS + `Access-Control-Allow-Private-Network` so the HTTPS Pages site can call localhost.
- `web/scanner.js`: when the backend is reachable, send a frame about once per second and
  apply the result. Priority: ArUco (4 markers) > model > manual corners. Status shows
  which source is active. Without backend the web behaves exactly as today.
- Docs: README + CLAUDE.md (how to run the backend, priority order, limits).

Out of scope: robot control endpoints, cell occupancy/colour check (possible follow-up).

## Constraints
- Runs offline after the first model download. MPS when available, CPU fallback.
- Separate venv in `backend/` (uv, Python 3.12) for reproducibility.
- Must not break the published demo mode.
- Real tray not yet in front of the camera (2026-10-23 19:45): tune thresholds on real
  frames as soon as it is.

## TDD
- Mode: **strict TDD enabled** (source: user global config "Strict TDD Mode: enabled").
- Runner: `pytest` in `backend/` (`uv run pytest`), wrapped with `~/.claude/bin/testsem`.
- Web: no test runner in repo; verify with a Playwright smoke run (fake camera).

## Tasks
- [x] T1 Backend skeleton + grid geometry (OpenCV corners refinement, warp, rows/cols
      estimation) with pytest on synthetic tray images. Route: delegated (writer, 2+ files).
- [x] T2 OWLv2 detection wrapper + `POST /vision/tray` endpoint, model loaded once, test
      with the detector stubbed; one manual run with the real model. Route: delegated.
- [x] T3 Web integration in `scanner.js` (backend polling, priority, status). Route:
      delegated or inline depending on size.
- [x] T4 Docs (README, CLAUDE.md, `backend/README.md`) + run script. Route: inline.
- [ ] T5 Tune on real tray frames once available.

## Acceptance criteria
- On synthetic images of a dark tray with N×M cells on a light table, the backend returns
  the correct rows/cols and corners within a few pixels.
- With the backend running, the web overlay snaps to the tray and fills rows/cols without
  markers; with the backend off, nothing changes compared with today.

## Progress / evidence
- T1 (63fed70): RED = ModuleNotFoundError on `smartseed_vision.geometry`; GREEN = 11 passed
  (4x6, 5x8, 3x3, 6x4 at 0 and 10 deg, corners < 5 px, bbox restriction, order, blank image).
- T2 (db816ab + follow-up): RED = ModuleNotFoundError on `detector`/`app`, then PNA preflight
  400 (fixed with Starlette `allow_private_network=True`); later RED for contour-fallback
  false positive. GREEN: `testsem -- 'cd backend && uv run pytest -q'` = 24 passed.
- Smoke (real OWLv2, MPS): first request 11.7 s (weights cached, includes load), warm ~0.69 s
  per request. Synthetic 5x8 rotated tray -> owlv2, 5x8, corners within ~3 px, score 0.12.
  Real frame `top_4.png` (no tray, WOWROBO mat): OWLv2 found nothing > 0.05; contour fallback
  first returned a false positive (11x45, confidence 0.21); now rejected (`found:false`) by
  `MIN_CONTOUR_CONFIDENCE=0.35`.
- Added scipy dependency (required by Owlv2 image processor).

- T3 (5ae71c9, inline: single file): Playwright smoke with fake camera showing a synthetic
  5x8 tray rotated 8 deg. Backend off -> status "Modelo de visión no disponible", 3x3 default,
  no errors. Backend on (real OWLv2, MPS) -> "Bandeja detectada por el modelo de visión ·
  5 × 8", rows/cols filled automatically, blue grid aligned with the tray, no page errors.
- T4 (docs commit): README section + structure, CLAUDE.md layout. Run script `backend/run.sh`
  already existed from T2.
- Unrelated uncommitted change in `web/index.html` (CSS "Ajustes solicitados") found in the
  working tree; not authored by this feature, left untouched.

## Next step
T5: capture top-camera frames with the real tray and tune thresholds / rows-cols estimation.
