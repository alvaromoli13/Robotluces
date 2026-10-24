# CLAUDE.md

Guidance for agents and contributors working in this repository.

## Project

SmartSeed: an SO-101 arm (LeRobot) plants seeds into a cell tray following a layout the
customer designs in a cinema-seat-style web UI. 4 seed types, one colored box each.
Full idea, flow and roadmap: see `guide.md`. Resolved criteria and the steps to
reproduce the result: see `README.md`.

## Deliverables and judging (drive every decision)

Deadline: Sunday 2026-10-25 13:00. Deliverables: live demo, **video of at most 1 minute**,
dataset on the Hugging Face Hub, reproducible repo, and the pitch with Q&A.

Scoring (average of the judges): live demo 30 (5 consecutive full-task attempts without
touching the robot, 6 points each), data & training 20, task difficulty 15, usefulness 15,
innovation 10, presentation 10, bonus +5 (HF dataset +3, reproducible repo +2).

Implications for any work here:
- Reliability of the demo task beats feature breadth. Do not add scope that puts the
  5-in-a-row demo at risk.
- Log failures and fixes per iteration; the judges score how the team iterated.
- Keep record/train/rollout commands and configs in the repo so it stays reproducible.
- Upload every dataset to the Hub as soon as it is recorded.
- The scoring table lives in both `README.md` (with how each criterion is resolved) and
  `guide.md` (with its implications); update all three files if it changes.

## Layout

- `web/` — the web UI. Plain HTML/CSS/JS, no build step, no framework. Served at
  `https://alvaromoli13.github.io/Robotluces/web/`; the root `index.html` redirects there.
- `web/scanner.js` — live camera, grid overlay, tray localisation. Source priority:
  ArUco markers (ARUCO_MIP_36h12, ids 0-3 TL/TR/BR/BL) > depth holes from the backend (one
  cell per hole, no corners) > backend tray grid > manually dragged corners. A size typed
  by hand switches back to the grid. A new hole count must repeat twice before the tray
  is resized, so one noisy frame does not wipe assigned seeds. It must keep working when the backend is down.
- `backend/` — offline vision service (uv project, Python 3.12, own `.venv`). FastAPI on
  `127.0.0.1:8000`: `GET /health`, `POST /vision/tray` (multipart `image` → `found`,
  normalized `corners` TL/TR/BR/BL, `rows`, `cols`, `confidence`, `source`, `holes`).
  OWLv2 bbox + OpenCV contour/warp/periodicity in `geometry.py` (dark, light and
  saturated blobs, so cardboard boxes work too). `depth.py`: Depth Anything V2 Small gives
  relative depth, and holes are basins enclosed by walls (grayscale fill from the frame
  border), returned row-major as normalized `x`, `y`, `area`, `depth`, `row`, `col`.
  All model inference shares one `GPU_LOCK`: two threads on MPS at once abort the process. CORS open plus Chrome Private
  Network Access, because the HTTPS Pages site calls localhost. Run `./run.sh`; tests
  `uv run pytest` (wrap in `~/.claude/bin/testsem --` on the team Mac). Tests use synthetic
  trays, synthetic depth maps and stubbed models; never download a model in tests.
  `SMARTSEED_DISABLE_MODEL=1` skips OWLv2 (contour only).
- `backend/smartseed_robot/` — robot executor mounted on the same app: `robot.py` (`RobotPort`,
  `FakeRobot`, `LeRobotFollower`), `kinematics.py` (placo via lerobot, URDF in `backend/assets/so101/`),
  `calibration.py` (pixel→robot homography), `poses.py`, `motion.py`, `executor.py`, `api.py`
  (`POST /plan`, `/stop`, `GET /robot/status`, `WS /robot/progress`, poses, calibration). `SMARTSEED_ROBOT=fake`
  (default) or `real` + `SMARTSEED_ROBOT_PORT`. Tests use `FakeRobot`; never open a serial port in tests.
  lerobot is pinned to commit `e595b79` (same as `vendor/lerobot`). Setup steps: `guide.md` "Ejecutor del robot"
  and `README.md` step 3.
- `odd/tasks/` — per-feature task documents.
- `.github/workflows/pages.yml` — older Actions deployment of `web/` (see below).
- Root `README.md` — resolved criteria and reproduction steps. `guide.md` — project
  idea, architecture and plan. `web/README.md` — notes on the UI prototype.

## GitHub Pages deployment

Current state (checked 2026-10-24):
- Settings → Pages → Source is **Deploy from a branch** (`main`, `/`), build type `legacy`.
  Every push to `main` publishes the **whole repository** (README, `backend/`, `odd/`…), not
  only `web/`. Never commit secrets or private data.
- The root `index.html` redirects to `web/`, so the public URL
  `https://alvaromoli13.github.io/Robotluces/` opens the app.
- `.github/workflows/pages.yml` still exists and deploys only `web/` as the site root when
  `web/**` changes. With the branch source it competes with the branch build (whichever
  deploys last wins, and `/web/` may stop existing until the next branch build). The team
  has to pick one: remove the workflow and keep the branch source, or switch the source
  back to **GitHub Actions** (then the root `index.html` redirect must go).
- Keep asset paths **relative** (`./app.js`, not `/app.js`): the site is served under
  `https://<user>.github.io/Robotluces/`.

## Conventions

- UI copy in Spanish; code, comments and commit messages in English.
- Conventional Commits.
- The published web runs in **demo mode** and must never send real robot commands. Real
  control only goes through the local backend on the laptop connected to the arm.
- Templates and the last-used layout are stored in `localStorage`.
