# SO-101 assets (vendored)

| | |
|---|---|
| Source | https://github.com/TheRobotStudio/SO-ARM100, folder `Simulation/SO101` |
| Commit | `a758567c3978dfeefe282ede0500085a48fe8f78` (2026-10-06, "docs: list Seeed Studio and WowRobo first in kits section (#188)") |
| License | Apache-2.0, copy in `so101/LICENSE` (the upstream repository ships no separate NOTICE file) |
| Files | `so101/so101_new_calib_camera.xml` (new-calibration MJCF with the wrist-camera mount) and the 15 STL meshes it references, in `so101/assets/` |

Only the new-calibration camera variant is vendored (the old-calibration files, URDFs, leader arm and handle
meshes are not used). The backend's own URDF copy for kinematics lives in `backend/assets/so101/` from the same
commit.

## Local changes to `so101_new_calib_camera.xml`

Everything else is byte-identical to upstream. Each change is cosmetic or scene wiring, none touches kinematics:

1. Link materials recoloured: the printed arm is orange (`0.98 0.42 0.04`), the jaws and the gripper block are
   red (`0.80 0.04 0.04`), as in the camera frames. Upstream is yellow.
2. `collision` default class: `contype="1" conaffinity="0"`, so the arm collides with the scene (mat, tray, boxes,
   seeds) but never with itself.
3. A `<camera name="wrist">` inside the `gripper` body, the pose is fitted in `sim/layout.py`
   (upstream has the camera *body* but no `<camera>` element).

4. Contact physics for grasping (T2b): two thin box geoms, `pad_fixed` (in `gripper`) and `pad_moving`, class `pad`
   (friction 1.2, condim 4), with the inner-face planes fitted to the jaw meshes; the seeds collide only with these
   pads among arm geoms. Collision bits (T4b, see `sim/README.md`, "Collision model"): the pads have `contype="24"`
   (bit 8 = seeds, bit 16 = box and tray walls) and the moving-jaw hull has `contype="16"` (walls only; it was `"0"`
   in T2b because its tip dragged on the box floor, which let the open jaw pass through walls). The fixed-jaw hull and
   the rest of the arm keep `contype="1"` and already hit walls.
   The `gripper` joint gets damping 0.03 and frictionloss 0.01, its actuator kp 3, kv 0.3, forcerange +-0.15 N m
   (ESTIMATED squeeze, about 2 N at the pads; the arm joints keep the upstream gains).

5. `shoulder_lift` range widened from +-100 to +-106 deg (joint and actuator ctrlrange): the real follower rests at
   -103 (taught `home` -103.25, `act_start` -103.08), past the upstream limit, which clamped the sim arm at -100.

To update: copy the upstream files again, reapply the changes above, note the new commit here.
