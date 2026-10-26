"""Replay a recorded real episode in the sim and measure how well the twin lines up with the real arm.

1. Kinematic replay: every recorded `observation.state` is written to the sim joints (through the same mapping
   `SimRobot` uses) and the sim tool site is compared with the backend's `Kinematics.tool_xyz` (placo FK of the URDF).
2. Camera overlay: for the frames that have a real top image, the rendered top camera is saved next to it (real |
   sim | sim arm outline on the real frame) as `sim/out/replay_overlay.png`; the arm-silhouette chamfer distance
   (px) is the visual residual.
3. Dynamic replay: the recorded `action`s are sent through `SimRobot` at 30 Hz (clamp, servo lag, contacts) and
   the sim joints / tool are compared with the recorded states.

    python sim/export_episode.py                      # once, with a lerobot interpreter
    backend/.venv/bin/python sim/replay.py            # prints the residuals, writes sim/out/replay_overlay.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim.fit_top_camera import real_arm_mask  # noqa: E402
from smartseed_robot.kinematics import Kinematics  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402


def tool_error_mm(robot: SimRobot, kin: Kinematics, state: np.ndarray) -> float:
    """|sim gripperframe - Kinematics.tool_xyz| for a joint state, with no physics (pure FK)."""
    mj, model, data = robot._mj, robot._model, robot._data
    from smartseed_robot.sim_robot import joints_to_qpos

    data.qpos[robot._qadr] = joints_to_qpos(dict(zip(JOINTS, state.tolist())))
    mj.mj_kinematics(model, data)
    sim = data.site_xpos[model.site("gripperframe").id]
    return float(np.linalg.norm(sim - np.array(kin.tool_xyz(dict(zip(JOINTS, state.tolist()))))) * 1000)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default=str(ROOT / "sim/out/ep0.npz"))
    ap.add_argument("--out", default=str(ROOT / "sim/out/replay_overlay.png"))
    ap.add_argument("--rows", type=int, nargs="*", default=[0, 90, 130, 180, 230, 270], help="frames in the overlay")
    args = ap.parse_args()
    npz = np.load(args.episode)
    state, action = npz["state"], npz["action"]
    kin = Kinematics()
    robot = SimRobot(initial=dict(zip(JOINTS, state[0].tolist())))

    fk = np.array([tool_error_mm(robot, kin, s) for s in state])
    print(f"kinematic replay, {len(state)} states: sim tool vs Kinematics.tool_xyz  "
          f"mean {fk.mean():.4f} mm, max {fk.max():.4f} mm")

    rows, chamfers = [], []
    index_of = {int(i): k for k, i in enumerate(npz["frame_index"])}
    for idx in npz["frame_index"]:
        k = index_of[int(idx)]
        robot._data.qpos[robot._qadr] = _qpos(state[idx])
        robot._mj.mj_forward(robot._model, robot._data)
        sim_img = robot.render("top")
        real_img = npz["top"][k]
        real_mask = cv2.resize(real_arm_mask(real_img).astype(np.uint8), (640, 480), interpolation=cv2.INTER_NEAREST) > 0
        sim_mask = _arm_mask_full(robot)
        if real_mask.sum() > 200 and sim_mask.sum() > 200:
            d_real = cv2.distanceTransform((~real_mask).astype(np.uint8), cv2.DIST_L2, 3)
            d_sim = cv2.distanceTransform((~sim_mask).astype(np.uint8), cv2.DIST_L2, 3)
            chamfers.append((d_real[sim_mask].mean() + d_sim[real_mask].mean()) / 2)
        if int(idx) in args.rows:
            edge = real_img.copy()
            contours, _ = cv2.findContours(sim_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(edge, contours, -1, (0, 255, 0), 2)
            label = lambda img, text: cv2.putText(img.copy(), text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                                   (255, 255, 255), 2)
            rows.append(np.hstack([label(real_img, f"real f{idx}"), label(sim_img, "sim"), label(edge, "sim outline")]))
    print(f"top camera overlay: arm silhouette chamfer mean {np.mean(chamfers):.2f} px "
          f"(median {np.median(chamfers):.2f}, over {len(chamfers)} frames with the arm in view)")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    print(f"wrote {args.out}")

    # dynamic replay: recorded actions through the physics
    robot2 = SimRobot(initial=dict(zip(JOINTS, state[0].tolist())))
    joint_err, tool_err = [], []
    for t in range(len(action)):
        robot2.send_joints(dict(zip(JOINTS, action[t].astype(float).tolist())))
        sim_state = np.array([robot2.read_joints()[j] for j in JOINTS])
        ref = state[min(t + 1, len(state) - 1)]
        joint_err.append(np.abs(sim_state - ref))
        tool_err.append(np.linalg.norm(np.array(kin.tool_xyz(dict(zip(JOINTS, sim_state.tolist()))))
                                       - np.array(kin.tool_xyz(dict(zip(JOINTS, ref.tolist()))))) * 1000)
    joint_err = np.array(joint_err)
    print("dynamic replay (actions through SimRobot): mean |joint error| per joint "
          + ", ".join(f"{j} {e:.2f}" for j, e in zip(JOINTS, joint_err.mean(0)))
          + f"; tool position error mean {np.mean(tool_err):.1f} mm, max {np.max(tool_err):.1f} mm")
    robot.close(), robot2.close()


def _qpos(state):
    from smartseed_robot.sim_robot import joints_to_qpos

    return joints_to_qpos(dict(zip(JOINTS, state.tolist())))


def _arm_mask_full(robot: SimRobot) -> np.ndarray:
    mj, model, data = robot._mj, robot._model, robot._data
    renderer = mj.Renderer(model, 480, 640)
    renderer.enable_segmentation_rendering()
    renderer.update_scene(data, camera="top")
    seg = renderer.render()
    renderer.close()
    orange = np.array([model.geom_group[g] == 2 and model.geom_matid[g] >= 0 and model.mat_rgba[model.geom_matid[g]][0] > 0.5
                       for g in range(model.ngeom)])
    gid = seg[..., 0]
    return (seg[..., 1] == mj.mjtObj.mjOBJ_GEOM) & (gid >= 0) & orange[np.clip(gid, 0, None)]


if __name__ == "__main__":
    main()
