"""Run a real-trained ACT policy inside the MuJoCo twin and film what it sees.

    backend/.venv/bin/python sim/run_policy.py --repo RafaelJaime/act-smartseed-d1-c100 --color black
    backend/.venv/bin/python sim/run_policy.py --repo RafaelJaime/act-smartseed-d2-c50 --color white --episodes 10
    backend/.venv/bin/python sim/run_policy.py --obs-compare real_top.png real_wrist.png --color white

The loop is the one `ActGrasp.run` runs against the real arm (`backend/smartseed_robot/act.py`): the arm starts at the
taught `act_start`, every control period the policy gets the `RobotPort` observation (`observation.state` in degrees,
gripper 0-100, `observation.images.top` / `.wrist` as 480x640 RGB uint8) and its action goes out as joint targets
through `send_joints` (same per-step clamp as the follower). The model is loaded by the same `resolve_spec` +
`LeRobotActPolicy` the backend uses, so pre/post-processing, normalisation and action-chunk handling are lerobot's.
Differences from the real run: simulated time advances exactly 1/30 s per step (no inference latency, no skipped
periods), and the scene is the twin (`sim/README.md` lists what differs from the real images).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import layout  # noqa: E402
from smartseed_robot.act import ACT_START_FALLBACK, LeRobotActPolicy, PolicyRunner  # noqa: E402
from smartseed_robot.catalog import resolve_spec  # noqa: E402
from smartseed_robot.robot import IMAGE_SHAPE  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

HZ = 30.0
CONFIG_DIR = ROOT / "sim" / "config"
DURATION_S = 10.0  # SMARTSEED_ACT_DURATION_S default
LIFT_MIN_MM = 30.0  # success: any seed of the colour rose more than this above its resting height
IN_JAWS_M = 0.02  # a seed this close to the tool frame at the end is between the jaws
SETTLE_STEPS = 15  # the arm holds act_start and the seeds settle before the policy starts
SEEDS_PER_BOX = 4
MEDIA_DIR = ROOT / "docs" / "media"
OUT_DIR = ROOT / "sim" / "out"


@dataclass
class EpisodeResult:
    color: str
    steps: int = 0
    sim_seconds: float = 0.0
    max_lift_mm: float = 0.0
    min_tool_seed_mm: float = float("inf")  # closest approach of the tool frame to a seed of the colour
    final_gripper: float = 0.0
    in_jaws: bool = False
    success: bool = False
    frames: list = field(default_factory=list, repr=False)


def load_act_start(path: Path = CONFIG_DIR / "poses.json") -> dict[str, float]:
    """The taught `act_start` of the sim config (the one taught on the real arm), else the executor's fallback."""
    if path.exists():
        pose = json.loads(path.read_text()).get("act_start")
        if pose:
            return pose
    return dict(ACT_START_FALLBACK)


def make_robot(act_start: dict[str, float]) -> SimRobot:
    return SimRobot(initial=act_start)


def policy_name(repo: str, checkpoint: str | None = None) -> str:
    name = repo.rsplit("/", 1)[-1].removeprefix("act-smartseed-")
    return f"{name}-{checkpoint}" if checkpoint else name


def inference_tag(n_action_steps: int | None = None, temporal_ensemble_coeff: float | None = None) -> str:
    """Media-name suffix for a non-default chunk execution (empty for the trained default)."""
    if temporal_ensemble_coeff is not None:
        return f"-te{temporal_ensemble_coeff:g}"
    return f"-n{n_action_steps}" if n_action_steps is not None else ""


def load_policy(repo: str, checkpoint: str | None = None, device: str | None = None, *,
                resolver: Callable[[str, str | None], str] = resolve_spec,
                factory: Callable[..., PolicyRunner] = LeRobotActPolicy,
                n_action_steps: int | None = None, temporal_ensemble_coeff: float | None = None) -> PolicyRunner:
    """Same path as the backend: `resolve_spec` (final model = repo, checkpoint = local download) then lerobot.
    The optional overrides change only how the chunks are executed (see `apply_inference_overrides`)."""
    overrides = {k: v for k, v in (("n_action_steps", n_action_steps),
                                   ("temporal_ensemble_coeff", temporal_ensemble_coeff)) if v is not None}
    return factory(resolver(repo, checkpoint), device, **overrides)


def seed_xyz(robot: SimRobot, color: str, index: int) -> np.ndarray:
    adr = robot._model.joint(f"seed_{color}_{index}_free").qposadr[0]
    return robot._data.qpos[adr:adr + 3].copy()


def jitter_seeds(robot: SimRobot, color: str, jitter: float, rng: np.random.Generator) -> None:
    """Shift every seed of the colour by a uniform error of up to `jitter` metres in x and y."""
    for i in range(SEEDS_PER_BOX):
        joint = robot._model.joint(f"seed_{color}_{i}_free")
        adr, dof = joint.qposadr[0], joint.dofadr[0]
        robot._data.qpos[adr:adr + 2] += rng.uniform(-jitter, jitter, 2)
        robot._data.qvel[dof:dof + 6] = 0


def _tool_xyz(robot: SimRobot) -> np.ndarray:
    return robot._data.site_xpos[robot._model.site("gripperframe").id].copy()


def run_episode(robot: SimRobot, policy: PolicyRunner, color: str, *, duration_s: float = DURATION_S,
                jitter: float = 0.0, rng: np.random.Generator | None = None, record: bool = False,
                on_frame: Callable[[int, np.ndarray, float], None] | None = None) -> EpisodeResult:
    """One closed-loop run. The robot is used as is (it starts at the pose it was built with)."""
    rng = rng or np.random.default_rng(0)
    if jitter:
        jitter_seeds(robot, color, jitter, rng)
    hold = robot.read_joints()
    for _ in range(SETTLE_STEPS):
        robot.send_joints(hold)
    rest = [seed_xyz(robot, color, i)[2] for i in range(SEEDS_PER_BOX)]
    policy.reset()
    result, t0 = EpisodeResult(color), robot.sim_time
    steps = max(1, round(duration_s * HZ))
    for step in range(steps):
        observation = robot.read_observation()
        action = policy.step(observation)
        robot.send_joints(action)
        lift = max(seed_xyz(robot, color, i)[2] - rest[i] for i in range(SEEDS_PER_BOX)) * 1000
        result.max_lift_mm = max(result.max_lift_mm, lift)
        tool = _tool_xyz(robot)
        result.min_tool_seed_mm = min(result.min_tool_seed_mm, 1000 * min(
            np.linalg.norm(seed_xyz(robot, color, i) - tool) for i in range(SEEDS_PER_BOX)))
        if record or on_frame:
            frame = np.hstack([observation["observation.images.top"], observation["observation.images.wrist"]])
            if record:
                result.frames.append(frame)
            if on_frame:
                on_frame(step, frame, lift)
    result.steps, result.sim_seconds = steps, robot.sim_time - t0
    result.final_gripper = robot.read_joints()["gripper"]
    tool = _tool_xyz(robot)
    result.in_jaws = any(np.linalg.norm(seed_xyz(robot, color, i) - tool) < IN_JAWS_M for i in range(SEEDS_PER_BOX))
    result.success = result.max_lift_mm > LIFT_MIN_MM
    return result


# -- media -----------------------------------------------------------------------------------------------------
def _label(frame: np.ndarray, text: str) -> np.ndarray:
    import cv2

    out = frame.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 24), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def save_strip(frames: list[np.ndarray], path: Path) -> None:
    """Six moments of one episode, top camera over wrist camera, at a third of the resolution."""
    import imageio.v2 as imageio

    w = IMAGE_SHAPE[1]
    cols = [np.vstack([f[:, :w][::3, ::3], f[:, w:][::3, ::3]]) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(str(path), np.hstack(cols))


def save_obs_comparison(real_top: Path, real_wrist: Path, out: Path, color: str) -> None:
    """Real frames (top | wrist) over the sim's frames at t=0 from the same `act_start`: the sim-to-real gap."""
    import imageio.v2 as imageio

    robot = make_robot(load_act_start())
    try:
        for _ in range(SETTLE_STEPS):
            robot.send_joints(robot.read_joints())
        obs = robot.read_observation()
    finally:
        robot.close()
    real = np.hstack([imageio.imread(str(real_top))[..., :3], imageio.imread(str(real_wrist))[..., :3]])
    sim = np.hstack([obs["observation.images.top"], obs["observation.images.wrist"]])
    rows = [_label(real, f"REAL ({color} run): top | wrist, what the policy saw at t=0"),
            _label(sim, "SIM twin at the same act_start pose: top | wrist")]
    out.parent.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(str(out), np.vstack(rows)[::2, ::2])


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", help="Hub repo id or local path of the ACT policy")
    ap.add_argument("--checkpoint", default=None, help="intermediate checkpoint step (default: the final model)")
    ap.add_argument("--color", choices=["black", "white"], default="black", help="the box whose seeds count")
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--duration", type=float, default=DURATION_S, help="seconds per episode (sim time)")
    ap.add_argument("--jitter", type=float, default=0.005, help="seed position error per axis, metres")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default=None, help="torch device (default: mps if available, else cpu)")
    ap.add_argument("--video-dir", default=str(OUT_DIR))
    ap.add_argument("--media-dir", default=str(MEDIA_DIR), help="where the PNG strip goes")
    ap.add_argument("--obs-compare", nargs=2, metavar=("REAL_TOP", "REAL_WRIST"),
                    help="write docs/media/sim-vs-real-obs.png from two real frames and exit")
    args = ap.parse_args(argv)
    if not args.repo and not args.obs_compare:
        ap.error("--repo is required")
    return args


def main(argv=None) -> None:
    import imageio.v2 as imageio

    args = parse_args(argv)
    if args.obs_compare:
        out = Path(args.media_dir) / "sim-vs-real-obs.png"
        save_obs_comparison(Path(args.obs_compare[0]), Path(args.obs_compare[1]), out, args.color)
        print(f"wrote {out}")
        return
    from smartseed_robot.act import pick_device

    device = pick_device(args.device)
    name = policy_name(args.repo, args.checkpoint)
    print(f"{name}: loading {args.repo} (checkpoint {args.checkpoint or 'final'}) on {device}", flush=True)
    policy = load_policy(args.repo, args.checkpoint, device)
    act_start, rng = load_act_start(), np.random.default_rng(args.seed)
    video = Path(args.video_dir) / f"act_{name}.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    total = max(1, round(args.duration * HZ))
    picks = {int(total * q) for q in (0.0, 0.2, 0.4, 0.6, 0.8)} | {total - 1}
    strip: dict[int, np.ndarray] = {}
    results = []
    with imageio.get_writer(str(video), fps=HZ, codec="libx264", macro_block_size=1) as writer:
        for ep in range(args.episodes):
            robot = make_robot(act_start)

            def on_frame(step, frame, lift, ep=ep):
                writer.append_data(_label(frame, f"{name} -> {args.color}  ep {ep}  t={step / HZ:4.1f}s  lift {lift:5.1f} mm"))
                if ep == 0 and step in picks:
                    strip[step] = frame

            try:
                r = run_episode(robot, policy, args.color, duration_s=args.duration, jitter=args.jitter, rng=rng,
                                on_frame=on_frame)
            finally:
                robot.close()
            results.append(r)
            print(f"{name} ep {ep}: max lift {r.max_lift_mm:6.1f} mm  closest {r.min_tool_seed_mm:5.0f} mm  gripper {r.final_gripper:5.1f}  "
                  f"in jaws {r.in_jaws}  {'SUCCESS' if r.success else 'fail'}", flush=True)
    save_strip([strip[k] for k in sorted(strip)], Path(args.media_dir) / f"sim-act-{name}.png")
    ok = sum(r.success for r in results)
    print(f"{name} ({args.color}): {ok}/{len(results)} succeeded; max lift mean "
          f"{np.mean([r.max_lift_mm for r in results]):.1f} mm, best {max(r.max_lift_mm for r in results):.1f} mm; "
          f"closest tool-seed approach {min(r.min_tool_seed_mm for r in results):.0f} mm (mean "
          f"{np.mean([r.min_tool_seed_mm for r in results]):.0f}); final gripper mean "
          f"{np.mean([r.final_gripper for r in results]):.1f}; in jaws "
          f"{sum(r.in_jaws for r in results)}/{len(results)}\nvideo {video}")


if __name__ == "__main__":
    main()
