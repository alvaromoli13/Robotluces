"""T5: success rate of an ACT policy in the twin, on scenes the dataset generator draws but the datasets never used.

    backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-black-c100 --color black
    backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-white-c100 --color white --checkpoint 020000 --episodes 20
    backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-white-c100 --color white --split train   # sanity check
    backend/.venv/bin/python sim/eval.py --repo RafaelJaime/act-sim-black-narrow-c100 --color black --layout narrow

A scene is `make_dataset.sample_params(color, HELDOUT_SEED, attempt, resample)`: the same layout sampling (boxes and tray
anywhere in the top view, any yaw, 2-4 seeds per box, light, colours, camera and start-pose noise) as the training data
(`--layout narrow`: boxes and tray near their nominal pose, as in the `-v3-narrow` datasets),
and it is kept only if the scripted planner can grasp in it (`plan_actions` does not raise), exactly like a dataset
episode. The datasets used seed 0; RNG streams of different seeds are independent, so no held-out scene is a training one.
`--split train` replays the kept scenes of the training log instead (a policy that fails there memorised nothing).

The loop is `run_policy.run_episode`: the arm starts at the taught `act_start` plus the scene's start noise, the policy gets
the `RobotPort` observation each 1/30 s and its action goes out through `send_joints`. SUCCESS = a seed of the target
colour rose more than 3 cm above its resting height at some moment (as in the generator). "Lands in the target hole" is
NOT measured: the scripted demos never place the seed either (they fold back holding it), so there is nothing to compare to.
`held` additionally reports the episodes that end with a seed within 2 cm of the tool frame.
"""
from __future__ import annotations

import argparse
import functools
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import make_dataset as md, run_policy  # noqa: E402
from smartseed_robot.kinematics import Kinematics  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402

HELDOUT_SEED = 1000  # the training datasets were generated with seed 0
OUT_DIR = ROOT / "sim" / "out" / "eval"
VIDEO_EPISODES = 5
HZ = run_policy.HZ


@dataclass
class Summary:
    color: str
    episodes: int = 0
    successes: int = 0
    held: int = 0
    max_lift_mm: list[float] = field(default_factory=list)
    closest_mm: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / self.episodes if self.episodes else 0.0

    def line(self, name: str = "") -> str:
        return (f"{name or 'policy'} ({self.color}): {self.successes}/{self.episodes} lifted a seed over 3 cm "
                f"({100 * self.success_rate:.0f} %); ends holding one {self.held}/{self.episodes}; "
                f"max lift mean {np.mean(self.max_lift_mm):.1f} mm, best {max(self.max_lift_mm):.1f} mm; "
                f"closest tool-seed approach mean {np.mean(self.closest_mm):.0f} mm, best {min(self.closest_mm):.0f} mm")


def heldout_scenes(color: str, n: int, *, seed: int = HELDOUT_SEED, kin: Kinematics | None = None,
                   layout_mode: str = "wide") -> list[md.EpisodeParams]:
    """The first `n` plannable scenes of `seed`: attempts are numbered from 0, and a placement the planner cannot grasp
    in is replaced by the next `resample` of the same attempt, as `build_dataset` does."""
    kin, scenes = kin or Kinematics(), []
    for attempt in range(n):
        rejected = 0
        while True:
            p = md.sample_params(color, seed, attempt, rejected, md.LAYOUTS[layout_mode])
            try:
                md.plan_actions(kin, p)
                break
            except md.Unreachable:
                rejected += 1
                if rejected > md.MAX_REJECTIONS:
                    raise RuntimeError(f"attempt {attempt}: {md.MAX_REJECTIONS} placements in a row were unreachable")
        scenes.append(p)
    return scenes


def train_scenes(color: str, n: int, layout_mode: str = "wide") -> list[md.EpisodeParams]:
    """The first `n` kept scenes of the local training log (`make_dataset.py`, seed 0)."""
    log = md._read_log(ROOT / "sim" / "out" / "datasets" / md.dataset_name(color, layout_mode))
    scenes = md.logged_scenes(log, layout_mode)
    if len(scenes) < n:
        raise SystemExit(f"the training log of {color} has {len(scenes)} scenes, {n} asked")
    return scenes[:n]


@functools.lru_cache(maxsize=256)
def start_pose(p: md.EpisodeParams) -> dict[str, float]:
    """Where the generator's arm starts this scene: the first commanded pose of its demonstration (the taught
    `act_start`, the scene's start noise and the first sample of the hand wobble)."""
    return dict(zip(JOINTS, map(float, md.plan_actions(_kin(), p)[0][0])))


@functools.lru_cache(maxsize=1)
def _kin() -> Kinematics:
    return Kinematics()


def run_scene(policy, p: md.EpisodeParams, *, duration_s: float = run_policy.DURATION_S, record: bool = False,
              on_frame: Callable[[int, np.ndarray, float], None] | None = None,
              on_robot: Callable[[SimRobot], None] | None = None) -> run_policy.EpisodeResult:
    """One episode in scene `p`; `on_robot` sees the robot once the scene is applied (tests poke at it)."""
    robot = SimRobot(initial=start_pose(p))
    try:
        md.apply_scene(robot, p)
        if on_robot:
            on_robot(robot)
        return run_policy.run_episode(robot, policy, p.color, duration_s=duration_s, record=record, on_frame=on_frame)
    finally:
        robot.close()


def evaluate(policy, color: str, scenes: list[md.EpisodeParams], *, duration_s: float = run_policy.DURATION_S,
             video: Path | None = None, video_episodes: int = VIDEO_EPISODES, name: str = "",
             log: Callable[[str], None] = lambda msg: None) -> Summary:
    """Run the policy once per scene; film the first `video_episodes` into one mp4 when `video` is given."""
    import imageio.v2 as imageio

    summary, writer = Summary(color), None
    if video:
        Path(video).parent.mkdir(parents=True, exist_ok=True)
        writer = imageio.get_writer(str(video), fps=HZ, codec="libx264", macro_block_size=1)
    try:
        for ep, p in enumerate(scenes):
            def on_frame(step, frame, lift, ep=ep, p=p):
                if writer is not None and ep < video_episodes:
                    writer.append_data(run_policy._label(
                        frame, f"{name} -> {color}  scene {p.attempt}  t={step / HZ:4.1f}s  lift {lift:5.1f} mm"))

            r = run_scene(policy, p, duration_s=duration_s, on_frame=on_frame)
            summary.episodes += 1
            summary.successes += r.success
            summary.held += r.in_jaws
            summary.max_lift_mm.append(r.max_lift_mm)
            summary.closest_mm.append(r.min_tool_seed_mm)
            log(f"{name} scene {p.attempt}: max lift {r.max_lift_mm:6.1f} mm  closest {r.min_tool_seed_mm:5.0f} mm  "
                f"gripper {r.final_gripper:5.1f}  in jaws {r.in_jaws}  {'SUCCESS' if r.success else 'fail'}")
    finally:
        if writer is not None:
            writer.close()
    return summary


def planner_ceiling(color: str, n: int, *, seed: int = HELDOUT_SEED, layout_mode: str = "wide",
                    rollout: Callable[..., md.Rollout] = md.simulate_episode, kin: Kinematics | None = None,
                    log: Callable[[str], None] = lambda msg: None, dart_noise_deg: float = 0.0) -> dict:
    """The ceiling for a policy: the scripted planner (the demonstrator) on the same held-out scenes, through the physics
    and the wall monitor, no rendering. `successes`: the seed was lifted and held; `kept`: also wall-valid (what the
    dataset generator would keep). `dart_noise_deg` > 0 flies the DART perturbation (as `make_dataset.py --dart-noise`)."""
    kin = kin or Kinematics()
    extra = {"dart_noise_deg": dart_noise_deg} if dart_noise_deg > 0 else {}
    episodes = successes = valid = kept = 0
    for p in heldout_scenes(color, n, seed=seed, kin=kin, layout_mode=layout_mode):
        r = rollout(p, kin, render=False, **extra)  # physics only; only three numbers per episode are kept, never the frames
        episodes, successes, valid = episodes + 1, successes + bool(r.success), valid + bool(r.valid)
        kept += bool(r.success and r.valid)
        log(f"scene {p.attempt}: lift {r.info.get('lift_mm', float('nan')):6.1f} mm  success {r.success}  wall-valid {r.valid}")
        del r
    return {"episodes": episodes, "successes": successes, "valid": valid, "kept": kept,
            "success_rate": successes / episodes, "kept_rate": kept / episodes}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=None, help="Hub repo id or local path of the ACT policy (not needed with --planner)")
    ap.add_argument("--planner", action="store_true",
                    help="no policy: run the scripted planner on the held-out scenes (the ceiling for a policy)")
    ap.add_argument("--checkpoint", default=None, help="intermediate checkpoint step, e.g. 020000 (default: final model)")
    ap.add_argument("--color", choices=["black", "white"], required=True)
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seed", type=int, default=HELDOUT_SEED, help="generator seed of the held-out scenes")
    ap.add_argument("--layout", choices=sorted(md.LAYOUTS), default="wide",
                    help="scene distribution; use the one the policy was trained on (narrow for the v3-narrow datasets)")
    ap.add_argument("--dart-noise", type=float, default=0.0, metavar="DEG",
                    help="with --planner: fly the DART perturbation of this size (degrees) to measure the ceiling of the dart demos")
    ap.add_argument("--split", choices=["heldout", "train"], default="heldout")
    ap.add_argument("--n-action-steps", type=int, default=None,
                    help="actions played per inference (default: the trained chunk, played open loop)")
    ap.add_argument("--temporal-ensemble", type=float, default=None, metavar="COEFF",
                    help="re-plan every step and blend the overlapping chunks (ACT paper: 0.01)")
    ap.add_argument("--duration", type=float, default=run_policy.DURATION_S, help="seconds per episode (sim time)")
    ap.add_argument("--device", default=None, help="torch device (default: mps if available, else cpu)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    if not args.planner and not args.repo:
        ap.error("--repo is required unless --planner is given")
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.planner:
        res = planner_ceiling(args.color, args.episodes, seed=args.seed, layout_mode=args.layout,
                              log=lambda msg: print(msg, flush=True), dart_noise_deg=args.dart_noise)
        print(f"scripted planner ({args.color}, {args.layout}, seed {args.seed}, dart noise {args.dart_noise:g} deg): {res['successes']}/{res['episodes']} lifted and held "
              f"({100 * res['success_rate']:.0f} %), {res['kept']}/{res['episodes']} also wall-valid ({100 * res['kept_rate']:.0f} %)")
        return
    from smartseed_robot.act import pick_device

    device = pick_device(args.device)
    name = (run_policy.policy_name(args.repo, args.checkpoint) + ("" if args.split == "heldout" else "-train")
            + ("" if args.layout == "wide" else f"-{args.layout}")
            + run_policy.inference_tag(args.n_action_steps, args.temporal_ensemble))
    print(f"{name}: loading {args.repo} (checkpoint {args.checkpoint or 'final'}) on {device}", flush=True)
    policy = run_policy.load_policy(args.repo, args.checkpoint, device, n_action_steps=args.n_action_steps,
                                    temporal_ensemble_coeff=args.temporal_ensemble)
    scenes = (heldout_scenes(args.color, args.episodes, seed=args.seed, layout_mode=args.layout)
              if args.split == "heldout" else train_scenes(args.color, args.episodes, args.layout))
    video = Path(args.out_dir) / f"eval_{name}.mp4"
    summary = evaluate(policy, args.color, scenes, duration_s=args.duration, video=video, name=name,
                       log=lambda msg: print(msg, flush=True))
    print(summary.line(name), f"\nvideo {video} (first {VIDEO_EPISODES} episodes)")


if __name__ == "__main__":
    main()
