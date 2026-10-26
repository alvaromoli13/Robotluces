"""Fit the sim `top` camera (pose + fovy) to the real top camera from a recorded episode.

The real frames show the orange arm at many known joint states, so the camera is whatever makes the rendered arm's
silhouette land on the real one: a chamfer distance between the real orange/red mask (HSV threshold) and the sim
arm mask (MuJoCo segmentation render), summed over the frames where the arm is in view. Prints the constants for
`sim/layout.py` (TOP_CAMERA_*). Needs `python sim/export_episode.py` first.

    backend/.venv/bin/python sim/fit_top_camera.py --episode sim/out/ep0.npz
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from scipy.optimize import minimize  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

from sim import layout  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import joints_to_qpos  # noqa: E402

W, H = 320, 240  # half resolution is plenty for a silhouette fit
BASE = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])  # columns: camera x = -y_world, y = +x_world, z = up


def real_arm_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return cv2.resize((((h <= 18) | (h >= 170)) & (s > 170) & (v > 140)).astype(np.uint8), (W, H),
                      interpolation=cv2.INTER_NEAREST).astype(bool)


class Fitter:
    def __init__(self, npz, first=60, last=270, step=10):
        import mujoco

        self.mj = mujoco
        self.model = mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))
        self.data = mujoco.MjData(self.model)
        self.cam = self.model.camera("top").id
        self.renderer = mujoco.Renderer(self.model, H, W)
        orange = np.zeros(self.model.ngeom, bool)
        for g in range(self.model.ngeom):
            mat = self.model.geom_matid[g]
            orange[g] = self.model.geom_group[g] == 2 and mat >= 0 and self.model.mat_rgba[mat][0] > 0.5
        self.orange = orange
        self.states, self.real, self.dist = [], [], []
        for k, idx in enumerate(npz["frame_index"]):
            if first <= idx <= last:
                self.states.append(npz["state"][idx])
                mask = real_arm_mask(npz["top"][k])
                self.real.append(mask)
                self.dist.append(cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 3))

    def set_camera(self, p) -> None:
        fovy, x, y, z, rx, ry, rz = p
        rot = Rotation.from_rotvec([rx, ry, rz]).as_matrix() @ BASE
        q = Rotation.from_matrix(rot).as_quat()
        self.model.cam_pos[self.cam] = (x, y, z)
        self.model.cam_quat[self.cam] = (q[3], q[0], q[1], q[2])
        self.model.cam_fovy[self.cam] = fovy

    def sim_mask(self, state) -> np.ndarray:
        self.data.qpos[:6] = joints_to_qpos(dict(zip(JOINTS, state.tolist())))
        self.mj.mj_forward(self.model, self.data)
        self.renderer.enable_segmentation_rendering()
        self.renderer.update_scene(self.data, camera="top")
        seg = self.renderer.render()
        self.renderer.disable_segmentation_rendering()
        gid = seg[..., 0]
        return (seg[..., 1] == self.mj.mjtObj.mjOBJ_GEOM) & (gid >= 0) & self.orange[np.clip(gid, 0, None)]

    def loss(self, p) -> float:
        self.set_camera(p)
        total = 0.0
        for state, real, dist in zip(self.states, self.real, self.dist):
            sim = self.sim_mask(state)
            if sim.sum() < 30:
                total += 60
                continue
            sim_dist = cv2.distanceTransform((~sim).astype(np.uint8), cv2.DIST_L2, 3)
            total += np.minimum(dist[sim], 25).mean() + np.minimum(sim_dist[real], 25).mean()
        return total / len(self.states)

    def camera_xyaxes(self, p) -> tuple[float, ...]:
        self.set_camera(p)
        self.mj.mj_forward(self.model, self.data)
        mat = self.data.cam_xmat[self.cam].reshape(3, 3)
        return (*mat[:, 0], *mat[:, 1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default=str(ROOT / "sim/out/ep0.npz"))
    args = ap.parse_args()
    fit = Fitter(np.load(args.episode))
    p = np.array([2 * np.degrees(np.arctan(240 / 520)), 0.30, 0.0, 0.50, 0, 0, 0.0])
    print(f"{len(fit.states)} frames; initial loss {fit.loss(p):.2f} px")
    for _ in range(3):
        p = minimize(fit.loss, p, method="Powell", options={"xtol": 1e-3, "ftol": 1e-5, "maxfev": 1500}).x
        print(f"loss {fit.loss(p):.2f} px  fovy {p[0]:.3f}  pos {np.round(p[1:4], 4)}")
    xy = fit.camera_xyaxes(p)
    print(f"TOP_CAMERA_POS = {tuple(round(float(v), 4) for v in p[1:4])}")
    print(f"TOP_CAMERA_XYAXES = {tuple(round(float(v), 5) for v in xy)}")
    print(f"TOP_CAMERA_FOVY = {p[0]:.3f}")


if __name__ == "__main__":
    main()
