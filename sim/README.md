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
| `collision.py` | wall pass-through detector: per physics step, arm-geom vs box/tray-wall contacts (max penetration, max force, count); a `geometry` mode for scenes whose jaws did not collide (v1) |
| `audit_walls.py`, `wall_check.py` | replay the kept episodes of a generation log and measure wall overlap (the v1 audit); the v1-vs-v2 close-up `docs/media/sim-wall-check.png` |
| `eval.py` | T5 metric: a policy on held-out generator scenes (seed 1000, `--layout wide|narrow`, `--planner` for the scripted ceiling), success = target-colour seed lifted > 3 cm, mp4 of the first 5 episodes to `out/eval/` |
| `scan_layout.py` | planner acceptance of candidate narrow-layout ranges (planning only), the evidence behind `--layout narrow` |
| `make_dataset.py` | scripted demos with randomised scenes -> LeRobotDatasets in the real schema, Hub push, previews (see "Generating sim datasets") |

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

- Two fingertip pad boxes carry all jaw-seed contact (`sim/assets/README.md`, change 4); the moving-jaw hull does not
  touch seeds or floors (its nib dragged the box floor) but, since T4b, it does hit walls. Box floors are 1.5 mm cardboard, so a seed centre sits at the measured tool z.
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
T4b (solid walls), same 20 trials, +-3 mm, `grasp_test.py --index N`, before = v1 checkout, after = this one:

| seed | black before / after | white before / after |
|---|---|---|
| 0 | 20/20 / **0/20** | 20/20 / 20/20 |
| 1 | 20/20 / 20/20 | 20/20 / 20/20 |
| 2 (the 100-trial rows above) | 20/20 / 20/20 | 20/20 / 20/20 |
| 3 | 0/20 / 0/20 | 19/20 / 19/20 |

Black seed 0 is the one change: its nominal spot is 13 mm from the box wall, no jaw axis clears it (the closest
passes 0.4 mm into it) and v1 only grasped it by flying the open jaw through the wall. The trial now prints the wall
penetration and force of every run; a grasp with no wall contact is asserted for seed 2 of both colours.

Replay of the recorded actions of episode 0 (black seed 0): the seed is lifted and carried off with the arm (sim
reading 6.7-6.9 against 7.1-7.2 recorded). Strips: `docs/media/sim-grasp-black.png`, `sim-grasp-white.png`.

## Collision model (T4b)

The v1 demos had the gripper pass through seed-box walls: the moving-jaw hull had `contype="0"` and the pads only
touched seeds, so only the fixed jaw and the arm links ever hit a wall, and (see "Moved walls" below) not even those
once a box had been moved. v2 gives walls their own collision bit:

| Geoms | contype | conaffinity | Collide with |
|---|---|---|---|
| walls and dividers of the boxes and the tray (class `wall`) | 2 | 19 (1+2+16) | the arm hulls, both jaws, seeds; stiff (`solref 0.004`, `priority 1`: their contact parameters win over the arm's soft defaults) |
| fixed-jaw hull, wrist, links (`collision` class) | 1 | 0 | walls and floors, not seeds, not each other |
| moving-jaw hull | 16 | 0 | walls only |
| fingertip pads | 24 (8+16) | 0 | seeds (bit 8) and walls (bit 16), not floors |
| box and tray floors (`env`) | 2 | 3 | the arm hulls, seeds |
| table, paper, mat (`ground`) | 4 | 2 | seeds only (the arm passes through: the arm rests its jaws on the table at `home`) |
| seeds | 2 | 10 | pads, walls, floors, ground, seeds |

So every jaw geom (fixed hull, moving hull, both pads) and every other arm geom stops at every box and tray wall,
rims included (the rim is the top face of the wall box). The floors, mat and table stay non-solid for the jaws: the
moving hull's nib dragged on the 1.5 mm box floor (T2b) and the pads and the home pose sit at or below those surfaces.
A jaw driven 4 cm through a box wall is stopped within 0.4 mm (30-40 N of servo push, test
`test_a_tool_pushed_through_a_box_wall_is_stopped_by_it`). The moving hull is MuJoCo's convex hull of an L-shaped part,
so it is a conservative proxy: it can touch a wall slightly before the real jaw would.

**Moved walls.** The generator moves and turns the boxes and the tray per episode. MuJoCo builds the static broad phase
when the model is compiled, so editing `geom_pos` of a static geom at run time left its collisions at the nominal spot
(a pose with the tool 7 mm inside a moved wall produced no contact at all). Each movable object is now its own body
(`tray`, `box_white`, `box_black`, geoms relative to it) and `apply_scene` sets `body_pos` / `body_quat`, which the
broad phase honours (`test_walls_that_the_scene_moved_still_collide_with_the_arm`). That bug also means the v1 physics
had no wall collisions at all for moved boxes.

**Validity** (`collision.WallMonitor`, a step hook on `SimRobot`): after every physics step it reads the contact list for
arm-geom vs wall-geom pairs (all links, both hulls, both pads; every box and tray wall) and records the deepest `-dist`,
the largest normal force (`mj_contactForce`) and the number of steps in contact. An episode is kept only if the seed
was lifted over 3 cm and is in the jaws at the end AND the deepest wall penetration is at most 1 mm AND no wall
contact pushed with more than 2 N. A `geometry` mode asks `mj_geomDistance` for the signed distance of every arm geom
to every wall geom after each control step regardless of the collision bits; `audit_walls.py` uses it on the v1 scenes.

**Planner.** `grasp_test.grasp_candidates` lists the jaw axes (radial, plus the 24 board axes turned with the box) whose
open-jaw footprint clears the walls and the neighbouring seeds by more than 5 mm, smallest wrist roll first.
`make_dataset.plan_actions` plans the whole episode for the first axis, then `check_path` puts the arm at every commanded
pose (forward kinematics, no physics), measures its distance to every wall of that scene and requires 5 mm from the
descent to the end of the lift and at the still poses (start and fold), and 2 cm for the moving transit and retract
(or no closer than the still poses already were: a box beside the base puts the folded arm within 2 cm of its wall
before any motion). The hover at tool height 7 cm and the vertical descent keep the jaw above the 3.5 cm walls until it is
over the seed. If an axis fails, the next one is tried; if none passes the scene is redrawn (`NoFit`, a placement
rejection counted separately from out-of-reach ones).

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

## Generating sim datasets (T4, collision-valid since T4b)

```bash
backend/.venv/bin/python sim/make_dataset.py --color black --episodes 100 --seed 0 --push-repo RafaelJaime/smartseed-sim-grasp-black-v2
backend/.venv/bin/python sim/make_dataset.py --color white --episodes 100 --seed 0 --push-repo RafaelJaime/smartseed-sim-grasp-white-v2
backend/.venv/bin/python sim/make_dataset.py --coverage docs/media/sim-dataset-coverage.png   # redraw from the logs
backend/.venv/bin/python sim/make_dataset.py --videos sim/out/v2_videos                         # mp4 of the first 5 episodes per colour
```

Datasets go to `sim/out/datasets/smartseed-sim-grasp-<colour>-v2` (a stopped run resumes; running it again with
`--push-repo` uploads). **v2 replaces v1**, which was withdrawn and deleted from the Hub (repos `smartseed-sim-grasp-black` / `-white`): v1 episodes let the
gripper pass through box walls (see "Collision model (T4b)"; replaying the 100 kept episodes of each v1 dataset with
`audit_walls.py`, **24 % of the black and 37 % of the white ones** have an arm geom more than 1 mm inside a wall, 19 % / 26 %
more than 5 mm, up to 22 / 25 mm; 4 % / 9 % of them in the grasp itself, the rest with the folded arm or the transit
inside a wall of a box placed near the base). The v1 generator is in git history (commit `874e274`, the last one before the
T4b wall fixes: `git worktree add ../Robotluces-v1 874e274`); do not train on v1 data.

Scripted demonstrations recorded with `LeRobotDataset.create` / `add_frame` / `save_episode` (lerobot at the pinned
commit `e595b79`; `lerobot[dataset]` is now part of the backend dependencies). The schema is the real one, key for key:
`sim/config/real_features.json` is `meta/info.json` of `smartseed-grasp-d1-clean` and `-d2-clean` (identical in both)
and a test compares the generator's features against it. Same task string, 30 fps, `robot_type` `so_follower`,
codebase `v3.0`, AV1 video, `observation.state` and `action` float32 degrees (gripper 0-100), `observation.images.top` and
`.wrist` 480x640x3. `action` is the commanded (leader) target, `observation.state` what the simulated follower measured
before it.

**One episode** follows the real ones (their action traces: rest at `act_start`, open while moving over a seed, descend,
close, then fold back to the rest pose *with the seed in the jaws* and hold until the 300 frame cap; real length 278-300,
mean 288): idle 24-45 frames, joint-space transit while the gripper opens (18-31), Cartesian descent with `Kinematics.solve`
(the wrist is spun so the jaws clear the walls, `grasp_test.grasp_pose`), settle, close (command 4.2-5.0, the seed stalls
the jaw at ~7), 7 cm lift, min-jerk joint move to the folded rest pose (lift -103, elbow 97, wrist -80..-100, pan 3..13,
as in the real episodes). Min-jerk with a random speed skew per phase, random phase lengths, a 0.25 deg hand wobble outside
the grasp and a 1.5 mm aiming error. Frames per episode 272-300. Success = the grasped seed rose over 3 cm and is
within 2 cm of the tool at the end (held through the fold); failures are discarded and logged.

**Randomisation** (all bounds in `Randomisation` in `make_dataset.py`; seeded by `(seed, attempt, colour, resample)`, so a
dataset is a function of `(colour, seed)` and a stopped run resumes where it stopped):

| What | Range |
|---|---|
| Black box, white box, 3x4 tray | uniform position anywhere on the table area the top camera sees, any yaw, no overlap (1 cm gap), 1.5 cm inside the view, centre within 36 cm of the arm and 10 cm clear of its base; placements the planner cannot grasp in are redrawn |
| Seeds | 2-4 per box (the box keeps its colour), uniform on the floor 22 mm off the inner walls, at least 25 mm apart; one of the colour's seeds is grasped |
| Light | ceiling light and headlight x0.7-1.3, direction tilted up to 25 deg |
| Colours | per-channel gain +-8 % on table/paper, mat and cardboard (no textures exist in the twin) |
| Top camera | +-5 mm position, +-1 deg orientation per axis |
| Wrist camera | +-2 mm on the gripper |
| Start pose | `act_start` plus noise (pan +-4, wrist flex and roll +-3 deg, others +-0.5) |

A placement is only accepted when the scripted planner can grasp into it: IK reaches the pre-grasp pose and the seed with the
jaws about horizontal (pitch up to 15 deg; a tilted wrist puts the seed outside the pads) and inside the joint ranges
(the MJCF wrist flex stops at +-95). The boxes' turn reaches the physics: MuJoCo ignores a runtime `geom_quat` on geoms
whose compiled frame was the identity unless `geom_sameframe` is cleared (a test reads `geom_xmat`).

**Results** (seed 0, generator at `ba857d5`+):

| | black (`smartseed-sim-grasp-black-v2`) | white (`smartseed-sim-grasp-white-v2`) |
|---|---|---|
| Attempts / kept episodes | 114 / 100 (generator success 87.7 %) | 112 / 100 (89.3 %) |
| Lifted but rejected by the wall monitor | 0 | 0 |
| Scenes redrawn before simulating (placement rejections) | 543: 204 no jaw yaw / path clears the walls, 339 out of reach | 666: 269 no fit, 397 out of reach |
| Failed attempts | 14, the seed was not lifted (missed the pads, open-loop) | 12, same |
| Wall contact in the kept episodes | 0 physics steps, max penetration 0.0 mm | 0 steps, 0.0 mm |
| Frames | 29,503 | 29,508 |
| Seed grasped (index 0-3) | 31 / 18 / 30 / 21 | 17 / 29 / 29 / 25 |
| Generation time | about 35 min on the M5 (two colours in parallel, no GPU) | |

The monitor rejected nothing because the planner's swept-path check already redraws every scene where an arm geom would
touch a wall: replaying the v1 scenes that the v1 audit flagged (more than 1 mm), the v2 planner redraws 23 of the 24 black
and 35 of the 37 white ones (the other three get a different jaw yaw). `audit_walls.py` run on the v2 logs (geometry mode,
independent of the collision bits) agrees: 0 of 200 episodes overlap a wall. Yield is lower than v1 (the planner now accepts 17 % / 14 % of the geometrically valid scenes, v1 29 % / 28.5 %) and biased to scenes with room around the seed: the grasped seeds in
`docs/media/sim-dataset-coverage.png` cluster nearer the arm and away from walls than the v1 ones.

Hub: https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v2 and
https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white-v2 (public, tag `BraboRobots`, in the collection
`smartseed-so-101-act-seed-sowing`, which does not list the withdrawn v1 repos). Loading them back from the Hub gives the same feature dict
as the real `info.json`, 100 episodes each. Previews: `docs/media/sim-dataset-preview.png` (episodes 0, 50, 99 per colour: top over
wrist at the first, middle and last frame), `docs/media/sim-dataset-coverage.png` (every kept scene on the top view) and
`docs/media/sim-wall-check.png` (episode 0 of v1: the same commands in the v1 and the v2 twin).

v1 results for reference (seed 0 of the v1 generator, no wall collisions for the jaws): 132 / 136 attempts for 100 kept
(75.8 % / 73.5 %), 29,497 / 29,502 frames.

Limits: the demos only show scenes the scripted planner can solve (the placements and seeds it cannot reach are never
recorded, so the data under-represents the far corners of the table); the scene is the twin, see "What is weak"; the real
white-seed episodes command the gripper to ~6.7 at the end, the sim uses 4.2-5.0 (a harder squeeze is needed for the sim servo).

## Narrow layout and the v3-narrow datasets (T5b, T5c)

The v2 policies (`act-sim-*-c100`, 100 demos over boxes and tray placed anywhere with any yaw) scored 1/20 and 2/20 on held-out
scenes (see "Evaluating sim-trained policies"). The next stage shrinks the distribution first: `--layout narrow` keeps the two
boxes and the tray near their nominal position in the real scene (centre uniform within +-3 cm in x and y of `layout.py`'s
position, yaw uniform within +-30 deg), and keeps everything else of the generator: 2-4 seeds uniform inside their box, light,
colour, camera and start-pose randomisation, the 1 cm gap between objects, the view and reach limits, the T4b wall-aware
planner, and the wall monitor (episode kept only with max wall penetration <= 1 mm, force <= 2 N).

**Why +-3 cm / +-30 deg** (`sim/scan_layout.py --attempts 40`, planner acceptance = scenes the scripted planner can grasp in per
scene drawn, `ik_acceptance` in the logs; the wide layout accepts 17 % / 14 %):

| jitter | yaw | black | white |
|---|---|---|---|
| 2 cm | +-15 | 43 % | 34 % |
| 2 cm | +-30 | 46 % | 36 % |
| 3 cm | +-15 | 43 % | 40 % |
| **3 cm** | **+-30** | **50 %** | **34 %** |
| 4 cm | +-30 | 49 % | 32 % |
| 5 cm | +-15 | 35 % | 33 % |
| 5 cm | +-30 | 35 % | 31 % |

Acceptance is flat from 2 to 4 cm and drops at 5 cm (40 attempts per cell, so about +-7 points of noise); 3 cm and +-30 deg is the
widest range that keeps it up, so it was taken. The yaw bound is the user's +-30 deg: smaller bounds did not raise it. The real
300-episode runs measured 42.7 % (black) and 36.1 % (white), see the table below.

```bash
backend/.venv/bin/python sim/make_dataset.py --color black --layout narrow --episodes 300 --seed 0 --push-repo RafaelJaime/smartseed-sim-grasp-black-v3-narrow
backend/.venv/bin/python sim/make_dataset.py --color white --layout narrow --episodes 300 --seed 0 --push-repo RafaelJaime/smartseed-sim-grasp-white-v3-narrow
backend/.venv/bin/python sim/make_dataset.py --layout narrow --videos sim/out/v3_videos      # mp4 of the first 5 (3 kept)
backend/.venv/bin/python sim/make_dataset.py --layout narrow --coverage docs/media/sim-dataset-coverage-narrow.png
backend/.venv/bin/python sim/eval.py --planner --color black --layout narrow --episodes 100     # scripted ceiling
```

| | black (`smartseed-sim-grasp-black-v3-narrow`) | white (`smartseed-sim-grasp-white-v3-narrow`) |
|---|---|---|
| Attempts / kept episodes | 307 / 300 (generator success 97.7 %) | 302 / 300 (99.3 %) |
| Frames | 88,617 | 88,410 |
| Lifted but rejected by the wall monitor | 0 | 0 |
| Scenes redrawn before simulating | 412: 193 no jaw yaw / path clears the walls, 219 out of reach | 534: 235 no fit, 299 out of reach |
| Planner acceptance of geometrically valid scenes (`ik_acceptance`) | 42.7 % | 36.1 % |
| Geometric acceptance of drawn objects | 64.0 % | 67.1 % |
| Failed attempts (seed not lifted) | 7 | 2 |
| Scripted planner on 100 held-out narrow scenes (seed 1000, physics, wall monitor) | **100 / 100** lifted and held, all wall-valid | **97 / 100**, all wall-valid |

The last row is the ceiling for a policy trained on this data: the demonstrator itself succeeds 100 % / 97 % on the scenes
`eval.py --layout narrow` uses. Hub: https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-black-v3-narrow and
https://huggingface.co/datasets/RafaelJaime/smartseed-sim-grasp-white-v3-narrow (public, tags `BraboRobots`, `smartseed`, `so101`,
`simulation`, both in the collection `smartseed-so-101-act-seed-sowing`; `meta/info.json` features, fps, robot type and codebase
version equal the real `d1-clean` / `d2-clean` ones, read back from the Hub; 300 episodes each). Coverage: `docs/media/sim-dataset-coverage-narrow.png`
(grasped seeds cluster in the nominal box area); videos `sim/out/v3_videos/` (git-ignored).

Weak: the demos still only show planner-solvable scenes (the planner redraws 57 % / 64 % of the geometrically valid scenes, so
seeds hard against a wall are absent), the layout is a +-3 cm / +-30 deg neighbourhood of one scene (a policy trained here will not
generalise across the table), and the wall-collision audit (`audit_walls.py`) was not re-run on the 600 episodes: the planner's
swept-path check and the monitor (0 collision rejections) are the evidence.

**Next step (not started here):** train on Brev,

```bash
scripts/brev/launch_two.sh <host> RafaelJaime/smartseed-sim-grasp-black-v3-narrow sim-black-narrow-c100 RafaelJaime/smartseed-sim-grasp-white-v3-narrow sim-white-narrow-c100
backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-black-narrow-c100 --color black --layout narrow
```

and gate on `eval.py --layout narrow` (held-out) against the 100 % / 97 % ceiling.

### DART recovery demos (T5e, `--dart-noise`)

Why: narrow ACT trained on 300 clean planner demos plateaus at about 23 % held-out success. The planner is an open-loop joint
trajectory, so the demos only contain states on that one clean path; once the policy drifts off it, it has never seen a way
back (about 60 % of the failures end 10-25 mm from the seed with the jaws closed beside it, and re-planning more often made
things worse). DART (Disturbances for Augmenting Robot Trajectories) records the demonstrator while it is perturbed, so the
data contains off-path states and the expert's way back.

```bash
backend/.venv/bin/python sim/make_dataset.py --color black --layout narrow --episodes 600 --dart-noise 4 --seed 0   # -> sim/out/datasets/smartseed-sim-grasp-black-v4-dart
backend/.venv/bin/python sim/eval.py --planner --color black --layout narrow --episodes 100 --dart-noise 4         # ceiling with the noise on
```

**Design** (`make_dataset.dart_offsets`, `simulate_episode(dart_noise_deg=...)`):

- The executed command is the plan plus a perturbation of the five arm joints: white noise low-passed by a Gaussian kernel
  (sigma 0.4 s), standard deviation `DEG` per joint, clipped to +-2 `DEG`, clipped to the joint limits. It is seeded by the
  scene, so a dataset is reproducible and `--dart-noise 0` (the default) takes exactly the old code path (same bytes).
- The envelope is zero while idle, fades in half-way through the transit, is full until the descent starts and fades out over
  the first 3/4 of the descent. The jaws therefore reach the seed on the planned pose (a perturbed jaw shoves the seed away:
  with the noise held through the grasp, a 2 deg scene lost the seed), and the close, the lift and the fold-back are the plain
  plan. The gripper is never perturbed.
- The recorded `action` is the plan's nominal waypoint at that frame, not the noisy command; `observation.state` is what the
  follower really measured. The planner is open loop (a joint trajectory fixed by the scene, aimed at the seed), so the
  nominal waypoint already is what the expert would command from the perturbed state: the position controller pulls the arm
  back to the path that ends at the seed. Re-solving the approach from the current state was not needed: the noise is gone
  before the close, so the final pose is the nominal one anyway, and a re-solve would add a second planner path
  (IK branch changes, wall re-checks) for no precision gain.
- Every safety rule stays: the plan keeps its swept-path wall check, and the noisy rollout is watched by the same wall monitor
  (rejected above 1 mm or 2 N); only successful, wall-valid episodes are written. The log lines of a dart dataset carry
  `dart_noise_deg`; the dataset folder is `<colour>-v4-dart`.

**Ceiling with the noise on** (`eval.py --planner --dart-noise`, 100 held-out narrow scenes per colour, seed 1000, physics, wall monitor;
clean planner 100 / 97):

| noise (std per joint) | black lifted and held / wall-valid | white lifted and held / wall-valid |
|---|---|---|
| 4 deg | 99 / 99 | 97 / 97 |
| 6 deg | 98 / 96 | 94 / 92 |

4 deg (about 2 cm at the tool, clipped at 8 deg) keeps both colours at or above the 95 % target, so it is the value used;
6 deg drops white below it. (20 scenes, black: 2 deg and 4 deg both 20 / 20.)

## What is weak

- **Walls and the jaw proxy.** The moving-jaw hull is a convex hull, larger than the real jaw, and the box and tray walls are
  estimated from the top frame (a centimetre or so): a grasp the real arm manages with the wall a few millimetres from the
  seed can be refused here. Nominal black seed 0 (13 mm from a wall) was grasped 20/20 in v1 only because the open jaw went
  through the wall; with solid walls no jaw axis clears it and `grasp_test.py` gets 0/20 on it (table above).
- **Floors, mat and table are not solid for the jaws** (see "Collision model"): a jaw pressed into the floor is not detected.
- **v2 data is biased** to scenes with room for the open jaws (17 % / 14 % of the geometrically valid scenes survive the planner, v1 29 % / 28.5 %), so seeds
  hard against a wall or in a corner are never demonstrated; the arm itself is only checked against walls, not against seeds
  other than the grasped one (the footprint test keeps neighbours 10 mm out of the jaws).
- **Grasping** is limited to what `grasp_test.py` covers: vertical approach, seeds clear of walls and neighbours. Black seed 3 (near the box corner) fails 0/20 (the spun-wrist IK does not reach it), white seed 3 19/20. Pad friction, squeeze torque and seed size are tuned to the real readings, not measured.
- **Real calibration vs the camera.** The four clicks in `backend/data/calibration.json` miss the fitted camera by
  28-60 px (several cm) at any single tool height; the best single height is 0.12 m. Likely lens distortion (the
  pinhole fit is exact on the arm, where the camera was fitted) and clicks at varying heights. That is why sim mode
  ships its own self-consistent `config/calibration.json` instead of the real one.
- No lens distortion, no motion blur, no real textures: expect a visual gap for a policy trained on real images.
- Servo dynamics untuned; torque off holds instead of going limp.

## Evaluating sim-trained policies (T5)

```bash
backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-black-c100 --color black                      # 20 held-out scenes
backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-white-c100 --color white --checkpoint 020000
backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-white-c100 --color white --split train       # sanity: the training scenes
```

`eval.py` draws scenes with `make_dataset.sample_params(color, 1000, attempt, resample)` (the datasets used seed 0; same layout,
light, colour, camera and start-pose sampling; a scene is kept only if the scripted planner can grasp in it), starts the arm at
the demonstration's first pose and runs the policy 10 s in closed loop. **Success = a seed of the target colour rose more than
3 cm.** "Lands in the target hole" is not measured: the scripted demos fold back holding the seed and never place it.
Run it with `run_policy.py` in mind: `run_policy.py` is the T3 tool (one fixed nominal scene) and is the wrong test for the v2 policies.

**Diagnosis of the 0/10 from `run_policy.py`.** Checked, no mismatch found: dataset frames vs a fresh render of the same scene
(top 2.1/255 mean abs difference, all from the AV1 codec; state and action identical), keys, 480x640 RGB uint8, units and joint
order, 30 fps, action through `send_joints`, start pose. A test pins that the first observation of an eval episode equals frame 0
of the demonstration byte for byte. Open loop (policy fed the recorded observations of training episode 0, replanning each
frame): mean abs error 1.4-2 deg per joint, gripper 0.1-0.3. What differs is the scene: `run_policy.py` always runs the one
nominal layout (and no start noise), which is a single point of a 3-objects x position x yaw space seen through 100 episodes.

Results (20 episodes per row, ACT chunk 100, 40k steps, `sim/out/eval/*.log`):

| policy | training scenes (log of seed 0) | held-out scenes | held-out, checkpoint 020000 |
|---|---|---|---|
| black | 12/20 (60 %) | **1/20** (5 %) | 1/20 |
| white | 4/20 (20 %) | **2/20** (10 %) | 1/20 |

Only 1 of the 3 held-out "successes" of the final models ends with the seed in the jaws (white); the others lifted the seed and
dropped it (a 32 cm peak lift is the fold-back with the seed, then lost). Offline error of the policy against the scripted
demonstration, replanning every 5th frame, mean over 6 scenes: training 2.1 / 1.8 deg (black / white), held-out 4.4 / 5.2 deg,
wrist roll of white 9.3 deg (the jaw yaw is the hard part). The scripted planner itself succeeds on about 88 % of scenes.

Most likely cause: too few demonstrations for the scene diversity. 100 episodes spread boxes and tray anywhere with any yaw, so
the policy interpolates a seed position and a jaw yaw from about 100 layouts; it does not even close the loop reliably on the
layouts it was trained on (60 % / 20 %), and generalises worse (error x2.4 held-out). Causal confusion is not excluded (the
state alone predicts the idle and fold phases; the images must carry the target) but this data cannot separate it from
under-fitting. Recommendation, nothing started: (1) 5-10x more demos per colour (about 3-6 h of generation on the M5), or one
policy for both colours with the target colour as a fixed task; (2) a narrower first stage (tray and boxes inside a small
region, yaw within +-30 deg) to confirm the pipeline reaches >50 % before widening; (3) re-run `eval.py --split train` and the
held-out split as the acceptance number.

### Eval-driven training length (T5d)

The number of steps is not fixed. `scripts/brev/auto_train.sh <host> <black repo> <white repo>` (instead of `watch_pair.sh`) runs
on this Mac next to a `launch_two.sh` box:

```bash
PYTHON=backend/.venv/bin/python scripts/brev/auto_train.sh my-box RafaelJaime/act-sim-black-narrow-c100 RafaelJaime/act-sim-white-narrow-c100
```

- Every new `checkpoints/<step>` on the Hub is evaluated locally, one at a time, with
  `sim/eval.py --layout narrow --episodes 30` (held-out seed 1000, the same 30 scenes for every step); step -> successes goes to
  `sim/out/auto_train/<name>.json`. An eval whose RSS exceeds `RSS_MAX_MB` (6000) is killed; three failed evals stop the model.
- `sim/auto_stop.py` decides after each eval: stop at >= 90 % success, after 2 consecutive checkpoints without a strictly higher
  success count (patience 20k steps at `--save_freq=10000`), or at the 120k cap. The best checkpoint is the earliest with the highest count.
- A run that reaches its `--steps` limit and is not stopped is resumed on the box by `scripts/brev/resume_run.sh`
  (`lerobot-train --config_path=<out>/checkpoints/last/pretrained_model/train_config.json --resume=true --steps=<+40k, max 120k>`):
  same output dir and Hub repo. Read in lerobot e595b79 (`lerobot_train.py`, `train_utils.py`): resume restores step, RNG, optimizer
  and sampler offset; checkpoints are still saved every `save_freq` and pushed (`save_checkpoint_to_hub`, `checkpoints/<step>`,
  the name is zero-padded to 6 digits, so 050000 etc.); `--steps` on the command line overrides the saved config. Not run on a GPU yet.
  Stopping a model kills its run on the box (`pkill`), its `FAILED-<name>` marker is then ignored.
- When both models are done: the best checkpoint of each is printed and written into the model card (`README.md` only, between
  `<!-- best-checkpoint -->` markers; checkpoints are never deleted or overwritten, but lerobot's own end-of-run push does
  refresh the repo root with the last step's weights), logs go to `~/brev-logs`, and the box is deleted.
- Safety as `watch_pair.sh`: delete on setup failure, all runs failed, no step in 40 min, a step stalled 20 min, box unreachable
  10 min; `brev delete <host> </dev/null` capped at 2 min and confirmed in `brev ls`. Different from the watcher: if the Brev
  login expired it waits up to `LOGIN_WAIT_MIN` (180) for `brev login` (macOS notification) and only then exits 3 "LOGIN NEEDED".
  Long runs (up to 80k more steps per model, about 14 h at 1.5 step/s) mean the login will expire: check the notification.
- Remote scope: ssh to the given host and `brev delete` of it, nothing else. State is kept in files (`sim/out/auto_train/state-<host>`),
  so the script can be restarted. Tests: `backend/tests/test_auto_stop.py` (decision logic), `backend/tests/test_auto_train_sh.py`
  (fake ssh, brev and python: patience, resume +40k, cap, target, setup failure, failed runs, stall, no step, unreachable,
  logged out, eval failures).
