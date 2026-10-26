"""Fit the sim `wrist` camera (pose on the gripper body, fovy) and the gripper 0-100 -> jaw angle map.

The real wrist frames always show the two red jaw tips at the bottom. The fixed jaw pins the camera pose to the
gripper; how far the moving jaw has swung, for the recorded gripper value of that frame, pins the jaw map. Loss:
chamfer distance between the real red mask and the sim red-jaw mask (segmentation render), over frames with
different gripper openings. Several starting orientations are tried (the mount orientation is not known).
Prints the camera element for the vendored MJCF and `GRIPPER_JAW_RAD` for `sim_robot.py`.

    backend/.venv/bin/python sim/fit_wrist_camera.py --episode sim/out/ep0.npz
"""
from __future__ import annotations

import argparse
import itertools
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
from smartseed_robot.sim_robot import GRIPPER_JAW_RAD  # noqa: E402

W, H = 320, 240
JAW_SPAN_DEG = (3497 - 2034) * 360 / 4096  # follower calibration: gripper 0..100 spans this many degrees of jaw


def real_jaw_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((h <= 8) | (h >= 172)) & (s > 150) & (v > 70)
    return cv2.resize(mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)


class Fitter:
    def __init__(self, npz, frames, span_deg=JAW_SPAN_DEG):
        import mujoco

        self.span_rad = np.deg2rad(span_deg)
        self.mj = mujoco
        self.model = mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))
        self.data = mujoco.MjData(self.model)
        self.cam = self.model.camera("wrist").id
        self.renderer = mujoco.Renderer(self.model, H, W)
        red = np.zeros(self.model.ngeom, bool)
        for g in range(self.model.ngeom):
            mat = self.model.geom_matid[g]
            red[g] = (self.model.geom_group[g] == 2 and mat >= 0 and self.model.mat_rgba[mat][0] > 0.7
                      and self.model.mat_rgba[mat][1] < 0.2 and self.model.body(self.model.geom_bodyid[g]).name
                      in ("moving_jaw_so101_v1", "gripper"))
        self.red = red
        self.items = []
        for k, idx in enumerate(npz["frame_index"]):
            if idx in frames:
                mask = real_jaw_mask(npz["wrist"][k])
                self.items.append((npz["state"][idx], mask, cv2.distanceTransform((~mask).astype(np.uint8),
                                                                                  cv2.DIST_L2, 3)))

    def apply(self, p) -> None:
        x, y, z, rx, ry, rz, fovy, lo = p
        hi = lo + self.span_rad
        self.model.cam_pos[self.cam] = (x, y, z)
        q = (Rotation.from_rotvec([rx, ry, rz])).as_quat()
        self.model.cam_quat[self.cam] = (q[3], q[0], q[1], q[2])
        self.model.cam_fovy[self.cam] = fovy
        self.jaw = (lo, hi)

    def mask(self, state) -> np.ndarray:
        lo, hi = self.jaw
        self.data.qpos[:5] = np.deg2rad(state[:5])
        self.data.qpos[5] = lo + (hi - lo) * state[5] / 100
        self.mj.mj_forward(self.model, self.data)
        self.renderer.enable_segmentation_rendering()
        self.renderer.update_scene(self.data, camera="wrist")
        seg = self.renderer.render()
        self.renderer.disable_segmentation_rendering()
        gid = seg[..., 0]
        return (seg[..., 1] == self.mj.mjtObj.mjOBJ_GEOM) & (gid >= 0) & self.red[np.clip(gid, 0, None)]

    def loss(self, p) -> float:
        self.apply(p)
        total = 5.0 * max(0.0, 60.0 - p[6], p[6] - 120.0)  # keep the fov a plausible webcam one
        for state, real, dist in zip(*zip(*self.items)):
            sim = self.mask(state)
            if sim.sum() < 20:
                total += 60
                continue
            sim_dist = cv2.distanceTransform((~sim).astype(np.uint8), cv2.DIST_L2, 3)
            total += np.minimum(dist[sim], 40).mean() + np.minimum(sim_dist[real], 40).mean()
        return total / len(self.items)


def quat_from_axes(x_axis, y_axis) -> np.ndarray:
    x, y = np.asarray(x_axis, float), np.asarray(y_axis, float)
    return np.column_stack([x, y, np.cross(x, y)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default=str(ROOT / "sim/out/ep0.npz"))
    args = ap.parse_args()
    npz = np.load(args.episode)
    frames = {int(i) for i in npz["frame_index"] if 100 <= i <= 280}
    fit = Fitter(npz, frames)
    lo = GRIPPER_JAW_RAD[0]
    axes = [np.array(v) for v in itertools.product([-1, 0, 1], repeat=3) if np.abs(v).sum() == 1]
    best = None
    for ax, ay in itertools.permutations(axes, 2):
        if abs(ax @ ay) > 0:
            continue
        rot = Rotation.from_matrix(quat_from_axes(ax, ay))
        for off in ([0.0, 0.03, -0.03], [0.0, -0.03, -0.03], [0.03, 0.0, -0.03], [-0.03, 0.0, -0.03]):
            p = np.array([*off, *rot.as_rotvec(), 90.0, lo])
            loss = fit.loss(p)
            if best is None or loss < best[0]:
                best = (loss, p)
    print(f"best coarse start loss {best[0]:.2f}")
    p = best[1]
    for _ in range(3):
        p = minimize(fit.loss, p, method="Powell", options={"xtol": 1e-3, "ftol": 1e-5, "maxfev": 2500}).x
        print(f"loss {fit.loss(p):.2f} px")
    mat = Rotation.from_rotvec(p[3:6]).as_matrix()
    print(f'<camera name="wrist" pos="{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" xyaxes="'
          f'{" ".join(f"{v:.4f}" for v in (*mat[:, 0], *mat[:, 1]))}" fovy="{p[6]:.2f}"/>')
    hi = p[7] + fit.span_rad
    print(f"GRIPPER_JAW_RAD = ({p[7]:.4f}, {hi:.4f})  # jaw {np.degrees(p[7]):.1f} to {np.degrees(hi):.1f} deg")


if __name__ == "__main__":
    main()
