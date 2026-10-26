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

To update: copy the upstream files again, reapply the three changes, note the new commit here.
