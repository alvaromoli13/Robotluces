from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .act import ActConfig, ActGrasp, PolicyRunner
from .calibration import Calibration, CalibrationError
from .catalog import ModelCatalog
from .executor import Executor, ExecutorConfig, PlanError
from .kinematics import IKError, LazyKinematics
from .motion import MotionConfig, move_to
from .poses import PoseError, PoseStore
from .robot import FakeRobot, RobotPort

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Runtime:
    mode: str
    robot: RobotPort
    poses: PoseStore
    calibration: Calibration
    calibration_path: Path
    kin: object
    executor: Executor
    catalog: ModelCatalog | None = None


def build_runtime(mode: str | None = None, port: str | None = None, data_dir=None, robot: RobotPort | None = None,
                  kin=None, config: ExecutorConfig | None = None, act: ActConfig | None = None,
                  policy_factory: Callable[[str], PolicyRunner] | None = None,
                  catalog: ModelCatalog | None = None,
                  spec_resolver: Callable[[str, str | None], str] | None = None) -> Runtime:
    """`fake` (default) never opens a serial port; `real` needs SMARTSEED_ROBOT_PORT. With ACT policies configured
    the real follower also opens the top/wrist cameras (fake mode never does)."""
    mode = mode or os.environ.get("SMARTSEED_ROBOT", "fake")
    act = act or ActConfig.from_env()
    data = Path(data_dir or os.environ.get("SMARTSEED_DATA_DIR") or DEFAULT_DATA_DIR)
    if robot is None:
        if mode == "real":
            port = port or os.environ.get("SMARTSEED_ROBOT_PORT")
            if not port:
                raise ValueError("SMARTSEED_ROBOT=real needs SMARTSEED_ROBOT_PORT (e.g. /dev/tty.usbmodem...)")
            from .robot import LeRobotFollower

            robot = LeRobotFollower(port, {"top": act.cam_top, "wrist": act.cam_wrist} if act.enabled else None)
        elif mode == "fake":
            robot = FakeRobot()
        else:
            raise ValueError(f"SMARTSEED_ROBOT must be 'fake' or 'real', got '{mode}'")
    kin = kin or LazyKinematics()
    poses, cal_path = PoseStore(data / "poses.json"), data / "calibration.json"
    calibration = Calibration.load(cal_path)
    return Runtime(mode, robot, poses, calibration, cal_path, kin,
                   Executor(robot, poses, calibration, kin, config=config, mode=mode,
                            act=ActGrasp(act, policy_factory, spec_resolver) if act.enabled else None),
                   catalog or ModelCatalog())


class Cell(BaseModel):
    cell_index: int
    row: int
    col: int
    color: str = Field(pattern=r"^[a-z][a-z_-]{0,19}$")  # bowl colour id; the UI lets users define their own
    u: float
    v: float


class PlanBody(BaseModel):
    image_size: tuple[int, int]
    cells: list[Cell] = Field(min_length=1)
    mode: Literal["full", "grasp", "place"] = "full"  # grasp / place run one half of the cycle, for debugging
    drop_z: float | None = Field(default=None, ge=0.02, le=0.25)  # tool height (m) over the cell when releasing


class ActSelectBody(BaseModel):
    color: str = Field(pattern=r"^[a-z][a-z_-]{0,19}$")
    repo: str = Field(min_length=1)
    checkpoint: str | None = Field(default=None, pattern=r"^\d{1,12}$")  # None = the final model


class PointBody(BaseModel):
    u: float
    v: float
    image_size: tuple[int, int]
    x: float | None = None  # robot metres; defaults to the tool position from FK
    y: float | None = None


def create_router(rt: Runtime) -> APIRouter:
    router = APIRouter()
    ex = rt.executor

    def idle_only() -> None:
        if ex.running:
            raise HTTPException(409, "a plan is running; stop it first")

    def torque_off_refusal() -> JSONResponse | None:
        if rt.robot.torque_enabled:
            return None
        return JSONResponse({"detail": "torque is off; POST /robot/torque-on first", "code": "torque_off"},
                            status_code=409)

    @router.get("/robot/status")
    def status():
        return ex.status() | {"torque": rt.robot.torque_enabled}

    def act_models() -> tuple[list[dict], bool]:
        """Hub catalog plus the env defaults (always selectable, even offline), and whether the Hub was unreachable."""
        hub, offline = rt.catalog.models()
        models = {m["repo"]: m for m in hub}
        for color in ex.act.colors:
            repo = ex.act.config.policies[color]
            models.setdefault(repo, {"repo": repo, "checkpoints": []})
        return [m | {"name": m["repo"].rsplit("/", 1)[-1]} for m in models.values()], offline

    @router.get("/robot/act/models")
    def act_catalog():
        if ex.act is None:
            return {"enabled": False, "offline": False, "models": [], "active": {}}
        models, offline = act_models()
        return {"enabled": True, "offline": offline, "models": models, "active": ex.act.active()}

    @router.post("/robot/act/select")
    def act_select(body: ActSelectBody):
        def refuse(status: int, code: str, detail: str):
            return JSONResponse({"detail": detail, "code": code}, status_code=status)

        if ex.act is None:
            return refuse(409, "act_disabled", "no ACT policies are configured (SMARTSEED_ACT_POLICIES)")
        if ex.running:
            return refuse(409, "busy", "a plan is running; stop it before switching the ACT model")
        if not ex.act.has(body.color):
            return refuse(404, "unknown_color", f"no ACT policy for colour '{body.color}'")
        known = {m["repo"]: m["checkpoints"] for m in act_models()[0]}
        if body.repo not in known:
            return refuse(422, "unknown_model", f"'{body.repo}' is not in the ACT catalog")
        if body.checkpoint is not None and body.checkpoint not in known[body.repo]:
            return refuse(422, "unknown_checkpoint", f"'{body.repo}' has no checkpoint {body.checkpoint}")
        try:
            ex.act.select(body.color, body.repo, body.checkpoint)
        except Exception as exc:  # download or disk failure; the active policy is unchanged
            return refuse(502, "download_failed", f"could not fetch the model: {exc}")
        return {"active": ex.act.active()}

    @router.get("/robot/joints")
    def joints():
        j = rt.robot.read_joints()
        try:
            x, y, z = rt.kin.tool_xyz(j)
            tool = {"x": x, "y": y, "z": z}
        except Exception:  # FK is a convenience here; joints must still be readable
            tool = None
        return {"joints": j, "tool": tool}

    @router.get("/robot/poses")
    def poses():
        return rt.poses.all()

    @router.post("/robot/poses/{name}")
    def teach(name: str):
        try:
            return {"name": name, "joints": rt.poses.teach(name, rt.robot)}
        except PoseError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/robot/goto/{name}")
    def goto(name: str):
        idle_only()
        if refusal := torque_off_refusal():
            return refusal
        pose = rt.poses.get(name)
        if pose is None:
            raise HTTPException(404, f"pose '{name}' is not taught")
        move_to(rt.robot, pose, threading.Event(), MotionConfig(ex.cfg.hz, ex.cfg.max_speed))
        return {"name": name}

    @router.get("/robot/calibration")
    def calibration():
        cal = rt.calibration
        return {"fitted": cal.fitted, "n": len(cal.points), "image_size": cal.image_size, "points": cal.points}

    @router.post("/robot/calibration/points")
    def add_point(body: PointBody):
        x, y = body.x, body.y
        if x is None or y is None:
            try:
                x, y, _ = rt.kin.tool_xyz(rt.robot.read_joints())
            except IKError as exc:  # pragma: no cover - FK does not fail on valid joints
                raise HTTPException(422, str(exc)) from exc
        try:
            rt.calibration.add_point(body.u, body.v, x, y, body.image_size)
        except CalibrationError as exc:
            raise HTTPException(422, str(exc)) from exc
        rt.calibration.save(rt.calibration_path)
        return {"n": len(rt.calibration.points), "x": x, "y": y}

    @router.delete("/robot/calibration/points")
    def clear_points():
        rt.calibration.clear()
        rt.calibration.save(rt.calibration_path)
        return {"n": 0}

    @router.post("/robot/calibration/fit")
    def fit():
        try:
            stats = rt.calibration.fit()
        except CalibrationError as exc:
            raise HTTPException(422, str(exc)) from exc
        rt.calibration.save(rt.calibration_path)
        return stats

    @router.post("/plan", status_code=202)
    def plan(body: PlanBody):
        if refusal := torque_off_refusal():
            return refusal
        try:
            plan_id = ex.start([c.model_dump() for c in body.cells], body.image_size, body.mode, body.drop_z)
        except PlanError as exc:
            return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)
        return {"plan_id": plan_id, "cells": len(body.cells)}

    @router.post("/stop")
    def stop():
        return {"stopped": ex.stop()}

    @router.post("/robot/torque-on")
    def torque_on():
        idle_only()
        rt.robot.torque_on()
        return {"torque": True}

    @router.post("/robot/torque-off")
    def torque_off():
        ex.stop()
        ex.join(2)
        rt.robot.torque_off()
        return {"torque": False}

    @router.websocket("/robot/progress")
    async def progress(ws: WebSocket):
        await ws.accept()
        # a client joining mid-plan replays it from the start; otherwise it only sees new plans
        sent = ex.plan_start_index if ex.running else len(ex.events)
        try:
            while True:
                while sent < len(ex.events):
                    await ws.send_json(ex.events[sent])
                    sent += 1
                try:
                    await asyncio.wait_for(ws.receive_text(), 0.05)  # raises on disconnect
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            return

    return router
