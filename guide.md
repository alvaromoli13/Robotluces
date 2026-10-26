# SmartSeed 🌱 — Assisted seeding with an SO-101 arm

Project guide: idea, architecture and work plan. For the resolved criteria and the
reproduction steps, see [README.md](README.md).

Project for the **Robotekin LeRobot Hackathon** (Vitoria-Gasteiz, 23-25 October 2026).
Submission: **Sunday 13:00**. Presentations: 14:15.

## The idea

An **SO-101** (LeRobot) robotic arm seeds a cell tray following the design the customer
picks in a graphical interface.

- The seeds are defined by the user in the web page ("+" button: name, emoji and **color of
  its box**); 4 come by default, each in a **box of a different color**.
- The seed tray is a grid of cells (rows × columns).
- The interface works like a **cinema or stadium seat picker**: each cell is a square and
  is painted the color of the seed it will hold.
- When the customer presses **Sembrar** ("Seed"), the robot picks up the seeds from the
  colored boxes and seeds each cell according to the plan.

## Deliverables and evaluation

**Deliverables** (before Sunday at 13:00):
1. **Live demo** in front of the jury.
2. **Video of 1 minute at most.** When it is finished, it goes into the team's Drive
   folder: <https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n>.
3. **Dataset published on Hugging Face** (bonus +3).
4. **Reproducible repository**, this one (bonus +2).
5. **Presentation** of the project and the jury's Q&A.

**Criteria.** Each juror scores each team and the final grade is the average of all of them.

| Criterion | What is assessed | Points |
|---|---|---|
| Live demo | 5 consecutive attempts at the complete task **without touching the robot**; each success earns 6 points | 30 |
| Data and training | Amount, variety and consistency of the demonstrations; cameras and framing; how failures were iterated on | 20 |
| Task difficulty | Realistic ambition for 48 h: from picking up an object to multi-step tasks that withstand changes of position or lighting | 15 |
| Usefulness and impact | That it solves a real problem | 15 |
| Innovation and ingenuity | Originality of the approach and of the solution | 10 |
| Presentation and team | How the work is told and how the jury is answered | 10 |
| Bonus | Dataset on Hugging Face (+3) and reproducible repository (+2) | +5 |

**What this means for the project:**
- **The demo scores the most** (30). The demo's "complete task" has to be something the
  robot does well **5 times in a row**, for example a small fixed template of 4 cells, one
  per color. A short, reliable demo is better than the whole tray with failures. The
  complete tray can appear in the video.
- **Data (20)**: many consistent demonstrations, varying the position of the seeds and the
  lighting a little. The failures of each iteration and how they were fixed have to be
  written down (in the task documents in `odd/tasks/`, section *Progress / evidence*),
  because that is what is told to the jury.
- **Difficulty (15)**: the task has several steps (choose box → pick up → carry →
  release in the right cell), which is already ambitious. We have to show that it
  withstands changes of position or lighting.
- **Usefulness (15)**: custom seeding for nurseries and vegetable gardens; the customer
  designs their tray without repetitive manual work.
- **Innovation (10)**: the cinema-seat interface with the live camera, the reusable
  templates and **marker-free** tray detection.
- **Bonus (+5)**: upload the datasets to the Hub as soon as they are recorded and leave the
  exact commands to record, train and run in the repo.

## Usage flow

0. **Place the tray**: the farmer leaves the tray **anywhere in the work area** of the
   table, without sticking anything on it or aligning it. The overhead camera detects it
   and the web page shows the real grid (number of cells and their position) over the live
   image.
1. **Choose a template**: when the app opens, the **last formula used** is loaded. A
   **saved template** can also be chosen.
2. **Edit**: the customer taps cells to change their seed (each cell can hold a different
   seed), or uses the **fill everything with one color** buttons. Empty cells are left
   unseeded.
3. **Save (optional)**: the design can be saved as a named template.
4. **Seed**: the plan is sent to the robot. The interface shows live which cell is being
   seeded and which are already done.
5. **Finished**: the formula is saved as "last used" for next time.

The grid is shown **over the overhead camera image**, so the customer sees the real tray
with the plan superimposed, and progress can be checked at a glance.

## Architecture

```
┌──────────────┐  plan (JSON)  ┌──────────────────┐  actions   ┌──────────┐
│  Web (web/)  │ ────────────▶ │ Local backend    │ ─────────▶ │  SO-101  │
│ grid +       │ ◀──────────── │ (Mac, Python,    │ ◀───────── │ follower │
│ camera       │  progress     │  LeRobot)        │  state     │ + cameras│
└──────────────┘  (WebSocket)  └──────────────────┘            └──────────┘
```

- **Web** (`web/`): HTML/CSS/JS without a framework. Templates and last formula in
  `localStorage`. Published on GitHub Pages in **demo mode**, without a robot.
- **Local backend**: Python server on the laptop connected to the robot. It receives the
  plan, turns it into a task queue `(box color → cell row,column)` and streams the camera
  and the progress. It also detects the tray in the image. It is the only place that talks
  to the hardware.
- **Execution on the robot**: hybrid approach, see the next section.

The plan that crosses from the web page to the backend **carries no robot coordinates: it
carries pixels**. The conversion to meters and to angles is done by the backend, which is
the one that knows the calibration.

## Robot approach: hybrid

Each cell of the plan is seeded in two phases:

| Phase | How it is done | What moves in the scene |
|---|---|---|
| 1. **Pick up** the "seed" from the bowl of color X | **Learned policy** (ACT) for color X: from the start pose it goes to the bowl, picks up and comes back, guided by the cameras | The **bowls can move**: the policy looks for its own by color, not by position |
| 2. **Release** it in the cell (row, column) | **Vision + inverse kinematics**: the camera locates the cell and the arm computes how to get above it | The **tray goes wherever the farmer leaves it**, within the work area |

- **Policy: one ACT per bowl color.** From the start pose (`act_start`), the policy for the
  color in turn does the whole pickup cycle: go to the bowl, pick up and come back. The
  episodes are recorded with **both bowls on the table and swapped around**, so the
  policy learns to look for its own **by color** and not by position. A color without a
  policy falls back to the taught-poses route, which keeps working.
- **Why one per color and not a single one for all**: a single policy with both bowls in
  front of it has no way of knowing which one to go to, because ACT does not receive the
  color as an input. Separating them is what turns "pick up something" into "pick up from
  the red bowl".
- **What it costs**: a few dozen episodes per color and one training run per color. The
  current models come from two 10 s grasp datasets (96 and 91 clean episodes) and from
  40,000 steps on Brev with 2 H100s (~1 h 45 per pair of models; see "Data and policy").
- Alternative discarded for lack of time: a SmolVLA that receives the color as text.
- **Why not learn everything**: ACT does not receive "which cell am I going to". Learning
  "box X → cell (row, column)" would require demonstrations for 4 colors × 40 cells,
  hundreds of combinations, and it does not fit in 48 hours. The geometric part (where
  each cell is) is an exact calculation; the hard perception part (picking up from a box
  that has moved) is the one that is learned.
- **What earns points**: moving the bowls between episodes is what demonstrates the
  difficulty criterion ("withstands changes of position or lighting") and the data and
  training one.
- **Where it fits in the code**: the executor first checks whether that color has a policy
  (`ActGrasp` in `act.py`, declared in `SMARTSEED_ACT_POLICIES`). If it does, it runs the
  policy in a closed loop at 30 Hz for `SMARTSEED_ACT_DURATION_S`; if not, it falls back
  to the taught-poses `Grasper` (`TaughtGrasp`: goes down to `grasp_<color>` or applies
  some deltas and closes). Both routes end in the same release.
- **Pickup plan B**: if a policy is not reliable in time, that bowl is fixed in place and
  its pickup is done with taught positions. The demo still works and the policy remains
  as an improvement.

## Seeding sequence

The backend executor walks through the plan cell by cell. The pickup has two routes
depending on whether there is a policy for that color or not; the release is the same in
both:

```
with policy:    act_start → the ACT goes to the bowl, picks up and comes back
                → above the cell (inverse kinematics) → wrist +5° → open gripper → act_start
                (after the last cell: home)

without policy: start → above the bowl (taught pose) → pick up → is it holding anything?
                → lift → above the cell → open gripper → start
```

1. **Pickup with policy**: the arm goes to `act_start` (the pose the episodes start in)
   and the ACT for that color sends actions at 30 Hz for the configured number of
   seconds. In this route the grasp is not judged: the policy leaves the gripper almost
   closed on the seed, and that is indistinguishable from an empty gripper.
2. **Pickup with taught poses**: `home` → `above_box_<color>` → the `Grasper` goes down
   and closes. After 0.3 s of rest the gripper position is checked (`gripper.pos`, from 0
   to 100): if it has closed completely (≤ 8), there is nothing inside, and it
   **retries once**. Then it rises to the pose above the bowl with whatever it holds.
3. **Release**, the same in both routes: the cell center in pixels is converted to the
   robot's (x, y) with the homography, and the arm first positions itself **8 cm above**
   the release height and goes down from there, so as not to scrape the tray on arrival.
4. **Closed-loop correction**: with the arm extended the servos sag under gravity, so
   after moving the executor reads the joints, computes with forward kinematics where the
   tip ended up and, if it is off by more than **5 mm**, aims further by the amount it was
   short and repeats, up to **2 corrections**. The final error comes out in the
   `drop_pose` event and the web page shows it as "Soltado a N mm del hueco" ("Released N
   mm from the cell").
5. **Tilt the wrist and open the gripper**: right before opening, `wrist_flex` +5°
   (`release_wrist_tilt_deg`) so that the seed falls toward the cell; afterwards it rises
   again to the approach pose and returns to the start of the route. In a full plan with
   policy, after the last cell the arm goes to `home` with the gripper open.

In short, **Sembrar** is, cell by cell: ACT grasp from the seed's box and release over
the cell; the plan ends at `home`.

**If the gripper seems empty, the cell is completed anyway**: the arm goes to the cell,
opens and carries on. The `cell_done` event arrives with `empty: true` and the web page
warns about it. This is deliberate: in a demo of 5 consecutive attempts it is better to
complete the run and show which cell came out empty than to abort.

**Half tests.** The plan accepts a `mode` to debug without doing the whole cycle:
`"grasp"` only picks up and keeps the seed (it needs no calibration), `"place"` only
releases over the cell with the gripper as it is (it needs no policy or taught bowls).
They are the **Probar coger** ("Test grasp") and **Probar dejar** ("Test release")
buttons of the **Ajustes** ("Settings") panel. It also accepts `drop_z` (0.02-0.25 m) to
change the release height for that plan only.

**How the arm moves.** The SO-101 receives joint angles in degrees:
`robot.send_action({"shoulder_pan.pos": …, "shoulder_lift.pos": …, "elbow_flex.pos": …,
"wrist_flex.pos": …, "wrist_roll.pos": …, "gripper.pos": 0-100})`. The target is not sent
all at once: it is interpolated between the current position and the final one at 30 Hz
with a limit of 45 °/s on the joint with the longest travel, and `max_relative_target` (8)
in the follower configuration additionally limits how far it can move at each step.

**Before moving a single motor** the executor validates the whole plan: fields and colors,
that there is a calibration, that the poses for colors without a policy are taught, and
that inverse kinematics solves **all** the cells. If anything fails, the plan is rejected
with its code and the arm does not move.

**Stop**: `POST /stop` cuts the sequence and the arm **stays where it is, with torque on**;
the motors are not disabled, so as not to drop the piece in mid-air or let the arm fall.
Removing torque is a separate, explicit action (`POST /robot/torque-off`), only when the
arm is in a safe place.

**Actual executor parameters** (`ExecutorConfig`), the ones worth knowing:

| Parameter | Value | What it is |
|---|---|---|
| `drop_z` | 0.06 m | height of the tip above the tray when releasing (adjustable per plan) |
| `approach_clearance` | 0.08 m | how far above it positions itself before going down |
| `place_tolerance_m` | 5 mm | error accepted over the cell when releasing |
| `place_corrections` | 2 | aiming retries per cell |
| `hz` | 30 | control frequency (and the policy's) |
| `max_speed` | 45 °/s | limit on the joint that rotates the most |
| `max_relative_target` | 8 | per-step cap on the follower |
| `gripper_open` / `gripper_closed` | 60 / 0 | gripper open and closed |
| `empty_below` | 8 | below this, the gripper is empty (taught route only) |
| `release_wrist_tilt_deg` | 5° | `wrist_flex` added over the cell right before opening the gripper |
| `settle_s` | 0.3 s | rest before judging the grasp and before measuring the tip |
| `retries` | 1 | grasp retries (taught route only) |
| IK tolerance | 3 mm | with up to 6 solver rounds per tilt |

## Free tray: detection and inverse kinematics

### 1. Detect the tray

The tray is located **without sticking anything on it**, which avoids preparing material
and makes it work with whatever tray the customer brings. There are three ways, and the
first one available wins; the color of what is drawn over the video shows which one is
active. As long as no tray is detected, no grid is drawn: an invented grid over the table
is worse than none.

1. **Cells by depth** (blue circles, backend). **Depth Anything V2 Small**
   (`depth-anything/Depth-Anything-V2-Small-hf`) estimates the relative depth of each
   pixel (about 130 ms per frame on MPS). The table around the box is as low as the
   bottom of a compartment, so "deep" is not enough: a cell is a **basin surrounded by
   walls**, an area from which water could not get out to the edge of the image without
   going over a wall (morphological fill from the frame border). Each basin gives the
   center of a cell; stray basins and those that fall outside the tray are discarded, and
   the ones left are numbered in tray coordinates, not image coordinates, so the rows and
   columns come out right even if it is rotated.
2. **Grid from the vision model** (blue, backend). **OWLv2**
   (`google/owlv2-base-patch16-ensemble`), an open detector that looks for objects from
   text ("a black plastic seed tray"), locates the tray in the image; **OpenCV** extracts
   inside that area the 4 exact corners (trying dark, light and saturated blobs, so that
   cardboard boxes also work), straightens the tray and **counts rows and columns** from
   the periodicity of the cell edges. A contour with no pits in the depth map does **not**
   count as a tray: contours alone also match printed text or floor tiles. On the Mac
   (MPS) it takes about 0.7 s per frame; the first time, about 12 s more while the model
   loads.
3. **Corners by hand** (yellow, always available). The user drags the 4 corners over the
   video and types rows and columns. It works **without a backend**, so it is the demo's
   safety net. If the user types rows or columns by hand, it goes back to the grid and the
   model no longer overwrites them.

With the 4 corners and the rows × columns count, the center of each cell is computed in
pixels by bilinear interpolation, even if the tray is rotated; with the cells by depth the
center comes directly from each basin. A new cell count has to repeat twice in a row
before the tray is resized, so that a noisy frame does not wipe out the seeds already
assigned.

**Already occupied cells.** Each cell is compared with the tray's own material, sampled on
the edge **between** the cells and not against the other cells, so it keeps working with
the tray almost full. A cell counts as occupied if its color departs from the edge
(chromaticity in Lab, so that shadows do not count) or if its brightness becomes uneven
(stones, seeds and their shadows). The web page paints them **amber**. Measured on the
real cardboard tray: empty ≤ 4.5 chroma and ≤ 16 deviation; with stones, 17 and 30.

**ArUco markers: supported, but we do not use them.** `web/scanner.js` can detect 4
`ARUCO_MIP_36h12` markers at the corners with `js-aruco2` (vendored in `web/vendor/`,
no CDN) and they would take priority over everything else if they were stuck on. We do not
use them: the point is that the farmer just leaves the tray and that is it. They remain as
an option if marker-free detection goes wrong with the real tray.

Start the backend (on the robot's laptop):

```bash
cd backend
uv sync          # first time only; installs torch, transformers, OpenCV and lerobot in backend/.venv
./run.sh         # http://localhost:8000 · GET /health · POST /vision/tray
```

Then open the web page (published or `web/index.html`) and press **Escanear con cámara**
("Scan with camera"). If the backend is at another address, run this in the browser
console:
`localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')`.

The thresholds are tuned with synthetic images and with two photos of the real cardboard
tray (empty and with stones), which live in `backend/tests/fixtures/` and are used in the
tests. With another tray, you have to re-check the brightness on black plastic, a dark
table that gets mistaken for the tray, and whether it counts the cells correctly. Tests:
`cd backend && uv run pytest`.

### 2. Calibrate the camera with the robot (once)
- The gripper tip is taken to 4-6 marks on the table. At each one, the pixel where the
  camera sees it and the tip position given by forward kinematics are saved.
- `cv2.findHomography` turns those pairs into a **table pixel → robot (x, y)
  coordinates** transformation, and returns the mean and maximum error in mm. Since those
  positions come from the same arm model that inverse kinematics later uses, a good part
  of the model's errors cancel out.
- **From the browser**: **Escanear** ("Scan") → **Calibrar robot** ("Calibrate robot") does
  the whole cycle without touching the console: "Soltar brazo" ("Release arm"), take the
  tip to a point on the tray, click that point in the image, and with 4 spread-out points,
  **Ajustar** ("Fit"; it shows the error in mm). It can also be done by hand with
  `POST /robot/calibration/points` and `/fit`.
- The calibration is saved in `backend/data/calibration.json` and reloaded at startup; if
  the frame arrives at another size, the pixels are rescaled automatically.
- About 15 minutes. It is only repeated if the overhead camera or the robot is moved.

### 3. Release in the cell
- For each cell: pixel → robot (x, y) → **inverse kinematics** to 6 cm above the
  cell → open the gripper.
- **The gripper points as far down as the arm allows**: the solver tries vertical first
  and, if it cannot reach, tilts it outward in 15° steps (15, 30 … 90) and keeps the
  first tilt that reaches; only if none reaches does orientation stop mattering and only
  the position counts. This gains reach on far cells without giving up entering straight
  on near ones.
- The approach is from above (8 cm above) and with **closed-loop correction**:
  see [Seeding sequence](#seeding-sequence).
- LeRobot ships the kinematics: `lerobot.model.kinematics.RobotKinematics`
  (`forward_kinematics` / `inverse_kinematics`), which uses `placo`. `uv sync` installs it
  with the `kinematics` extra; the SO-101 URDF (`so101_new_calib.urdf`) and its meshes are
  vendored in `backend/assets/so101/` (provenance and commit in `SOURCE.md`), so there is
  nothing to download.

### Risks and how to mitigate them
- **The URDF has to match our calibration**: `so101_new_calib` is designed for LeRobot's
  calibration, but this has to be checked in 10 minutes. Move the arm by hand and check
  that the position given by `forward_kinematics` matches the real one
  (`GET /robot/joints` returns `tool`).
- **Accuracy**: error accumulates between the calibration and the kinematics. The
  closed-loop correction on release absorbs a good part of it (it leaves the tip within 5
  mm when it arrives in time), but it has to be **measured** with a 10-cell test; the error
  of each release comes out in the `drop_pose` event and in the web page itself. With 4 cm
  cells and 2.5 cm balls the margin is tight: mitigation, release from a little higher
  (the Ajustes panel changes the height without touching code), slightly smaller balls or a
  tray with larger cells.
- **Detection tuned with few real photos**: this is the new risk since we stopped using
  markers. Immediate mitigation: the corners by hand, which do not depend on any model.
- **The policy does not judge the grasp**: in the ACT route the gripper is left almost
  closed on the seed, indistinguishable from empty, so there is no retry. Mitigation: the
  arm releases anyway over the cell and the web page warns that it looked empty.
- **Work area**: "anywhere" means within the area the arm reaches and the overhead camera
  sees. It is marked on the table. If the tray ends up outside, the backend rejects the
  plan with `code: "unreachable"` and the list of cells, and the web page explains it.
- **Time**: installing, calibrating and tuning takes half a Saturday. It is the project's
  biggest technical risk.

### Tray plan B
If on **Saturday at noon** the 10-cell test is not reliably accurate, the tray outline is
drawn on the table and the balls are released using **4 corners taught with the leader**
and interpolation. The camera still detects the grid for the web page and checks that the
tray is in its place.

## Robot executor (`backend/smartseed_robot/`)

By default the robot is **fake** (`SMARTSEED_ROBOT=fake`): it opens no serial port. With
the real arm:
`SMARTSEED_ROBOT=real SMARTSEED_ROBOT_PORT=/dev/tty.usbmodemXXXX ./run.sh`
(follower `follower_01`, degrees, `max_relative_target` 8). The taught data is saved in
`backend/data/` (`poses.json`, `calibration.json`, outside git; `SMARTSEED_DATA_DIR`
changes it).

Modules:

| File | What it is responsible for |
|---|---|
| `robot.py` | `RobotPort` (read and send joints, torque, observation), `FakeRobot` and the `LeRobotFollower` adapter |
| `kinematics.py` | forward and inverse kinematics over the SO-101 URDF (placo), with the preferred downward tilt |
| `calibration.py` | pixel → table homography, its error in mm and its persistence |
| `poses.py` | named taught poses (`home`, `act_start`, `above_box_<color>`, `grasp_<color>`) |
| `motion.py` | movement interpolation, cancelable |
| `act.py` | ACT policies per color, loaded on first use, and their closed loop; `select` swaps the one for a color on the fly |
| `catalog.py` | catalog of ACT models and checkpoints on the Hub (5-minute cache) and download of intermediate checkpoints |
| `executor.py` | plan validation, modes, sequence of each cell and corrected release |
| `api.py` | HTTP endpoints and the progress WebSocket |

Setting up with the arm (everything on `http://127.0.0.1:8000`; move the arm by hand with
torque off: `POST /robot/torque-off`):

1. **Check forward kinematics**: `GET /robot/joints` returns angles and `tool` (x, y, z
   in meters relative to the base). Measure the gripper tip with a ruler and compare.
2. **Teach poses** (`home`, `above_box_<color>` —by default `red|yellow|green|purple`, and
   any other color you add in the web page— and optional `grasp_<color>`
   that goes down to pick up): place the arm and `POST /robot/poses/{name}`.
   `POST /robot/goto/{name}` checks that it returns to it, **after** turning torque back
   on with `POST /robot/torque-on` (sets target = current position, no jumps). With
   torque off, `goto` and `/plan` respond `409 torque_off`.
3. **Calibrate camera-robot**: with the tip over a visible point of the tray,
   `POST /robot/calibration/points {"u":..,"v":..,"image_size":[w,h]}` (x, y come from
   forward kinematics). At least 4 spread-out points and `POST /robot/calibration/fit`
   (returns the error in mm).
4. **Seed**: `POST /plan {"image_size":[w,h],"cells":[{"cell_index","row","col","color","u","v"}]}`
   and follow the progress through `WS /robot/progress`. Optional: `mode` (`"full"` by
   default, `"grasp"` only pick up, `"place"` only release; these are the tests in the
   **Ajustes** panel) and `drop_z` (m, 0.02–0.25) for the tip height when releasing.
5. **Choose ACT model** (optional): in **Ajustes → Modelo ACT** ("Settings → ACT model")
   you pick color, model and checkpoint. It is equivalent to `GET /robot/act/models`
   (`RafaelJaime/act-smartseed-*` models from the Hub with their checkpoints, 5-minute
   cache) and `POST /robot/act/select {color, repo, checkpoint}` (`409 busy` with a plan
   running, `422` unknown model or checkpoint, `502` failed download). An intermediate
   checkpoint is downloaded with `snapshot_download`
   (`checkpoints/<step>/pretrained_model/*`); the model is loaded on the next ACT.
6. **Stop**: `POST /stop` (the arm stays in place with torque on). `POST /robot/torque-off`
   only when the arm is in a safe place; `POST /robot/torque-on` to recover it.

In the taught-poses route, an empty grasp (gripper fully closed) is retried once; with a
policy it is not judged. In both cases the arm **releases anyway over the cell** and the
cell counts as done, with a warning that the gripper seemed empty. With the gripper
vertical the reach at tray height is about 28 cm from the base; tilting it outward
reaches a bit farther.

## Cloud training (Brev)

The final ACTs are trained on Brev machines with 2 H100s, one variant per GPU, at ~6.3
steps/s (40,000 steps, batch 32, ~1 h 45). The scripts are in `scripts/brev/`; the full
commands are in [README.md § Training](README.md#train).

| Script | Where it runs | What it does |
|---|---|---|
| `train_pair.sh <dataset> <prefix>` | Brev machine | trains `-c100` and `-c50` at the same time (one per GPU) and uploads checkpoints every 10,000 steps to the Hub |
| `resume.sh <source> <step> <total> <new>` | Brev machine (1 GPU) | resumes from a checkpoint on the Hub, optimizer included, up to more steps |
| `watch_one.sh <host> <repo> <final step>` | the Mac | waits for training to end and deletes the machine only once the final checkpoint is verified on the Hub |

Operating lessons:
- `scp` to Brev says OK but the file **does not arrive in `~`**: upload it with `ssh host 'cat > ~/f' < f`.
- After launching a training run, check `tmux` and the log before leaving.
- Do not delete the machine by hand: `watch_one.sh` does it itself after verifying the Hub.

## Scene and objects

Seeds are represented by **balls** or similar objects: picking up a real seed with the
SO-101 gripper would fail too often to survive 5 demos in a row.

- **Size**: roughly 60-70 % of the cell opening, so that it goes in even if the robot
  releases a little off. For example, about 2.5 cm for 4 cm cells.
- **That they do not bounce or roll**: wooden balls, solid rubber, large marbles or
  pompoms. No ping-pong balls.
- **Color**: each ball the color of its box. It is understood instantly in the demo and in
  the video.
- **Boxes**: low, with a 3 to 5 cm rim, so that the gripper reaches the bottom, and with few
  balls inside so that it does not pick up two at once.
- **Table**: a color that contrasts with the balls and the boxes and without reflections,
  with the lighting as constant as possible.

### Plan format

When **Sembrar** is pressed, the web page sends `POST /plan` with one entry per cell that
holds a seed (empty ones are not sent). `u` and `v` are the cell center in **pixels** of
the camera frame, which the backend converts to table coordinates with the homography:

```json
{
  "image_size": [1280, 720],
  "cells": [
    { "cell_index": 0, "row": 0, "col": 0, "color": "red",    "u": 412, "v": 233 },
    { "cell_index": 5, "row": 1, "col": 1, "color": "green",  "u": 498, "v": 301 },
    { "cell_index": 9, "row": 2, "col": 1, "color": "purple", "u": 499, "v": 370 }
  ]
}
```

`color` is the id of the color of the **box** to pick up from, not the name of the variety.
The user chooses it when creating the seed (`red`, `orange`, `yellow`, `green`, `blue`, `purple`,
`pink`, `white`; the backend accepts any id `^[a-z][a-z_-]{0,19}$`). By default:
Tomate (tomato) → `black`, Pimiento (pepper) → `white`, Limón (lemon) → `yellow`, Berenjena
(eggplant) → `purple`. A color without a taught pose responds `409 missing_pose`. `cell_index`
is the index of the square on the map (`row * columns + column`) and comes back unchanged in
the progress events, so the web page knows which square to paint.

Optional body fields, used by the debug buttons in **Ajustes**:
`mode` (`"full"` by default; `"grasp"` goes to `act_start`, runs the policy and keeps the
seed, or in a route without a policy rises from the taught box; `"place"` goes above the
cell with the gripper as it is, opens and returns to `act_start`, without a policy or boxes) and
`drop_z` (m, 0.02–0.25, replaces the default height of 6 cm for that plan only). `grasp`
needs no calibration; `place` does. `plan_started` repeats the `mode` in the event.

Response: `202 {"plan_id", "cells"}` if it accepts it. Otherwise, `4xx {"detail", "code"}`:

| `code` | When |
|---|---|
| `invalid` (422) | fields are missing, the color id is not valid, or `mode`/`drop_z` is out of range |
| `no_calibration` (409) | the homography is not fitted (does not apply in `mode: "grasp"`) |
| `missing_pose` (409) | `home` or the pose of some color without a policy is missing (does not apply in `mode: "place"`) |
| `unreachable` (422) | inverse kinematics cannot reach one or several cells, which are listed in the `detail` |
| `torque_off` (409) | torque is off |
| `busy` (409) | a plan is already running |

The web page shows that `detail` and starts **no** animation: a rejected plan must never
look like a successful seeding.

Progress through `WS /robot/progress`, one JSON per event:

| `type` | Fields | What the web page does |
|---|---|---|
| `plan_started` | `total` | Shows the seeding panel |
| `cell_started` | `cell_index`, `row`, `col`, `color` | The square blinks |
| `drop_pose` | `cell_index`, `target`, `reached`, `error_mm`, `corrections` | Before opening the gripper: shows "Soltado a N mm del hueco" (the web page ignores types it does not know) |
| `cell_done` | `cell_index`, `message`, `empty` | Marks ✓ and advances the bar; with `empty` it warns that the gripper seemed empty |
| `cell_failed` | `cell_index`, `message` | Marks a red ✕ and counts it separately. The executor no longer emits it (a cell with an empty gripper is completed anyway); the web page still understands it |
| `finished` | `message` | Closes the seeding as finished |
| `stopped` | `message` | Closes the seeding as stopped |
| `error` | `cell_index`, `message` | Shows the robot's error |

A client that connects in the middle of a plan receives it from the beginning, so
reloading the web page during seeding does not lose the progress.

**Detection freezes while seeding.** When **Sembrar** is pressed, `scanner.freeze()` saves
the cell centers and the image size: the plan is built from that snapshot, and no more
`POST /vision/tray` requests are sent nor are the cells repositioned until the seeding
finishes, fails, is stopped or the plan is rejected (`unfreeze()`). The cells stay where
they were marked. The resources in `web/index.html` carry `?v=` to bypass the browser
cache when publishing changes.

**Without a backend** (the web page published on GitHub Pages) the `POST` fails over the
network and the interface simulates the seeding with the **MODO DEMO** ("DEMO MODE") label
clearly visible. If the backend does respond but the tray has not been scanned, the web
page refuses to seed and asks to scan: without pixels there is no position to take the arm
to.

## Next steps

### 1. Hardware and scene (Friday)
- [x] Assemble the leader and the follower and calibrate them (done on Friday 23).
- [ ] Check that teleoperation works well, gripper included.
- [ ] Get the balls and one bowl per seed color you are going to use (see [Scene and objects](#scene-and-objects)).
- [ ] Mark on the table the tray's **work area** and the area of each bowl: they can be
      moved within their area.
- [ ] Place the overhead camera (`top`), which sees the whole work area and the box
      areas, and the arm camera (`wrist`). **The cameras and the robot are not moved again.**
- [ ] Test with teleoperation that a ball is picked up from each box and released in a
      cell.

### 2. Interface (Friday-Saturday)
- [x] Cinema-style cell grid, with configurable size.
- [x] Custom seeds (name + emoji + box color, in `localStorage`) and a "fill everything with one color" button.
- [x] Save and load templates, and automatically load the last formula used.
- [x] **Sembrar** button that sends the plan to the backend, with a progress view and **Parar** ("Stop").
- [x] Overhead camera image with the **detected** grid superimposed.
- [x] A rejected plan shows the reason and animates nothing; without a backend, demo mode is marked.
- [x] Camera-robot calibration from the browser and an **Ajustes** panel with release
      height and half tests (**Probar coger** / **Probar dejar**).
- [x] No internet needed: typefaces and `js-aruco2` served from `web/`, not from a CDN.
- [x] Interface smoke test in jsdom, Chromium capture and a walkthrough with a fake camera.
- [ ] Warning if the tray ends up outside the arm's work area (today the backend detects it
      on receiving the plan, with `code: "unreachable"`, and the web page shows the reason).

### 3. Backend and robot connection (Saturday)
- [x] Local server (FastAPI + WebSocket) with the endpoints `POST /plan`, `POST /stop`,
      `WS /robot/progress`, poses, calibration, torque and state.
- [x] Marker-free tray detection → cell centers in pixels, with already occupied
      cells marked.
- [x] Kinematics with `lerobot[kinematics]` and the SO-101 URDF vendored in the repo.
- [x] Executor of the [seeding sequence](#seeding-sequence): pickup with policy or
      with taught poses, closed-loop corrected release, interpolated movement,
      validation of the whole plan before moving and safe stop (**Stop** keeps
      torque on).
- [x] `grasp` / `place` modes and per-plan `drop_z` to debug half a sequence.
- [ ] Check that forward kinematics matches the arm's real position.
- [ ] Teach with the leader `act_start`, `home` and the position above each bowl without a
      policy.
- [ ] Camera-robot calibration (pixel → robot x, y homography).
- [ ] Release by inverse kinematics and **measure the error** with a 10-cell test.
- [ ] Tune the detection with more frames of the real tray.
- [ ] Saturday at noon: decide between free tray or plan B (taught corners).

### 4. Data and policy (Friday night-Saturday)
- [x] Test batch: about 10 episodes, train a few steps and check that it learns
      before recording everything.
- [x] Policy for the first bowl trained and published on the Hub, plugged into the executor
      (`SMARTSEED_ACT_POLICIES`).
- [x] Clean grasp datasets on the Hub (10 s episodes, task `grasp the seed below the
      gripper`, tag `BraboRobots`): `RafaelJaime/smartseed-grasp-d1-clean` (96 episodes,
      from `smartseed-grasp-d_20261025_002427` without 1, 15, 26 and 34) and
      `smartseed-grasp-d2-clean` (91, from `smartseed-grasp-d_20261025_010641` without 0-4, 18, 66,
      84 and 96).
- [x] Four ACTs trained on Brev (2 H100s, one per GPU): `act-smartseed-d1-c100`, `-d1-c50`,
      `-d2-c100`, `-d2-c50` (c50 = `chunk_size` and `n_action_steps` 50), 40,000 steps, batch 32,
      checkpoints every 10,000 on the Hub. By default: black (Tomate) → `d1-c100`, white
      (Pimiento) → `d2-c100`.
- [ ] In progress: `act-smartseed-d1-c100-80k`, `d1-c100` resumed from its 40k checkpoint
      (with the optimizer) up to 80k on one H100 (`scripts/brev/resume.sh`).
- [ ] Test with the real arm which model and checkpoint seeds best (selector in **Ajustes**).
- [ ] Review `act_start`: the taught one has `wrist_flex` ≈ 72° and the d1/d2 episodes
      start around 47°.
- [ ] Record **~50 episodes of 20 s per color** with `lerobot-record`: each episode goes from
      `home` to the bowl of that color, picks up a seed and comes back. **Both bowls on the
      table and swapped around** between episodes, and some lighting variation.
- [ ] Upload the datasets to the Hugging Face Hub with the team's tags.
- [x] Train the ACT for the second color (`d2-c100`).
- [ ] Teach `act_start` with the real arm and check the whole cycle cell by cell.
- [ ] Write down the failures of each iteration and how they were fixed in `odd/tasks/`.

### 5. Demo and submission (Sunday before 13:00)
- [ ] Fix the **demo task** and rehearse it until it works 5 times in a row without touching
      the robot.
- [ ] Record the **video of 1 minute at most**: problem → interface → robot seeding →
      result, and upload it to the [Drive folder](https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n).
- [ ] Publish the datasets on Hugging Face (+3) with the `BraboRobots` tag and link them here.
- [ ] Leave the repository reproducible (+2): recording, training and
      rollout commands, and the configuration used.
- [ ] Prepare the presentation and the answers to the jury's most likely questions
      (data, failures and iterations, usefulness).

## Repository structure

```
web/                        interface (the Pages site root redirects here)
  index.html                markup: scan screen, map, seeding panel and settings
  app.css                   all the styles
  app.js                    custom seeds, map, templates and seeding against the backend
  scanner.js                live camera, grid and tray localization
  calibrate.js              camera-robot calibration from the browser
  vendor/                   js-aruco2 (cv.js, aruco.js) served from the repo
  fonts/                    DM Sans and Manrope, local, no Google Fonts
  README.md                 interface notes
tests/web/                  interface smoke test (jsdom), capture and camera in Chromium
backend/                    local service (FastAPI): vision and robot control
  smartseed_vision/         geometry.py, detector.py, depth.py, occupancy.py, app.py
  smartseed_robot/          robot.py, kinematics.py, calibration.py, poses.py,
                            motion.py, act.py, catalog.py, executor.py, api.py
  assets/so101/             SO-101 URDF and meshes for the kinematics (+ SOURCE.md)
  tests/                    pytest with synthetic trays and depth, photos of the real
                            tray in fixtures/ and a fake robot
  run.sh                    starts at http://localhost:8000
  pyproject.toml            dependencies (lerobot pinned to commit e595b79)
scripts/stack.sh            real backend + web in one command, for the demo
scripts/brev/               ACT training on Brev: train_pair.sh, resume.sh, watch_one.sh
odd/tasks/                  task documents per feature, with the evidence of each iteration
.github/workflows/pages.yml old deployment of web/ (see CLAUDE.md, "GitHub Pages")
index.html                  redirect from the Pages root to web/
README.md                   resolved criteria and steps to reproduce the result
guide.md                    this document: idea, architecture and plan
CLAUDE.md                   guide for agents and collaborators
```

## Automated tests

Everything runs **without the arm and without cameras**: the fake robot, the synthetic
images and the simulated policies stand in for the hardware, so anyone can clone the repo
and check that it works.

**Backend** (`cd backend && uv run pytest`): 177 test functions in 14 files.

| File | What it checks |
|---|---|
| `test_geometry.py` | corners and row × column count on synthetic trays: rotated, dark, light and cardboard |
| `test_depth.py` | cells as basins: one per compartment, row ordering, cells outside the tray discarded, a depression open to the edge is not a cell |
| `test_occupancy.py` | occupied cells against the tray edge, with the real photos (empty and with stones) |
| `test_detector.py` | selection of the best OWLv2 box and cropping to the image size |
| `test_app.py` | `/health`, `/vision/tray`, CORS and Private Network, and that the models never run at the same time on the GPU |
| `test_robot.py` | `FakeRobot`: torque, partial commands, history, full or empty grasp |
| `test_kinematics.py` | forward kinematics against the URDF, IK round trip, and that the gripper points as far down as possible |
| `test_calibration.py` | homography fit, error, pixel rescaling and persistence |
| `test_poses.py` | valid names (custom colors included), missing poses, persistence and corrupt file |
| `test_motion.py` | interpolation with speed limit and stop within one control step |
| `test_act.py` | configuration from the environment, lazy per-color loading and cancelable closed loop |
| `test_catalog.py` | catalog of models and checkpoints from the Hub, cache and download of intermediate checkpoints |
| `test_executor.py` | the two pickup routes, `grasp`/`place` modes, release with correction, an empty cell that is completed anyway, `busy` and `stop` |
| `test_robot_api.py` | API contract: state, poses, calibration, rejected plans with their `code`, WebSocket events |

**Interface** (`cd tests/web && npm test`): the smoke test actually loads `web/index.html`
in jsdom and drives it, in two passes:

- **without a backend**: seeding is simulated and **MODO DEMO** is shown, and nothing is sent.
- **with the simulated robot**: the plan that goes out has exactly the shape of
  `smartseed_robot`, progress arrives over WebSocket and paints each square, and a rejected
  plan (`unreachable`, `torque_off`, `busy`) shows the reason without animating anything.

In addition: `npm run render` opens the page in a real Chromium at desktop and mobile
size, saves screenshots to `tests/web/shots/` and fails on console errors or horizontal
overflow; `npm run camera` walks through the whole scan with Chromium's synthetic camera.
Both need `CHROME_PATH` pointing to an installed Chromium.

## Trying the web page

Open `web/index.html` in the browser. It needs no build or server, and it works
without internet: the typeface and `js-aruco2` are inside `web/`.
It is published on GitHub Pages: <https://alvaromoli13.github.io/Robotluces/> (the root
redirects to `web/`). Pages is in *deploy from branch* mode (`main`, root folder), so
**every push to `main` publishes the whole repository**, not just `web/`: do not push
anything private.

There is a smoke test that actually loads the page and drives it:

```bash
cd tests/web
npm install     # first time only (jsdom and puppeteer-core, for the tests only)
npm test        # 2 passes: without a backend (demo mode) and with the simulated robot
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
CHROME_PATH="..." npm run camera   # Chromium fake camera: scan and map over the video
```

`npm test` checks the behavior: map, templates, resizing, the plan that is sent (its exact
shape, that of `smartseed_robot`), progress over WebSocket, the rejected plan and demo
mode. `npm run render` opens the page in a real Chromium at desktop and mobile size, saves
screenshots to `tests/web/shots/` and fails on console errors or horizontal overflow.
`npm run camera` walks through the whole scan with Chromium's synthetic camera.

## Safety

The published web page does not control the robot. Only the local backend, on the event
network, can move the arm. Always keep the follower's power cable at hand the first time
you try each change.
