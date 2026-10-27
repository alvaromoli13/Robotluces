# SmartSeed MuJoCo twin

MuJoCo replica of the arm, mat, 3x4 seedling tray, white and black seed boxes and the two cameras, behind the
backend `RobotPort` contract (`SMARTSEED_ROBOT=sim`). Plan and research: `../docs/simulation.md`.

## Run it

```bash
cd backend && uv sync                      # mujoco + imageio are in the default `sim` uv group
SMARTSEED_ROBOT=sim ./run.sh               # backend on 127.0.0.1:8000, no arm, no camera
SMARTSEED_ROBOT=sim ../scripts/stack.sh    # plus the web on :8080 (SMARTSEED_ACT_POLICIES=... to run ACT)
SMARTSEED_SIM_RECORD_DIR=out/videos ...    # one plan-<id>.mp4 of the top camera per plan
SMARTSEED_SIM_VIEWER=1 ...                 # live window; macOS needs mjpython, run.sh switches to it
```

Headless rendering works on macOS: `mujoco.Renderer` (CGL) gives 640x480 frames, also from non-main threads (one
renderer per thread). Simulated time advances one 1/30 s control period per `send_joints` (10 physics substeps);
the executor's own 30 Hz sleeps make plans run in real time. Torque off holds the arm still (no limp arm).

## Files

| File | What |
|---|---|
| `layout.py` | every scene constant, tagged MEASURED / FITTED / ESTIMATED; `python -m sim.layout` regenerates `scene.xml` (a test fails if they disagree) |
| `scene.xml` | generated MJCF: includes the vendored arm, adds table, mat, tray, boxes, seeds, lights, `top` camera |
| `assets/` | vendored SO-101 MJCF + meshes with license and provenance (`assets/README.md`), incl. the `wrist` camera |
| `config/` | `calibration.json` + `poses.json` for sim mode (`python -m sim.make_config`) |
| `export_episode.py` | dumps a recorded LeRobot episode to `out/ep0.npz` (run it with a lerobot interpreter) |
| `fit_top_camera.py`, `fit_wrist_camera.py` | camera fits against real frames, print the constants |
| `measure_layout.py` | back-projects pixels read off the real top frame to metres |
| `replay.py` | replays the episode, prints residuals, writes `out/replay_overlay.png` |
| `grasp_test.py` | scripted IK grasp by contact physics, N jittered trials per colour, mp4 + PNG strip of a success |

## Measured, fitted, estimated

| Quantity | Value | How |
|---|---|---|
| Arm kinematics | tool site = `Kinematics.tool_xyz` | MEASURED: max 0.0016 mm over the 300 states of episode 0 (same URDF family) |
| Arm joint map | MJCF rad = deg2rad(lerobot deg) | MEASURED by the FK check above, zero offsets confirmed |
| Gripper map | jaw rad = -0.1954 + 0.02244 * g (g in 0-100) | slope MEASURED from the follower calibration (2034..3497 ticks = 128.6 deg per 0-100); offset FITTED on the wrist frames (chamfer 1.98 px). Without the span fixed the fit drifts to an unphysical 1.9 deg per unit |
| Gripper limits | closes at g = 6.0, saturates near 87 | the real follower reads about 6.0 closed empty (d1 start 6.09): its hard stop, the joint limit here. The pads are 10.9 mm apart at the tip there |
| Table height | -0.011 m in the base frame, mat top -0.008 | MEASURED from FK: the recorded grasp closes with the tool frame at z = -0.0003 on a seed on the box floor; the taught `home` is at -0.011. The base origin sits ~1 cm above the table |
| Top camera | pos (0.2998, -0.0216, 0.4997), fovy 56.18 deg, yaw -8.9 deg, tilt about 0 | FITTED: arm silhouette chamfer over 22 frames of episode 0, 4.9 px (both directions summed); yaw 0 would be 9.0 px |
| Wrist camera | on the `gripper` body, fovy 77.85 deg | FITTED with the red jaw masks over frames with g from 6 to 30, 1.98 px; the camera mount is the upstream mount, the real one may differ |
| Mat, tray, boxes | sizes and centres in `layout.py` (board frame rotated by the camera yaw) | ESTIMATED: pixels read by eye off `act_white_top.png` and back-projected with the fitted camera at their known heights (about +-3 mm reading error). Tray 19.2 x 15.0 cm, 3 columns x 4 rows. Mat bottom edge is hidden, guessed |
| Heights (tray 4.5 cm, boxes 3.5 cm, wall 3-4 mm) | | ESTIMATED |
| Seeds | black r 6.8 mm, white r 7.4 mm, 1 g, 4 per box; black seed 0 sits between the pads of the recorded grasp (0.156, -0.136) | positions MEASURED for 2 per colour, the others ESTIMATED (black extras moved off the walls); radii ESTIMATED so the jaw reading on a seed matches the real one (see Grasp physics). Mass is inflated from a few tenths of a gram: contact stiffness in MuJoCo scales with the lighter body, 0.5 g let the jaw squeeze 1.7 mm into the seed |
| Colours, lighting, textures | flat colours, one directional light | ESTIMATED; no "WOWROBO" print, no lens distortion |

## Replay residual (episode 0 of `RafaelJaime/smartseed-grasp-d1-clean`)

`backend/.venv/bin/python sim/replay.py`:

- Kinematic replay (recorded `observation.state` into the sim, 300 states): sim tool vs `Kinematics.tool_xyz`
  **mean 0.0014 mm, max 0.0016 mm**.
- Top-camera overlay (`out/replay_overlay.png`, real | sim | sim arm outline on the real frame): arm silhouette
  chamfer **5.5 px mean, 4.9 px median** over 30 frames (about 5 mm at the arm's height).
- Dynamic replay (recorded `action`s through `SimRobot`, so clamp, servo lag, gravity): mean joint error 1.1-3.6 deg
  per joint, tool position error **mean 15.7 mm, max 75.7 mm**. The servo gains are the upstream STS3215 ones and
  were not tuned against a real step response.

Note: episode 0 was recorded with the tray turned 90 degrees (4 columns x 3 rows) and the camera a few pixels off
the final setup, so the overlay's static scene differs; the scene follows the final 3x4 frame.

## Grasp physics (T2b)

Real data (d1-clean 96 episodes, d2-clean 91): the follower reads about 6.1 closed empty, 6.9 holding a black seed,
7.4 holding a white one (the recorded action goes to about 4.8, so the servo squeezes). The jaw mesh explains it:
the MJCF joint stop (g = 6.0) is a hard stop, not jaw contact, and the pads are 10.9 mm apart at the tip there.
A 12-13 mm seed therefore holds the jaw off the stop by 0.9-1.4 units, with no weld or attach.

- Two fingertip pad boxes carry all jaw-seed contact (`sim/assets/README.md`, change 4); the moving-jaw hull no longer
  collides (its nib dragged the box floor). Box floors are 1.5 mm cardboard, so a seed centre sits at the measured tool z.
- Gripper servo: kp 3, kv 0.3, force limit 0.15 N m. A stiff, strong servo squeezes a light seed through the pads, a
  weak one cannot close, a lightly damped one rings.
- Seeds: friction 1.2, condim 4, mass 1 g, radii 6.8 / 7.4 mm (ESTIMATED from the readings and from the wrist frames).
- Scripted grasp (`grasp_test.py`): above the seed, descend until the tool z is the seed centre, close until the
  reading stops, lift 5 cm, hold 2 s. The jaws open along the radial line, or along the board axis that clears walls and
  neighbours, with the wrist spun by `Kinematics.solve(spin_deg=...)`. The planner aims at the nominal seed position
  while the seed is displaced by up to 3 mm.

Results (`backend/.venv/bin/python sim/grasp_test.py`, seed 2 of each box, +-3 mm placement error):

| | trials | success | lift | slip | reading while holding (real) |
|---|---|---|---|---|---|
| black | 100 | 100 | 50.0 mm | under 1 mm | 6.88 (6.93) |
| white | 100 | 100 | 49.8 mm | under 1 mm | 7.44 (7.37) |

+-5 mm error: 40/40 per colour. Other seeds, 20 trials: black 0, 1 20/20, black 3 0/20; white 0, 1 20/20, white 3 19/20.
Replay of the recorded actions of episode 0 (black seed 0): the seed is lifted and carried off with the arm (sim
reading 6.7-6.9 against 7.1-7.2 recorded). Strips: `docs/media/sim-grasp-black.png`, `sim-grasp-white.png`.

## What is weak

- **Grasping** is limited to what `grasp_test.py` covers: vertical approach, seeds clear of walls and neighbours. Black seed 3 (near the box corner) fails 0/20 (the spun-wrist IK does not reach it), white seed 3 19/20. Pad friction, squeeze torque and seed size are tuned to the real readings, not measured.
- **Real calibration vs the camera.** The four clicks in `backend/data/calibration.json` miss the fitted camera by
  28-60 px (several cm) at any single tool height; the best single height is 0.12 m. Likely lens distortion (the
  pinhole fit is exact on the arm, where the camera was fitted) and clicks at varying heights. That is why sim mode
  ships its own self-consistent `config/calibration.json` instead of the real one.
- No lens distortion, no motion blur, no real textures: expect a visual gap for a policy trained on real images.
- Servo dynamics untuned; torque off holds instead of going limp.
