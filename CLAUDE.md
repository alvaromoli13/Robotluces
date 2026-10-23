# CLAUDE.md

Guidance for agents and contributors working in this repository.

## Project

SmartSeed: an SO-101 arm (LeRobot) plants seeds into a cell tray following a layout the
customer designs in a cinema-seat-style web UI. 4 seed types, one colored box each.
Full idea, flow and roadmap: see `README.md`.

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
- The scoring table and its implications live in `README.md`; update both files if they
  change.

## Layout

- `web/` — the web UI. Plain HTML/CSS/JS, no build step, no framework. This folder is the
  **GitHub Pages site root**.
- `.github/workflows/pages.yml` — deploys `web/` to GitHub Pages.
- Root `README.md` — project idea and plan. `web/README.md` — notes on the UI prototype.

## GitHub Pages deployment

- The workflow uploads **only `web/`** (`upload-pages-artifact` with `path: "web"`).
  Anything outside `web/` is not published.
- It runs on push to `main` when `web/**` or the workflow itself changes, and manually via
  `workflow_dispatch`.
- Keep asset paths **relative** (`./app.js`, not `/app.js`): the site is served under
  `https://<user>.github.io/Robotluces/`.
- Repo setting required once: Settings → Pages → Source = **GitHub Actions**.
- If the site folder is renamed, update `path:` and `paths:` in the workflow and this file.

## Conventions

- UI copy in Spanish; code, comments and commit messages in English.
- Conventional Commits.
- The published web runs in **demo mode** and must never send real robot commands. Real
  control only goes through the local backend on the laptop connected to the arm.
- Templates and the last-used layout are stored in `localStorage`.
