# Replicating the experiment in a simulator

> **Status: steps 1-5 are implemented** (scene, cameras, joint mapping, `SimRobot`, `SMARTSEED_ROBOT=sim`;
> see `sim/README.md` for what was measured, how accurate it is and how to run it). Steps 6 onward and the
> experiments are still a roadmap. Claims about third-party projects come from a desk survey and are marked
> **(unverified)** unless we checked them. Where the layout below differs from `sim/`, `sim/` wins:
> `SimRobot` lives in `backend/smartseed_robot/sim_robot.py` so the backend factory can import it.

Goal: run the SmartSeed pick-and-sow experiment in simulation, so that our ACT policies (or
policies retrained on simulated data) can be tried without the arm, and so others can replicate
the work without hardware.

## What the simulator has to match

Verified in this repo (`backend/smartseed_robot/robot.py`, `executor.py`, `kinematics.py`, `act.py`):

| Contract | Value |
|---|---|
| Robot interface | `RobotPort` protocol: `read_joints`, `read_observation`, `cameras_ok`, `reconnect_cameras`, `send_joints`, `torque_off`, `torque_on`, `torque_enabled`, `close`. `FakeRobot` is the reference test double. |
| Joints | `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll` in **degrees** (lerobot `use_degrees=True`), `gripper` in **0-100** |
| Observation | `observation.state` float32 in that joint order; `observation.images.top` and `observation.images.wrist`, HWC uint8 RGB, shape `(480, 640, 3)` |
| Control rate | 30 Hz (`MotionConfig.hz` and `ExecutorConfig.hz`) |
| Clamp | the real follower is built with `max_relative_target=8.0`: lerobot limits each goal to at most 8 units from the present position per command |
| Kinematics | placo IK on `backend/assets/so101/so101_new_calib.urdf`, frame `gripper_frame_link`; `Kinematics.tool_xyz(joints)` takes joints in degrees |
| Backend factory | `build_runtime` in `api.py` picks the robot from `SMARTSEED_ROBOT` (`fake` or `real`, anything else raises) |
| Policy input | the ACT policies were trained on `top` + `wrist` cameras, 640x480@30, task `grasp the seed below the gripper` |

The URDF is the TheRobotStudio SO-ARM100 `so101_new_calib.urdf` (provenance in
`backend/assets/so101/SOURCE.md`), so a "new calibration" MJCF from the same repository shares its
joint zeros with our forward kinematics.

## Options

| Option | What it gives | Fit for us | Notes |
|---|---|---|---|
| [TheRobotStudio SO-ARM100 `Simulation/SO101`](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101) | URDF + MJCF for new and old calibration, `scene.xml`, and `so101_new_calib_camera.{urdf,xml}` with a wrist-camera mount. Apache-2.0 (checked via the GitHub API) | **Best base.** Same URDF family as our kinematics | Verified: the file list above; position actuators with `kp` about 998 and a force range for the STS3215 class; the camera variant adds mount and camera *bodies* but **no `<camera>` element** (0 found), so we add cameras ourselves; the gripper range is about -10 to 100 degrees |
| [MuJoCo Menagerie `robotstudio_so101`](https://github.com/google-deepmind/mujoco_menagerie) | Curated SO-101 MJCF | Fallback | No cameras and different actuator gains **(unverified)** |
| [LeRobot `gym-hil`](https://huggingface.co/docs/lerobot/hilserl_sim) | Human-in-the-loop RL sim in MuJoCo | Not directly | Franka only **(unverified)** |
| [LeRobot EnvHub + `lerobot-eval`](https://huggingface.co/docs/lerobot/envhub) | A way to publish a gym env and evaluate a policy with `lerobot-eval` | Useful for evaluation later | Observation key names (`pixels` / `agent_pos`) versus our `observation.images.*` / `observation.state` need checking **(unverified)** |
| [LeIsaac](https://github.com/LightwheelAI/leisaac) | Isaac Lab; SO-101 leader teleoperation, data collection, conversion and policy training (description checked via the GitHub API) | Best fidelity if a GPU is available | Needs an NVIDIA GPU, so **not on a Mac**; cloud GPU (for example Brev) works. LeRobot recorder support **(unverified)** |
| [so101-nexus](https://github.com/johnsutor/so101-nexus) | SO-101 in MuJoCo: teleoperation, imitation learning, RL (Apache-2.0, checked via the GitHub API) | Closest ready-made fit | Wrist + overhead cameras and LeRobot v3 output **(unverified)**; beta **(unverified)** |
| [so-frame](https://github.com/livekit-examples/so-frame) | Real/sim overlay calibration | Helps the calibration check | Not inspected |
| [ManiSkill3](https://maniskill.readthedocs.io/en/latest/user_guide/tutorials/sim2real/index.html) | GPU-parallel sim with a sim2real tutorial | Not directly | SO-100 only **(unverified)** |

**Recommendation.** MuJoCo with the `so101_new_calib_camera` MJCF: it runs on a Mac (no GPU
needed, which is also where the backend runs), it is the same arm model as our IK, and its
position actuators behave like the Feetech servos closely enough to start. If an NVIDIA GPU is
available (for example a Brev instance), LeIsaac is the higher-fidelity alternative; it is a
separate stack and would not share `SimRobot`. Before building from scratch, evaluate
`so101-nexus` against the contract table above: if it already gives matching camera keys, 30 fps
and joint conventions, it replaces most of steps 2 and 3 below.

## Joint mapping

- **Arm joints.** The new-calibration MJCF sets each joint's zero to the middle of its range,
  which is the same convention as lerobot's calibrated degrees. So `qpos[rad] = deg2rad(deg)`
  and back, applied only at the `SimRobot` boundary.
- **Gripper.** lerobot uses 0 (closed) to 100 (open); the MJCF jaw joint is an angle (about -10
  to 100 degrees). Fit a linear map `jaw_rad = a * gripper + b` from a few recorded gripper
  values and the matching jaw angles; do not assume it is the identity.
- **Check before trusting it.** Replay the `observation.state` of a recorded episode through the
  sim, then (1) compare `Kinematics.tool_xyz` computed from the recorded joints with the
  simulated `gripper_frame_link` position (millimetres), and (2) overlay the rendered top camera
  on the real top frame at the same instant. Joint errors show up as a growing offset.

## Build steps

1. **Scene** (`sim/scene.xml`): table mat; a 3x4 seedling tray with holes; the black and white
   seed boxes; seeds as small spheres. Dimensions from our tray and the camera-robot
   calibration (`backend/data/calibration.json`, git-ignored; the pixel-to-robot homography).
2. **Cameras.** `top`: a fixed `<camera>` whose pose and `fovy` come from the camera-robot
   calibration and a measured top camera; `wrist`: a `<camera>` attached to the gripper body,
   next to the wrist-camera mount of the `_camera` variant. Both render 640x480.
3. **Physics tuning.** Servo gains and force limits (compare with the real step response by
   commanding a joint and logging the real follower), and seed size, mass and friction. Grasping
   is the weak point: seeds are tiny and the ACT policy relies on the jaws stopping on a seed
   (`FakeRobot` models this with `held_value`).
4. **`SimRobot(RobotPort)`** (`sim/sim_robot.py`): same keys and shapes as above, steps physics at
   30 fps (several substeps per control step), applies the same clamp (`max_relative_target=8.0`),
   reports `torque_enabled`, and implements `cameras_ok` / `reconnect_cameras` trivially.
5. **Backend factory.** Add `SMARTSEED_ROBOT=sim` next to `fake` / `real` in `build_runtime`, so
   the web UI and the executor drive the simulated arm unchanged. The factory error message and
   README table must be updated with it.
6. **Optional gym env** (`sim/env.py`): wrap `SimRobot` in a gymnasium env and, if useful, an
   EnvHub `make_env` so `lerobot-eval` can run policies. Map observation keys explicitly (see the
   EnvHub row above).

## Experiments

- **A. Zero-shot real ACT in sim.** Load `RafaelJaime/act-smartseed-d1-c100` / `-d2-c100` into the
  sim. Expect a visual gap (render versus camera image). Mitigations to try: texture and lighting
  randomization, real-photo textures for the mat, tray and boxes, camera-pose jitter.
  **Run (T3, `sim/run_policy.py`):** 1 of 40 episodes lifted a seed over 3 cm (d1-c100-80k, a real grasp that
  dropped the seed after 0.8 s); the other three policies 0/10. The policies do move to the right box and hover over
  the seeds, but never close on one: the visual gap is real. Table, videos and the real-vs-sim frame comparison
  (`docs/media/sim-vs-real-obs.png`) are in `sim/README.md`, "Running the real ACT in sim".
- **B. Sim-trained policy.** **Demos done (T4, `sim/make_dataset.py`):** 100 scripted episodes per colour with
  randomised box, tray and seed placement, lighting and cameras, on the Hub as `RafaelJaime/smartseed-sim-grasp-black` and
  `-white` (generator success 76 % / 74 %, details in `sim/README.md`). Training is T5. Original plan: write scripted IK demonstrations (`sim/scripted_demo.py`, using
  `Kinematics.solve` against the simulated tool frame), record them as a `LeRobotDataset` with the
  same keys and fps, train ACT with the existing scripts (`lerobot/scripts/20_train_local.sh`, or
  `scripts/brev/train_pair.sh` on a cloud GPU), and evaluate. Metric: a seed is lifted more than
  3 cm and lands within a tolerance of the target hole; at least 50 seeded episodes per policy,
  reporting success rate and drop error.
- **C. Real-to-sim replay** as a calibration check: replay recorded episodes from the d1/d2
  datasets in the sim and compare tool position and camera overlay (see "Joint mapping").

## Proposed layout

```
sim/
  scene.xml            # MJCF scene including the so101_new_calib_camera model
  assets/              # meshes, textures (SO-101 meshes with their Apache-2.0 provenance)
  sim_robot.py         # SimRobot(RobotPort)
  env.py               # optional gymnasium env / EnvHub make_env
  scripted_demo.py     # IK demonstrations -> LeRobotDataset
  eval.py              # success metric over N seeded episodes
backend/tests/test_sim_robot.py   # contract parity with FakeRobot (keys, shapes, dtypes, clamp)
```

Contract tests should run the same assertions against `FakeRobot` and `SimRobot`: observation
keys, `(480, 640, 3)` uint8 images, float32 state in `JOINTS` order, per-command clamp, torque
behaviour. They must not need a display (use MuJoCo's offscreen renderer or skip rendering).

## Open questions

- Does `so101-nexus` already satisfy the contract (camera names, 30 fps, degrees)?
- How well do the real-photo textures close the visual gap for ACT (experiment A)?
- The gripper linear fit and servo gains need real measurements; none were taken at the event.
