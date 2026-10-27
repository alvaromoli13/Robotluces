"""Picture of one jaw against one wall: the same commanded motion in the v1 scene and in the v2 scene.

    # in a checkout of the v1 generator (see sim/audit_walls.py): plan the logged episode, save its actions and a close-up
    # at the control step of deepest wall overlap
    python sim/wall_check.py --log <v1 sim_generation.jsonl> --attempt 0 --out DIR
    # in this checkout: replay those actions in the v2 twin and save the close-up of the same step, then the pair
    python sim/wall_check.py --log <v1 sim_generation.jsonl> --attempt 0 --out DIR --replay DIR/actions.npz --pair docs/media/sim-wall-check.png

The close-up is a free camera aimed at the tool, looking down at the wall it is about to cross.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)), sys.path.insert(0, str(ROOT / "backend"))

from sim import collision, grasp_test, make_dataset as md  # noqa: E402
from smartseed_robot.robot import JOINTS  # noqa: E402
from smartseed_robot.sim_robot import SimRobot  # noqa: E402


def close_up(robot: SimRobot, size=(480, 640), distance: float = 0.16) -> np.ndarray:
    import mujoco

    cam = mujoco.MjvCamera()
    cam.type, cam.lookat[:], cam.distance, cam.azimuth, cam.elevation = mujoco.mjtCamera.mjCAMERA_FREE, grasp_test.tool_xyz(robot), distance, 150.0, -38.0
    renderer = mujoco.Renderer(robot._model, *size)
    try:
        renderer.update_scene(robot._data, camera=cam)
        return renderer.render().copy()
    finally:
        renderer.close()


def play(p: md.EpisodeParams, actions: np.ndarray, frame: int | None):
    """Play `actions` in this checkout's twin with the geometric wall monitor; returns (per-step penetration, the
    close-up at `frame`, or at the deepest overlap when None)."""
    robot = SimRobot(initial=dict(zip(JOINTS, map(float, actions[0]))))
    try:
        md.apply_scene(robot, p)
        monitor = collision.WallMonitor(robot._model, mode="geometry", every=1)
        hold = robot.read_joints()
        for _ in range(md.SETTLE_STEPS):
            robot.send_joints(hold)
        pens, image = [], None
        for t, row in enumerate(actions):
            robot.send_joints(dict(zip(JOINTS, map(float, row))))
            before = monitor.report().max_penetration_m
            monitor(robot._model, robot._data)
            pens.append(monitor.report().max_penetration_m)
            if frame is not None and t == frame:
                image = close_up(robot)
            elif frame is None and pens[-1] > before and pens[-1] == max(pens):
                image, deepest = close_up(robot), t
        return np.array(pens), image, (frame if frame is not None else deepest)
    finally:
        robot.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", required=True)
    ap.add_argument("--attempt", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", default=None, help="actions.npz saved by the v1 run: replay them here")
    ap.add_argument("--pair", default=None, help="PNG to write with the v1 and v2 close-ups side by side")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = {r["attempt"]: r for r in map(json.loads, Path(args.log).read_text().splitlines()) if r.get("seed") is not None}
    rec = log[args.attempt]
    p = md.sample_params(rec["color"], rec["seed"], args.attempt, rec.get("ik_rejections", 0))
    import imageio.v2 as imageio

    if args.replay is None:
        actions, marks = md.plan_actions(md.Kinematics(), p)
        pens, image, frame = play(p, actions, None)
        np.savez(out / "actions.npz", actions=actions, frame=frame, pen=pens[frame])
        imageio.imwrite(str(out / "close_up_v1.png"), image)
        print(f"v1: deepest overlap {1000 * pens.max():.1f} mm at control step {frame}")
        return
    saved = np.load(args.replay)
    pens, image, frame = play(p, saved["actions"], int(saved["frame"]))
    imageio.imwrite(str(out / "close_up_v2.png"), image)
    print(f"v2: same commands, deepest overlap {1000 * pens.max():.2f} mm; v1 had {1000 * float(saved['pen']):.1f} mm")
    if args.pair:
        from PIL import Image, ImageDraw

        left = Image.open(out / "close_up_v1.png").convert("RGB")
        right = Image.fromarray(image)
        sheet = Image.new("RGB", (left.width + right.width, left.height + 34), (255, 255, 255))
        sheet.paste(left, (0, 34)), sheet.paste(right, (left.width, 34))
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 10), f"v1: the gripper goes {1000 * float(saved['pen']):.1f} mm into the box wall (the commands of "
                           f"{rec['color']} attempt {args.attempt}, episode {rec.get('episode_index')} of v1)", fill=(160, 20, 20))
        draw.text((left.width + 8, 10), f"v2: the wall holds it ({1000 * pens.max():.1f} mm), the monitor rejects "
                                        "the episode and the planner redraws the scene", fill=(20, 110, 30))
        Path(args.pair).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.pair)


if __name__ == "__main__":
    main()
