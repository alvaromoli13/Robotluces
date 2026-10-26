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

## Measured, fitted, estimated

| Quantity | Value | How |
|---|---|---|
| Arm kinematics | tool site = `Kinematics.tool_xyz` | MEASURED: max 0.0016 mm over the 300 states of episode 0 (same URDF family) |
| Arm joint map | MJCF rad = deg2rad(lerobot deg) | MEASURED by the FK check above, zero offsets confirmed |
| Gripper map | jaw rad = -0.1954 + 0.02244 * g (g in 0-100) | slope MEASURED from the follower calibration (2034..3497 ticks = 128.6 deg per 0-100); offset FITTED on the wrist frames (chamfer 1.98 px). Without the span fixed the fit drifts to an unphysical 1.9 deg per unit |
| Gripper limits | closes at g = 6.0, saturates near 87 | the real follower reads about 6 fully closed (episode minimum), emulated with the jaw joint stop because the jaw hulls cannot collide |
| Table height | -0.011 m in the base frame, mat top -0.008 | MEASURED from FK: the recorded grasp closes with the tool frame at z = -0.0003 on a seed on the box floor; the taught `home` is at -0.011. The base origin sits ~1 cm above the table |
| Top camera | pos (0.2998, -0.0216, 0.4997), fovy 56.18 deg, yaw -8.9 deg, tilt about 0 | FITTED: arm silhouette chamfer over 22 frames of episode 0, 4.9 px (both directions summed); yaw 0 would be 9.0 px |
| Wrist camera | on the `gripper` body, fovy 77.85 deg | FITTED with the red jaw masks over frames with g from 6 to 30, 1.98 px; the camera mount is the upstream mount, the real one may differ |
| Mat, tray, boxes | sizes and centres in `layout.py` (board frame rotated by the camera yaw) | ESTIMATED: pixels read by eye off `act_white_top.png` and back-projected with the fitted camera at their known heights (about +-3 mm reading error). Tray 19.2 x 15.0 cm, 3 columns x 4 rows. Mat bottom edge is hidden, guessed |
| Heights (tray 4.5 cm, boxes 3.5 cm, wall 3-4 mm) | | ESTIMATED |
| Seeds | black r 5 mm, 4 per box; seed 0 sits at the recorded grasp point (0.150, -0.132) | positions MEASURED for 2 per colour from the frame, the others ESTIMATED; sizes ESTIMATED from the wrist frames (white seeds look bigger, about 7 mm radius, not modelled) |
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

## What is weak

- **Grasping.** Seeds are 10 mm spheres against convex-hull jaw meshes. A jaw closing on a seed does not hold it
  reliably (the jaw closes to the empty value 6.0 where the real one stops at about 12 on a black seed). Do not
  trust pick success in sim yet; fix by primitive jaw collision geoms and tuned friction/solref.
- **Real calibration vs the camera.** The four clicks in `backend/data/calibration.json` miss the fitted camera by
  28-60 px (several cm) at any single tool height; the best single height is 0.12 m. Likely lens distortion (the
  pinhole fit is exact on the arm, where the camera was fitted) and clicks at varying heights. That is why sim mode
  ships its own self-consistent `config/calibration.json` instead of the real one.
- No lens distortion, no motion blur, no real textures: expect a visual gap for a policy trained on real images.
- Servo dynamics untuned; torque off holds instead of going limp.
