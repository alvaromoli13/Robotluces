"""Scripted grasp demonstrations in the MuJoCo twin, recorded as LeRobotDatasets with the real datasets' schema.

    backend/.venv/bin/python sim/make_dataset.py --color black --episodes 100 --seed 0 \\
        --out sim/out/datasets/smartseed-sim-grasp-black --push-repo RafaelJaime/smartseed-sim-grasp-black

One episode mirrors a real teleop episode of `RafaelJaime/smartseed-grasp-d{1,2}-clean`: rest at the taught
`act_start`, open the gripper while moving above a seed, descend, close, lift, fold back to the rest pose with the seed
in the jaws, hold there until the 300-frame cap. `action` is the commanded joint target (the leader), `observation.state`
the joints the simulated follower measures, both in degrees with the gripper 0-100; the two camera streams are the
twin's 640x480 `top` and `wrist` renders. Only episodes in which the seed was lifted more than 3 cm and is still in the
jaws at the end are kept.

Everything random is drawn from `np.random.default_rng([seed, attempt, colour])` (one *attempt* = one candidate episode,
failed ones consume an attempt), so a dataset is a function of `(colour, seed)` and a stopped run resumes exactly where
it left off. All bounds live in `Randomisation` (`RANDOM`) and are listed in `sim/README.md`.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import grasp_test, layout  # noqa: E402
from smartseed_robot.kinematics import IKError, Kinematics  # noqa: E402
from smartseed_robot.robot import ARM_JOINTS, IMAGE_SHAPE, JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

CONFIG_DIR = ROOT / "sim" / "config"
REAL = json.loads((CONFIG_DIR / "real_features.json").read_text())
FPS: int = REAL["fps"]
TASK: str = REAL["task"]
ROBOT_TYPE: str = REAL["robot_type"]
FEATURES: dict = REAL["features"]
LOG_NAME = "sim_generation.jsonl"
GITHUB = "https://github.com/alvaromoli13/Robotluces"
HF_USER = "RafaelJaime"
REAL_REPOS = {"black": "RafaelJaime/smartseed-grasp-d1-clean", "white": "RafaelJaime/smartseed-grasp-d2-clean"}
COLLECTION = "RafaelJaime/smartseed-so-101-act-seed-sowing-6adf0632f7e93bb112d73e8c"

MIN_FRAMES, MAX_FRAMES = 272, 300  # real episodes: 278-300 frames, most of them exactly the 10 s cap
SETTLE_STEPS = 15  # the arm holds the start pose and the seeds settle before frame 0
LIFT_MIN_M = 0.03  # a kept episode lifted the seed at least this much ...
IN_JAWS_M = 0.02  # ... and ends with it this close to the tool frame (as in `run_policy`)
LIFT_M = 0.07  # Cartesian lift above the grasp height before the fold-back
TOOL_Z_OFFSET = grasp_test.TOOL_Z_OFFSET
APPROACH_Z = grasp_test.APPROACH_Z
JOINT_MARGIN_DEG = 0.5
PARK_XY = (3.0, 3.0)  # seeds that are not part of an episode wait here, far outside the scene


@dataclass(frozen=True)
class Randomisation:
    """Every per-episode random bound of the generator, in one place."""
    seeds_min: int = 2  # seeds present in each box (of the 4 of the twin)
    seeds_max: int = 4
    seed_wall_margin_m: float = 0.022  # seeds are uniform on the box floor, this far from the inner walls so the jaws fit
    seed_min_gap_m: float = 0.025  # ... and at least this far from each other
    view_margin_m: float = 0.015  # boxes and tray lie fully inside the top camera's footprint, this far from its edge
    object_gap_m: float = 0.01  # free space between the two boxes and the tray
    base_keepout_m: float = 0.10  # nothing closer than this to the shoulder pan axis (the arm's own footprint)
    reach_max_m: float = 0.36  # box and tray centres within this of the pan axis (IK rejects the rest)
    light_scale: tuple[float, float] = (0.7, 1.3)  # multiplies the ceiling light and the headlight
    light_tilt_deg: float = 25.0  # ceiling light direction tilted off vertical by up to this
    colour_jitter: float = 0.08  # per-channel gain of the table/paper, the mat and the cardboard, (1 +- this)
    top_cam_shift_m: float = 0.005  # top camera position, each axis
    cam_rot_deg: float = 1.0  # top camera orientation, each axis
    wrist_cam_shift_m: float = 0.002  # wrist camera position on the gripper, each axis
    aim_error_m: float = 0.0015  # the operator's aim at the seed, x and y (1 sigma, clipped at 2 sigma)
    start_noise_deg: dict = field(default_factory=lambda: {
        "shoulder_pan": 4.0, "shoulder_lift": 0.5, "elbow_flex": 0.5, "wrist_flex": 3.0, "wrist_roll": 3.0,
        "gripper": 0.5})  # the leader never rests at exactly the taught act_start
    open_g: tuple[float, float] = (18.0, 31.0)  # gripper opening before the grasp (real teleop 19-31)
    close_g: tuple[float, float] = (4.2, 5.0)  # commanded closing level, below the ~7 stall on the seed
    wobble_deg: float = 0.25  # amplitude of the slow hand wobble added to the arm joints outside the grasp
    # frames per phase (inclusive ranges), the rest of the 300 frames is the hold at the fold
    idle: tuple[int, int] = (24, 45)
    transit: tuple[int, int] = (36, 52)
    descend: tuple[int, int] = (30, 42)
    settle: tuple[int, int] = (20, 30)
    close: tuple[int, int] = (10, 14)
    hold: tuple[int, int] = (8, 12)
    lift: tuple[int, int] = (18, 26)
    retract: tuple[int, int] = (40, 56)
    p_full_length: float = 0.65  # share of episodes that run to exactly the 300-frame cap
    rest_pan: tuple[float, float] = (3.0, 13.0)  # where the real episodes end folded (action space, degrees)
    rest_wrist_flex: tuple[float, float] = (-100.0, -80.0)
    rest_wrist_roll: tuple[float, float] = (-1.0, 6.0)


RANDOM = Randomisation()
MAX_PLACEMENT_DRAWS = 100_000


class Unreachable(Exception):
    """The seed cannot be grasped by the scripted planner (IK out of reach or out of the joint ranges)."""


@dataclass(frozen=True)
class Placement:
    center: tuple[float, float]  # board frame (x' up in the top image, y' left)
    yaw_deg: float


@dataclass(frozen=True)
class BoxState:
    center: tuple[float, float]
    yaw_deg: float
    seeds: tuple[tuple[int, float, float], ...]  # (seed index, x, y) in the box frame, relative to its centre


@dataclass(frozen=True)
class EpisodeParams:
    color: str
    seed: int
    attempt: int
    resample: int  # 0, or how many unreachable placements were thrown away before this one
    proposals: int  # object placements drawn for this one (3 are accepted)
    black: BoxState
    white: BoxState
    tray: Placement
    target: int  # seed index in the box of `color`
    light_scale: float
    light_tilt_deg: tuple[float, float]
    colour_gain: tuple[tuple[float, float, float], ...]  # table+paper, mat, cardboard
    top_cam_shift: tuple[float, float, float]
    top_cam_rot_deg: tuple[float, float, float]
    wrist_cam_shift: tuple[float, float, float]
    aim_error: tuple[float, float]
    start_noise_deg: tuple[float, ...]  # JOINTS order
    open_g: float
    close_g: float
    phases: tuple[tuple[str, int], ...]  # (name, frames) for idle .. retract
    total_frames: int
    rest_pose: tuple[float, float, float, float, float]  # arm joints at the fold (action space)
    wobble_seed: int

    @property
    def box(self) -> BoxState:
        return self.white if self.color == "white" else self.black

    @property
    def present(self) -> tuple[int, ...]:
        return tuple(i for i, _, _ in self.box.seeds)

    def seed_xy(self, color: str, index: int) -> np.ndarray:
        """World (base frame) xy of a seed: its box-frame spot turned and moved with the box."""
        state = self.white if color == "white" else self.black
        _, lx, ly = next(t for t in state.seeds if t[0] == index)
        c, s = math.cos(math.radians(state.yaw_deg)), math.sin(math.radians(state.yaw_deg))
        return np.array(layout.to_world((state.center[0] + c * lx - s * ly, state.center[1] + s * lx + c * ly)))

    def seed_xyz(self, index: int) -> np.ndarray:
        """Where seed `index` of the colour being grasped rests, base frame."""
        return np.array([*self.seed_xy(self.color, index),
                         box_of(self.color).floor_z + layout.SEED_RADIUS[self.color] + 1e-4])


def attempt_of(params: EpisodeParams) -> int:
    return params.attempt


def box_of(color: str) -> layout.OpenBox:
    return layout.WHITE_BOX if color == "white" else layout.BLACK_BOX


def placed_box(p: EpisodeParams) -> layout.OpenBox:
    """The box being grasped from, where this episode put it (its yaw is `p.box.yaw_deg`)."""
    return replace(box_of(p.color), center=p.box.center)


# -- placement geometry ---------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def view_polygon() -> tuple[tuple[float, float], ...]:
    """The top camera's footprint on the mat plane (base-frame xy, counter-clockwise): where the policy can see."""
    pos = np.array(layout.TOP_CAMERA_POS)
    xa, ya = np.array(layout.TOP_CAMERA_XYAXES[:3]), np.array(layout.TOP_CAMERA_XYAXES[3:])
    za = np.cross(xa, ya)
    t = math.tan(math.radians(layout.TOP_CAMERA_FOVY / 2))
    pts = []
    for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        d = xa * u * t * IMAGE_SHAPE[1] / IMAGE_SHAPE[0] + ya * v * t - za
        pts.append(tuple(map(float, (pos + (layout.MAT_TOP_Z - pos[2]) / d[2] * d)[:2])))
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return tuple(pts if area > 0 else pts[::-1])


def footprint(center, yaw_deg: float, half) -> np.ndarray:
    """Corners (4, 2) of a rectangle of half extents `half` turned by `yaw_deg` about `center`."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return np.array([(center[0] + c * sx * half[0] - s * sy * half[1], center[1] + s * sx * half[0] + c * sy * half[1])
                     for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def overlap(a, b, gap: float) -> bool:
    """Two (center, yaw_deg, half) rectangles are closer than `gap` (separating-axis test, `gap` split between them)."""
    ra, rb = footprint(a[0], a[1], np.add(a[2], gap / 2)), footprint(b[0], b[1], np.add(b[2], gap / 2))
    for rect in (ra, rb):
        for i in range(2):
            edge = rect[i + 1] - rect[i]
            axis = np.array([-edge[1], edge[0]]) / np.linalg.norm(edge)
            pa, pb = ra @ axis, rb @ axis
            if pa.max() <= pb.min() or pb.max() <= pa.min():
                return False
    return True


def _inside_view(point_world, margin: float) -> bool:
    poly = view_polygon()
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = x1 - x0, y1 - y0
        if (ex * (point_world[1] - y0) - ey * (point_world[0] - x0)) / math.hypot(ex, ey) < margin:
            return False
    return True


def _place(rng, half, others, r: Randomisation) -> tuple[Placement, int]:
    """Draw (centre, yaw) uniformly until the rectangle is in view, within reach, clear of the arm and of `others`;
    returns it with the number of draws it took."""
    board = np.array([layout.to_board(pt) for pt in view_polygon()])
    lo, hi = board.min(axis=0), board.max(axis=0)
    pan = np.array([layout.BASE_PAN_AXIS[0], 0.0])
    for draws in range(1, MAX_PLACEMENT_DRAWS + 1):
        center, yaw = rng.uniform(lo, hi), float(rng.uniform(-180, 180))
        if np.linalg.norm(np.array(layout.to_world(center)) - pan) > r.reach_max_m:
            continue
        corners = [np.array(layout.to_world(c)) for c in footprint(center, yaw, half)]
        if not all(_inside_view(c, r.view_margin_m) and np.linalg.norm(c - pan) >= r.base_keepout_m for c in corners):
            continue
        if any(overlap((center, yaw, half), o, r.object_gap_m) for o in others):
            continue
        return Placement((float(center[0]), float(center[1])), yaw), draws
    raise RuntimeError("no free placement for the object")


def _seeds_in(rng, box: layout.OpenBox, r: Randomisation) -> tuple[tuple[int, float, float], ...]:
    n = int(rng.integers(r.seeds_min, r.seeds_max + 1))
    idx = sorted(int(i) for i in rng.choice(layout.SEEDS_PER_BOX, n, replace=False))
    hx, hy = box.inner_half[0] - r.seed_wall_margin_m, box.inner_half[1] - r.seed_wall_margin_m
    spots: list[tuple[float, float]] = []
    while len(spots) < n:
        spot = (float(rng.uniform(-hx, hx)), float(rng.uniform(-hy, hy)))
        if all(math.hypot(spot[0] - o[0], spot[1] - o[1]) >= r.seed_min_gap_m for o in spots):
            spots.append(spot)
    return tuple((i, *spot) for i, spot in zip(idx, spots))


def _uni(rng, bound, size=None):
    return rng.uniform(-bound, bound, size)


def sample_params(color: str, seed: int, attempt: int, resample: int = 0, r: Randomisation = RANDOM) -> EpisodeParams:
    """Draw every random quantity of one candidate episode. Pure function of its arguments; `resample` counts the
    placements the planner could not reach (the generator asks for the next one)."""
    rng = np.random.default_rng([seed, attempt, 1 if color == "white" else 0, resample])
    tray, d1 = _place(rng, layout.TRAY_OUTER_HALF, [], r)
    taken = [(tray.center, tray.yaw_deg, layout.TRAY_OUTER_HALF)]
    placed, draws = {}, d1
    for name, box in (("black", layout.BLACK_BOX), ("white", layout.WHITE_BOX)):
        place, d = _place(rng, box.outer_half, taken, r)
        taken.append((place.center, place.yaw_deg, box.outer_half))
        placed[name] = BoxState(place.center, place.yaw_deg, _seeds_in(rng, box, r))
        draws += d
    present = [i for i, _, _ in placed[color].seeds]
    target = int(rng.choice(present))
    theta, rad = rng.uniform(0, 2 * math.pi), r.light_tilt_deg * math.sqrt(rng.uniform())
    phases = tuple((k, int(rng.integers(getattr(r, k)[0], getattr(r, k)[1] + 1)))
                   for k in ("idle", "transit", "descend", "settle", "close", "hold", "lift", "retract"))
    core = sum(n_ for _, n_ in phases)
    total = MAX_FRAMES if rng.uniform() < r.p_full_length else int(rng.integers(MIN_FRAMES, MAX_FRAMES))
    total = max(total, core + 15)
    aim = np.clip(rng.normal(0, r.aim_error_m, 2), -2 * r.aim_error_m, 2 * r.aim_error_m)
    return EpisodeParams(
        color=color, seed=seed, attempt=attempt, resample=resample, proposals=draws,
        black=placed["black"], white=placed["white"], tray=tray, target=target,
        light_scale=float(rng.uniform(*r.light_scale)),
        light_tilt_deg=(float(rad * math.cos(theta)), float(rad * math.sin(theta))),
        colour_gain=tuple(tuple(map(float, _uni(rng, r.colour_jitter, 3))) for _ in range(3)),
        top_cam_shift=tuple(map(float, _uni(rng, r.top_cam_shift_m, 3))),
        top_cam_rot_deg=tuple(map(float, _uni(rng, r.cam_rot_deg, 3))),
        wrist_cam_shift=tuple(map(float, _uni(rng, r.wrist_cam_shift_m, 3))),
        aim_error=(float(aim[0]), float(aim[1])),
        start_noise_deg=tuple(float(_uni(rng, r.start_noise_deg[j])) for j in JOINTS),
        open_g=float(rng.uniform(*r.open_g)), close_g=float(rng.uniform(*r.close_g)),
        phases=phases, total_frames=min(total, MAX_FRAMES),
        rest_pose=(float(rng.uniform(*r.rest_pan)), float(rng.uniform(-103.6, -102.6)),
                   float(rng.uniform(96.4, 96.95)), float(rng.uniform(*r.rest_wrist_flex)),
                   float(rng.uniform(*r.rest_wrist_roll))),
        wobble_seed=int(rng.integers(2**31)),
    )


# -- the scene ------------------------------------------------------------------------------------------------
def _rotate_z(quat: np.ndarray, deg: float) -> np.ndarray:
    import mujoco

    out, half = np.zeros(4), math.radians(deg) / 2
    mujoco.mju_mulQuat(out, np.array([math.cos(half), 0.0, 0.0, math.sin(half)]), quat)
    return out


def _turn(quat: np.ndarray, rot_deg) -> np.ndarray:
    """`quat` followed by a small rotation (degrees about x, y, z of the local frame)."""
    import mujoco

    vec = np.deg2rad(np.asarray(rot_deg, dtype=float))
    angle = float(np.linalg.norm(vec))
    if angle == 0:
        return np.asarray(quat, dtype=float).copy()
    delta, out = np.zeros(4), np.zeros(4)
    mujoco.mju_axisAngle2Quat(delta, vec / angle, angle)
    mujoco.mju_mulQuat(out, np.asarray(quat, dtype=float), delta)
    return out


def apply_scene(robot: SimRobot, p: EpisodeParams) -> None:
    """Turn the freshly built twin into this episode's scene (the model is private to the robot, so nothing leaks)."""
    import mujoco

    m, d = robot._model, robot._data

    def move(prefix: str, old_center, center, yaw_deg: float) -> None:
        """Turn every geom of the object about its old centre, then put that centre at `center` (board frame)."""
        c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
        for g in range(m.ngeom):
            if (m.geom(g).name or "").startswith(prefix):
                nx, ny = m.geom_pos[g, 0] - old_center[0], m.geom_pos[g, 1] - old_center[1]
                m.geom_pos[g, :2] = (center[0] + c * nx - s * ny, center[1] + s * nx + c * ny)
                m.geom_quat[g] = _rotate_z(m.geom_quat[g], yaw_deg)
                m.geom_sameframe[g] = 0  # the compiler flagged identity-quat geoms: without this the new quat is ignored

    move("tray_", layout.TRAY_CENTER, p.tray.center, p.tray.yaw_deg)
    for color, state in (("black", p.black), ("white", p.white)):
        box = box_of(color)
        move(box.name + "_", box.center, state.center, state.yaw_deg)
        present = {i for i, _, _ in state.seeds}
        for i in range(layout.SEEDS_PER_BOX):
            joint = m.joint(f"seed_{color}_{i}_free")
            adr, dof = joint.qposadr[0], joint.dofadr[0]
            if i in present:
                d.qpos[adr:adr + 3] = (*p.seed_xy(color, i), box.floor_z + layout.SEED_RADIUS[color] + 1e-4)
            else:
                d.qpos[adr:adr + 3] = (PARK_XY[0] + 0.1 * i, PARK_XY[1] + (color == "white"),
                                       layout.TABLE_Z + layout.SEED_RADIUS[color])
            d.qvel[dof:dof + 6] = 0
    # light: one ceiling lamp plus the headlight, brighter or dimmer, leaning a little
    scale = p.light_scale
    lid = m.light("ceiling").id
    m.light_diffuse[lid] = np.array([0.35, 0.35, 0.35]) * scale
    tx, ty = p.light_tilt_deg
    tilt = math.radians(math.hypot(tx, ty))
    if tilt > 0:
        azimuth = math.atan2(ty, tx)
        m.light_dir[lid] = (math.sin(tilt) * math.cos(azimuth), math.sin(tilt) * math.sin(azimuth), -math.cos(tilt))
    m.vis.headlight.diffuse[:] = np.array([0.25] * 3) * scale
    m.vis.headlight.ambient[:] = np.array([0.30] * 3) * (0.5 + 0.5 * scale)
    # colours: a per-channel gain on three groups of geoms
    for g in range(m.ngeom):
        name = m.geom(g).name or ""
        if name in ("table", "paper"):
            group = 0
        elif name == "mat":
            group = 1
        elif name.startswith(("tray_", "box_")):
            group = 2
        else:
            continue
        m.geom_rgba[g, :3] = np.clip(m.geom_rgba[g, :3] * (1 + np.asarray(p.colour_gain[group])), 0, 1)
    # cameras
    top, wrist = m.camera("top").id, m.camera("wrist").id
    m.cam_pos[top] += p.top_cam_shift
    m.cam_quat[top] = _turn(m.cam_quat[top], p.top_cam_rot_deg)
    m.cam_pos[wrist] += p.wrist_cam_shift
    mujoco.mj_forward(m, d)


# -- the motion -----------------------------------------------------------------------------------------------
def _min_jerk(u: np.ndarray) -> np.ndarray:
    return u ** 3 * (10 - 15 * u + 6 * u * u)


def _ease(n: int, skew: float = 1.0) -> np.ndarray:
    """Progress 0 -> 1 over `n` frames (the last one is the goal), min-jerk, with the speed peak moved by `skew`."""
    return _min_jerk((np.arange(1, n + 1) / n) ** skew)


@functools.lru_cache(maxsize=1)
def joint_limits_deg() -> dict[str, tuple[float, float]]:
    import mujoco

    m = mujoco.MjModel.from_xml_path(str(layout.SCENE_PATH))
    return {j: tuple(np.rad2deg(m.joint(j).range)) for j in ARM_JOINTS}


def _check_limits(sol: dict[str, float], what: str) -> None:
    for j, (lo, hi) in joint_limits_deg().items():
        if not lo + JOINT_MARGIN_DEG < sol[j] < hi - JOINT_MARGIN_DEG:
            raise Unreachable(f"{what}: {j} {sol[j]:.0f} deg is outside [{lo:.0f}, {hi:.0f}]")


MAX_PITCH_DEG = 15.0  # the jaws must open about horizontally: a tilted wrist puts the seed outside the pads


def _solve(kin: Kinematics, xyz, seed: dict, spin: float, what: str) -> dict[str, float]:
    try:
        sol, pitch = kin.solve_with_pitch(*map(float, xyz), seed=seed, spin_deg=spin)
    except IKError as exc:
        raise Unreachable(f"{what}: {exc}") from exc
    if pitch is None or pitch > MAX_PITCH_DEG:
        raise Unreachable(f"{what}: only a tilted wrist reaches it (pitch {pitch})")
    _check_limits(sol, what)
    return sol


def _vec(joints: dict[str, float]) -> np.ndarray:
    return np.array([joints.get(j, 0.0) for j in JOINTS], dtype=float)  # IK solutions carry no gripper


MAX_STEP_DEG = 7.2  # per-frame joint step the follower can track (its clamp is 8)


def _frames_for(frames: int, delta: np.ndarray) -> int:
    """`frames`, or more if a min-jerk move of `delta` (peak speed up to 2.3x the mean with the speed skew) would
    exceed the follower's per-step clamp."""
    return max(frames, math.ceil(2.3 * float(np.abs(delta[:5]).max()) / MAX_STEP_DEG))


def _wobble(rng_seed: int, n: int, amp: float) -> np.ndarray:
    """Slow smooth hand tremor, (n, 5) degrees: three sinusoids of 0.3-1.2 Hz per arm joint."""
    rng = np.random.default_rng(rng_seed)
    t = np.arange(n) / FPS
    out = np.zeros((n, len(ARM_JOINTS)))
    for j in range(len(ARM_JOINTS)):
        for _ in range(3):
            out[:, j] += rng.uniform(0.3, 1.0) * np.sin(2 * math.pi * rng.uniform(0.3, 1.2) * t + rng.uniform(0, 2 * math.pi))
    return amp * out / 2.0


def plan_actions(kin: Kinematics, p: EpisodeParams, force_seed_xyz=None) -> tuple[np.ndarray, dict]:
    """The commanded joint targets of one episode, (frames, 6) float32, plus the first frame of every phase."""
    ph = dict(p.phases)
    skew = np.random.default_rng(p.wobble_seed ^ 0x5EED).uniform(0.85, 1.2, 4)
    box = placed_box(p)
    seed_true = np.asarray(force_seed_xyz if force_seed_xyz is not None else p.seed_xyz(p.target), dtype=float)
    others = [p.seed_xyz(i) for i in p.present if i != p.target]
    aimed = seed_true + np.array([*p.aim_error, 0.0])  # the operator sees the seed a millimetre or two off
    if np.linalg.norm(aimed[:2] - [layout.BASE_PAN_AXIS[0], 0.0]) > 0.40:
        raise Unreachable(f"seed at {aimed[0]:.2f}, {aimed[1]:.2f} is beyond the arm's reach")
    grasp, spin = grasp_test.grasp_pose(aimed, layout.SEED_RADIUS[p.color], box, others, math.radians(p.box.yaw_deg))
    act_start = json.loads((CONFIG_DIR / "poses.json").read_text())["act_start"]
    q_start = np.array([act_start[j] for j in JOINTS]) + np.array(p.start_noise_deg)
    start_dict = dict(zip(JOINTS, q_start))
    what = f"{p.color} seed {p.target}"
    above = _solve(kin, grasp + [0, 0, APPROACH_Z], start_dict, spin, what + " above")
    q_above = _vec(above)
    segments, marks, frame = [], {}, 0

    def add(name, rows):
        nonlocal frame
        marks[name] = frame
        segments.append(np.asarray(rows, dtype=float))
        frame += len(rows)

    g_open = p.open_g
    add("idle", np.tile(q_start, (ph["idle"], 1)))
    marks["open"] = frame + int(0.3 * ph["transit"])  # the gripper starts opening during the transit
    n = _frames_for(ph["transit"], q_above - q_start)
    s = _ease(n, skew[0])
    rows = q_start + (q_above - q_start) * s[:, None]
    ramp = _min_jerk(np.clip((np.arange(1, n + 1) / n - 0.3) / 0.55, 0, 1))
    rows[:, 5] = q_start[5] + (g_open - q_start[5]) * ramp
    add("transit", rows)
    n, sol = ph["descend"], above
    s, rows = _ease(n, skew[1]), []
    for u in s:
        sol = _solve(kin, (grasp + [0, 0, APPROACH_Z * (1 - u)]), sol, spin, what + " descent")
        rows.append(_vec(sol))
    rows = np.array(rows)
    rows[:, 5] = g_open
    add("descend_start", rows)
    marks["descend_start"] = marks["descend_start"]
    q_grasp = rows[-1].copy()
    add("settle", np.tile(q_grasp, (ph["settle"], 1)))
    n = ph["close"]
    rows = np.tile(q_grasp, (n, 1))
    rows[:, 5] = g_open + (p.close_g - g_open) * _ease(n, 0.9)
    add("close_start", rows)
    q_closed = q_grasp.copy()
    q_closed[5] = p.close_g
    add("hold", np.tile(q_closed, (ph["hold"], 1)))
    n, sol = ph["lift"], dict(zip(JOINTS, q_grasp))
    rows = []
    for u in _ease(n, skew[2]):
        sol = _solve(kin, grasp + [0, 0, LIFT_M * u], sol, spin, what + " lift")
        rows.append(_vec(sol))
    rows = np.array(rows)
    rows[:, 5] = p.close_g
    add("lift_start", rows)
    q_lift = rows[-1].copy()
    q_rest = np.array([*p.rest_pose, p.close_g])
    n = _frames_for(ph["retract"], q_rest - q_lift)
    s = _ease(n, skew[3])
    add("retract_start", q_lift + (q_rest - q_lift) * s[:, None])
    rest_frames = p.total_frames - frame
    if rest_frames < 0:  # a long swing needed more frames than the episode has: another placement, please
        raise Unreachable(f"{what}: the motion needs {frame} frames, the episode has {p.total_frames}")
    marks["rest_start"] = frame
    segments.append(np.tile(q_rest, (rest_frames, 1)))
    actions = np.concatenate(segments)
    # a slow hand wobble on the arm joints, silent while the jaws are near the seed (descent to lift)
    envelope = np.ones(len(actions))
    quiet = slice(marks["descend_start"], marks["lift_start"] + 1)
    envelope[quiet] = 0.0
    envelope = np.convolve(envelope, np.ones(15) / 15, mode="same")
    actions[:, :5] += _wobble(p.wobble_seed, len(actions), RANDOM.wobble_deg)[:, :5] * envelope[:, None]
    marks["frames"] = len(actions)
    return actions.astype(np.float32), marks


# -- success and one rollout ----------------------------------------------------------------------------------
def episode_success(seed_rest: np.ndarray, seed_end: np.ndarray, tool_end: np.ndarray, peak_lift: float) -> bool:
    """Kept episode: the seed rose over 3 cm and ends in the jaws (within 2 cm of the tool frame), still lifted."""
    return bool(peak_lift > LIFT_MIN_M and seed_end[2] - seed_rest[2] > LIFT_MIN_M
                and np.linalg.norm(np.asarray(seed_end) - np.asarray(tool_end)) < IN_JAWS_M)


@dataclass
class Rollout:
    actions: np.ndarray  # (N, 6) float32, what the leader commanded
    states: np.ndarray  # (N, 6) float32, what the follower measured before each command
    top: np.ndarray  # (N, 480, 640, 3) uint8
    wrist: np.ndarray
    success: bool
    info: dict = field(default_factory=dict)


@functools.lru_cache(maxsize=1)
def _kinematics() -> Kinematics:
    return Kinematics()


def simulate_episode(p: EpisodeParams, kin: Kinematics | None = None) -> Rollout:
    """Plan the episode, then play it through the simulated follower while recording what the policy would see."""
    actions, marks = plan_actions(kin or _kinematics(), p)
    robot = SimRobot(initial=dict(zip(JOINTS, map(float, actions[0]))))
    try:
        apply_scene(robot, p)
        hold = robot.read_joints()
        for _ in range(SETTLE_STEPS):
            robot.send_joints(hold)
        seed_rest = grasp_test.seed_xyz(robot, p.color, p.target)
        n = len(actions)
        states = np.zeros((n, 6), np.float32)
        top = np.zeros((n, *IMAGE_SHAPE), np.uint8)
        wrist = np.zeros_like(top)
        peak = 0.0
        for t in range(n):
            obs = robot.read_observation()
            states[t], top[t], wrist[t] = obs["observation.state"], obs["observation.images.top"], obs["observation.images.wrist"]
            robot.send_joints(dict(zip(JOINTS, map(float, actions[t]))))
            peak = max(peak, float(grasp_test.seed_xyz(robot, p.color, p.target)[2] - seed_rest[2]))
        seed_end, tool_end = grasp_test.seed_xyz(robot, p.color, p.target), grasp_test.tool_xyz(robot)
        moved = [float(np.linalg.norm(grasp_test.seed_xyz(robot, p.color, i)[:2] - p.seed_xyz(i)[:2]))
                 for i in p.present if i != p.target]
        ok = episode_success(seed_rest, seed_end, tool_end, peak)
        info = {"lift_mm": 1000 * float(seed_end[2] - seed_rest[2]), "peak_lift_mm": 1000 * peak,
                "seed_to_tool_mm": 1000 * float(np.linalg.norm(seed_end - tool_end)),
                "other_seed_moved_mm": 1000 * max(moved, default=0.0), "phases": {k: int(v) for k, v in marks.items()}}
        return Rollout(actions, states, top, wrist, ok, info)
    finally:
        robot.close()


# -- the dataset ----------------------------------------------------------------------------------------------
def _read_log(root: Path) -> list[dict]:
    path = root / LOG_NAME
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _append_log(root: Path, record: dict) -> None:
    with open(root / LOG_NAME, "a") as f:
        f.write(json.dumps(record) + "\n")


def _open_dataset(root: Path, repo_id: str):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    if (root / "meta" / "info.json").exists():
        return LeRobotDataset.resume(repo_id, root=root)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()
    return LeRobotDataset.create(repo_id, FPS, FEATURES, root=root, robot_type=ROBOT_TYPE, use_videos=True)


def summarise(log: list[dict]) -> dict:
    """Totals over the whole log: `success_rate` is kept episodes per attempt (every attempt is simulated, the
    placements the planner could not reach were thrown away before); `placement_acceptance` is the share of drawn object
    placements (3 per scene) that ended up in a scene the planner could reach; `geometry_acceptance` counts the
    scenes that passed the geometric constraints and `ik_acceptance` the share of those the planner could grasp in."""
    saved = sum(1 for r in log if r["ok"])
    draws = sum(r.get("proposals", 0) for r in log)
    ik = sum(r.get("ik_rejections", 0) for r in log)
    return {"saved": saved, "attempts": len(log), "failed": len(log) - saved, "ik_rejections": ik,
            "success_rate": saved / len(log) if log else 0.0,
            "placement_acceptance": 3 * len(log) / draws if draws else 0.0,
            "geometry_acceptance": 3 * (len(log) + ik) / draws if draws else 0.0,  # in view, in reach, no overlap
            "ik_acceptance": len(log) / (len(log) + ik) if log else 0.0}  # ... and the planner can grasp the seed


def build_dataset(root: str | Path, color: str, episodes: int, seed: int, *, repo_id: str | None = None,
                  rollout: Callable[..., Rollout] = simulate_episode, kin: Kinematics | None = None,
                  progress: Callable[[str], None] = lambda msg: None) -> dict:
    """Record successful scripted episodes until the dataset holds `episodes`; resumes an existing one.

    Attempts are numbered from 0 and drawn from `sample_params(color, seed, attempt, resample)`; a placement the
    planner cannot reach (`Unreachable`) is replaced by the next `resample` of the same attempt. Every attempt (kept
    or failed) is one line of `<root>/sim_generation.jsonl`."""
    root = Path(root)
    repo_id = repo_id or f"{HF_USER}/smartseed-sim-grasp-{color}"
    ds = _open_dataset(root, repo_id)
    root.mkdir(parents=True, exist_ok=True)
    log = _read_log(root)
    start = ds.meta.total_episodes
    if sum(1 for r in log if r["ok"]) < start:  # stopped between save_episode and the log line
        for _ in range(start - sum(1 for r in log if r["ok"])):
            record = {"attempt": len(log), "ok": True, "reason": "recovered", "color": color, "seed": seed,
                      "target": None, "episode_index": None}
            _append_log(root, record), log.append(record)
    result = {"resumed_from": start}
    try:
        while ds.meta.total_episodes < episodes:
            attempt, t0, draws, rejected = len(log), time.time(), 0, 0
            while True:
                params = sample_params(color, seed, attempt, rejected)
                draws += params.proposals
                try:
                    run = rollout(params) if kin is None else rollout(params, kin)
                    break
                except Unreachable:
                    rejected += 1
                    if rejected > 200:
                        raise RuntimeError(f"attempt {attempt}: 200 placements in a row were unreachable")
            record = {"attempt": attempt, "ok": False, "reason": "", "color": color, "seed": seed,
                      "target": params.target, "present": list(params.present), "episode_index": None,
                      "proposals": draws, "ik_rejections": rejected}
            record |= {k: run.info[k] for k in ("lift_mm", "peak_lift_mm") if k in run.info}
            if run.success:
                for t in range(len(run.actions)):
                    ds.add_frame({"action": run.actions[t], "observation.state": run.states[t],
                                  "observation.images.top": run.top[t], "observation.images.wrist": run.wrist[t],
                                  "task": TASK})
                ds.save_episode()
                record |= {"ok": True, "reason": "kept", "episode_index": ds.meta.total_episodes - 1,
                           "frames": len(run.actions)}
            else:
                record["reason"] = (f"failed: lift {run.info.get('lift_mm', 0):.0f} mm, seed "
                                    f"{run.info.get('seed_to_tool_mm', float('nan')):.0f} mm from the tool")
            _append_log(root, record), log.append(record)
            progress(f"attempt {attempt}: {record['reason']} ({rejected} unreachable placements, "
                     f"{time.time() - t0:.0f} s) {ds.meta.total_episodes}/{episodes}")
    finally:
        ds.finalize()
    return result | summarise(log)


def generator_commit() -> str:
    """Last commit that touched the twin or the robot code the generator drives (docs-only commits do not count)."""
    try:
        return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h", "--", "sim", "backend/smartseed_robot"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def dataset_card(color: str, repo_id: str, commit: str, stats: dict) -> str:
    real = REAL_REPOS[color]
    box = {"black": "black seeds in the black box (real source `d1`)",
           "white": "white seeds in the white box (real source `d2`)"}[color]
    r = RANDOM
    rate = f"{100 * stats['success_rate']:.0f} %" if stats.get("success_rate") is not None else "n/a"
    tags = ["LeRobot", "BraboRobots", "smartseed", "robotekin-hackathon", "lerobot", "so101", "simulation", "mujoco"]
    front = "\n".join(["---", "license: apache-2.0", "task_categories:", "- robotics", "tags:",
                       *[f"- {t}" for t in tags], "configs:", "- config_name: default", "  data_files: data/*/*.parquet",
                       "---"])
    return f"""{front}

# {repo_id.split("/")[-1]}

**Simulated** demonstrations of the SmartSeed grasp task ({box}), generated in a MuJoCo twin of the scene. They are not
real recordings. The schema is the one of [`{real}`](https://huggingface.co/datasets/{real}) (codebase `v3.0`,
{FPS} fps, `robot_type` `{ROBOT_TYPE}`, same keys, shapes and units), so the same training scripts work unchanged and
real and simulated episodes can be mixed or fine-tuned across.

- Task: `{TASK}`
- Episodes: {stats.get("episodes", "?")}, frames: {stats.get("frames", "?")}; generator success rate {rate} \
({stats.get("attempts", "?")} attempts)
- Generator: `sim/make_dataset.py` of {GITHUB} at commit `{commit}` (the twin, the planner and the randomisation live
  there; `sim/README.md`, "Generating sim datasets")

## Features

| key | shape | content |
|---|---|---|
| `observation.state` | 6 float32 | measured follower joints: `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll` in degrees, `gripper` 0-100 |
| `action` | 6 float32 | commanded (leader) joint targets, same names and units |
| `observation.images.top` | 480x640x3 video | the twin's top camera |
| `observation.images.wrist` | 480x640x3 video | the twin's wrist camera |

## What an episode does

Like the real teleop episodes: rest at the taught `act_start`, open the gripper while moving above a seed, descend,
close, lift, fold back to the rest pose with the seed in the jaws and hold there until frame 300 (real episodes are
278-300 frames). Motion is min-jerk interpolation with random timing, a slow hand wobble and a 1.5 mm aiming error. The
grasp is plain contact physics (no weld, no attach). Only episodes where the seed rose over 3 cm and is still in the
jaws at the end are kept.

## Randomisation (per episode)

| what | bound |
|---|---|
| seeds per box / which one is grasped | {r.seeds_min}-{r.seeds_max} of 4 / one of the colour's seeds |
| seed position | uniform on the box floor, {1000 * r.seed_wall_margin_m:.0f} mm off the inner walls, at least {1000 * r.seed_min_gap_m:.0f} mm apart |
| box and tray pose | the two boxes and the 3x4 tray anywhere on the table the top camera sees (uniform position, any yaw, no overlap, {1000 * r.view_margin_m:.0f} mm inside the view, centre within {100 * r.reach_max_m:.0f} cm of the arm, {100 * r.base_keepout_m:.0f} cm clear of its base); placements the planner cannot reach are redrawn |
| light | intensity x{r.light_scale[0]}-{r.light_scale[1]}, direction tilted up to {r.light_tilt_deg:.0f} deg |
| colours | +-{100 * r.colour_jitter:.0f} % per channel on table, mat and cardboard (the twin has no textures) |
| top camera | +-{1000 * r.top_cam_shift_m:.0f} mm, +-{r.cam_rot_deg:.0f} deg |
| wrist camera | +-{1000 * r.wrist_cam_shift_m:.0f} mm on the gripper |
| start pose | `act_start` plus per-joint noise (pan +-{r.start_noise_deg["shoulder_pan"]:.0f}, wrist +-{r.start_noise_deg["wrist_flex"]:.0f} deg) |

`sim_generation.jsonl` logs every attempt (kept, failed, unreachable) with its seed and target.

## Limits

The twin is not the real scene: flat colours, no print on the mat, no lens distortion, estimated box and seed layout,
untuned servo dynamics (`sim/README.md`, "What is weak"). A policy trained on this data alone will see a visual gap on
the real arm.
"""


def push_dataset(root: Path, repo_id: str, card: str, *, private: bool = False) -> str:
    """Upload the dataset folder plus its card to the Hub (existing login) and tag it with the codebase version."""
    from huggingface_hub import HfApi

    (root / "README.md").write_text(card)
    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    api.upload_folder(folder_path=str(root), repo_id=repo_id, repo_type="dataset",
                      commit_message="Upload simulated SmartSeed grasp demonstrations")
    version = REAL["codebase_version"]
    try:
        api.delete_tag(repo_id, tag=version, repo_type="dataset")
    except Exception:  # first push: no tag yet
        pass
    api.create_tag(repo_id, tag=version, repo_type="dataset")
    return f"https://huggingface.co/datasets/{repo_id}"


def make_contact_sheet(roots: dict[str, Path], out: Path, episodes: int = 3) -> None:
    """PNG: per colour and episode one row of top | wrist at the first, middle and last frame."""
    import imageio.v2 as imageio
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    def hwc(t):
        return (t.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)

    rows = []
    for color, root in roots.items():
        ds = LeRobotDataset(f"{HF_USER}/smartseed-sim-grasp-{color}", root=root)
        for ep in np.linspace(0, ds.meta.total_episodes - 1, episodes).round().astype(int):
            lo, hi = int(ds.meta.episodes["dataset_from_index"][ep]), int(ds.meta.episodes["dataset_to_index"][ep])
            cells = []
            for i in (lo, (lo + hi) // 2, hi - 1):
                item = ds[i]
                cells.append(np.vstack([hwc(item["observation.images.top"]), hwc(item["observation.images.wrist"])])[::3, ::3])
            rows.append(np.hstack(cells))
    out.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(str(out), np.vstack(rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--color", choices=["black", "white"], required=True)
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="dataset folder (default sim/out/datasets/smartseed-sim-grasp-<colour>)")
    ap.add_argument("--push-repo", default=None, help="Hub dataset repo to upload to when done (existing HF login)")
    args = ap.parse_args()
    root = Path(args.out or ROOT / "sim" / "out" / "datasets" / f"smartseed-sim-grasp-{args.color}")
    repo_id = args.push_repo or f"{HF_USER}/smartseed-sim-grasp-{args.color}"
    summary = build_dataset(root, args.color, args.episodes, args.seed, repo_id=repo_id,
                            progress=lambda msg: print(msg, flush=True))
    print(json.dumps(summary))
    if args.push_repo:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        ds = LeRobotDataset(repo_id, root=root)
        stats = {"episodes": ds.meta.total_episodes, "frames": ds.meta.total_frames, **summary}
        print("pushed", push_dataset(root, args.push_repo, dataset_card(args.color, args.push_repo, generator_commit(), stats)))


if __name__ == "__main__":
    main()
