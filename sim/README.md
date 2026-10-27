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
| `run_policy.py` | closed-loop real-trained ACT in the twin: obs like `act.py`, success = seed lifted > 3 cm, mp4 + PNG strip per policy |
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

## Running the real ACT in sim (T3)

```bash
backend/.venv/bin/python sim/run_policy.py --repo RafaelJaime/act-smartseed-d1-c100 --color black     # 10 episodes, 10 s
backend/.venv/bin/python sim/run_policy.py --repo RafaelJaime/act-smartseed-d2-c50 --color white --checkpoint <step>
backend/.venv/bin/python sim/run_policy.py --obs-compare real_top.png real_wrist.png --color white   # sim-vs-real frame
```

The loop mirrors `ActGrasp.run`: the arm starts at the taught `act_start` (`config/poses.json`), each 1/30 s of
simulated time the policy gets `read_observation()` (`observation.state` float32 in degrees with the gripper 0-100,
`observation.images.top` / `.wrist` 480x640 RGB uint8) and its action goes out through `send_joints` (same clamp as the
follower). The model loads through `resolve_spec` + `LeRobotActPolicy`, so normalisation and action-chunk handling are
lerobot's (MPS when available). Differences from the real run: no inference latency, exactly 30 fps of sim time, the
twin's images. Each episode jitters every seed of the colour by up to +-5 mm in x and y (fixed seed 0, so a run is
reproducible). Success: any seed of the colour rose more than 30 mm above its resting height at any time. Also
reported: max lift, closest tool-to-seed distance, final gripper reading, whether a seed ended within 20 mm of the tool
frame ("in jaws"). Videos (all 10 episodes, top | wrist = what the policy sees): `sim/out/act_<name>.mp4` (git-ignored);
PNG strips of episode 0 (top over wrist, t = 0, 2, 4, 6, 8, 10 s): `docs/media/sim-act-<name>.png`.

Results, 10 episodes each, nothing tuned toward the policies (`shoulder_lift` range widened to the real follower's
-103 rest first, see `assets/README.md` change 5):

| Policy (colour) | Success | Max lift (mean / best) | Closest tool-seed (min / mean) | Final gripper (mean) | In jaws at end | Behaviour |
|---|---|---|---|---|---|---|
| `act-smartseed-d1-c100` (black) | 0/10 | 0 / 0 mm | 19 / 29 mm | 12.3 | 0/10 | goes to the black box and hovers over the seeds with the jaws half open, never closes on one |
| `act-smartseed-d1-c100-80k` (black) | 1/10 | 12.9 / 114.8 mm | 8 / 13 mm | 17.1 | 0/10 | reaches into the box, moves seeds by 1-5 mm; episode 2 closed on seed 0 (reading 7.0-7.6, the real holding value), lifted it to 11.5 cm and carried it for 0.8 s, then opened and dropped it |
| `act-smartseed-d2-c100` (white) | 0/10 | 0 / 0.1 mm | 39 / 46 mm | 23.9 | 0/10 | goes to the white box, wrist camera hovers over the seeds, gripper wide open, no descent to the floor |
| `act-smartseed-d2-c50` (white) | 0/10 | 0 / 0 mm | 36 / 39 mm | 15.2 | 0/10 | same approach, closer to the box wall, no grasp |

Reading: the policies recognise the box of their colour from the rendered images and move there, so the top camera,
joint units and action path work. The d1 policies, whose black seeds on a cardboard floor are the highest-contrast
target, get within 8-30 mm; the white-seed policies stay 36-47 mm away. The visual gap (flat colours, no WOWROBO print,
no seed highlights, different wrist-camera exposure and mount; the real wrist view at t = 0 shows a grey mat and a cardboard edge, the twin a darker mat;
`docs/media/sim-vs-real-obs.png`) is the most likely reason they do not commit to a grasp, but this run does not
isolate it from the physics, seed layout (the real box held 2 white seeds, the twin has 4) or the missing inference
latency. One episode in 40 is not a measured rate; the lone success is a genuine grasp-and-lift that did not hold.

## What is weak

- **Grasping** is limited to what `grasp_test.py` covers: vertical approach, seeds clear of walls and neighbours. Black seed 3 (near the box corner) fails 0/20 (the spun-wrist IK does not reach it), white seed 3 19/20. Pad friction, squeeze torque and seed size are tuned to the real readings, not measured.
- **Real calibration vs the camera.** The four clicks in `backend/data/calibration.json` miss the fitted camera by
  28-60 px (several cm) at any single tool height; the best single height is 0.12 m. Likely lens distortion (the
  pinhole fit is exact on the arm, where the camera was fitted) and clicks at varying heights. That is why sim mode
  ships its own self-consistent `config/calibration.json` instead of the real one.
- No lens distortion, no motion blur, no real textures: expect a visual gap for a policy trained on real images.
- Servo dynamics untuned; torque off holds instead of going limp.
