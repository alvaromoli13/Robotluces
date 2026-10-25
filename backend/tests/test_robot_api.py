import threading
import time

import pytest
from fastapi.testclient import TestClient

from smartseed_robot.api import build_runtime
from smartseed_robot.executor import ExecutorConfig
from smartseed_robot.robot import FakeRobot
from smartseed_vision.app import create_app

SIZE = [640, 480]
FAST = ExecutorConfig(hz=1000, max_speed=10_000, settle_s=0.0)
SEED = {"shoulder_pan": 0.0, "shoulder_lift": -30.0, "elbow_flex": 60.0, "wrist_flex": 30.0, "wrist_roll": 0.0,
        "gripper": 60.0}


def cells(n, color="red"):
    return [{"cell_index": i, "row": 0, "col": i, "color": color, "u": 200.0 + 40 * i, "v": 240.0} for i in range(n)]


def make_client(tmp_path, kin, robot=None, config=FAST):
    runtime = build_runtime(mode="fake", data_dir=tmp_path, robot=robot or FakeRobot(initial=SEED), kin=kin,
                            config=config)
    return TestClient(create_app(detector=None, depth=None, robot=runtime)), runtime


def teach_all(client, colors=("red", "yellow", "green", "purple")):
    client.post("/robot/poses/home")
    for i, color in enumerate(colors):
        client.app.state.robot_runtime.robot.send_joints({"shoulder_pan": 40.0 + 10 * i})
        assert client.post(f"/robot/poses/above_box_{color}").status_code == 200
    client.app.state.robot_runtime.robot.send_joints(SEED)


def calibrate(client):
    for u, v in [(50, 60), (590, 70), (600, 420), (40, 430)]:
        r = client.post("/robot/calibration/points",
                        json={"u": u, "v": v, "image_size": SIZE, "x": 0.15 + u * 0.00012, "y": (v - 240) * 0.0004})
        assert r.status_code == 200
    r = client.post("/robot/calibration/fit")
    assert r.status_code == 200 and r.json()["max_error_mm"] < 0.5


def wait_idle(client, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if client.get("/robot/status").json()["state"] != "running":
            return
        time.sleep(0.02)
    raise AssertionError("plan did not finish")


@pytest.fixture
def client(tmp_path, kin):
    return make_client(tmp_path, kin)[0]


def test_status_contract_when_idle(client):
    assert client.get("/robot/status").json() == {
        "state": "idle", "robot": "fake", "plan_id": None, "current_cell": None, "done": [], "failed": [],
        "calibrated": False, "poses": [], "policies": [], "torque": True, "cameras": True}


def test_joints_endpoint_returns_joints_and_tool_position(client):
    body = client.get("/robot/joints").json()
    assert body["joints"]["gripper"] == 60.0 and set(body["tool"]) == {"x", "y", "z"}


def test_teach_pose_validates_name_and_lists_taught(client):
    assert client.post("/robot/poses/home").json()["joints"]["shoulder_lift"] == -30.0
    assert client.post("/robot/poses/nowhere").status_code == 422
    assert client.get("/robot/status").json()["poses"] == ["home"]


def test_calibration_points_default_to_current_tool_position(client):
    body = client.post("/robot/calibration/points", json={"u": 10, "v": 20, "image_size": SIZE}).json()
    assert body["n"] == 1 and {"x", "y"} <= set(body)
    assert client.post("/robot/calibration/fit").status_code == 422  # fewer than 4 points


def test_calibration_persists_across_restarts(tmp_path, kin):
    client, _ = make_client(tmp_path, kin)
    calibrate(client)
    again, _ = make_client(tmp_path, kin)
    assert again.get("/robot/status").json()["calibrated"] is True


def test_plan_without_calibration_or_poses_is_a_409_with_code(client):
    r = client.post("/plan", json={"image_size": SIZE, "cells": cells(1)})
    assert r.status_code == 409 and r.json()["code"] == "no_calibration" and r.json()["detail"]
    calibrate(client)
    r = client.post("/plan", json={"image_size": SIZE, "cells": cells(1)})
    assert r.status_code == 409 and r.json()["code"] == "missing_pose" and "home" in r.json()["detail"]


def test_unknown_colour_is_a_409_missing_pose(client):
    teach_all(client)
    calibrate(client)
    r = client.post("/plan", json={"image_size": SIZE, "cells": cells(1, "blue")})
    assert r.status_code == 409 and r.json()["code"] == "missing_pose" and "above_box_blue" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"image_size": SIZE, "cells": []},
    {"image_size": SIZE, "cells": [{**cells(1)[0], "color": "Blue"}]},
    {"image_size": SIZE, "cells": [{**cells(1)[0], "color": "1red"}]},
    {"image_size": SIZE, "cells": [{**cells(1)[0], "color": "a" * 21}]},
    {"image_size": SIZE, "cells": [{**cells(1)[0], "color": ""}]},
    {"image_size": SIZE, "cells": [{"cell_index": 0}]},
    {"cells": cells(1)},
])
def test_invalid_plan_bodies_are_422(client, body):
    assert client.post("/plan", json=body).status_code == 422


def test_plan_runs_and_progress_streams_contract_events(client):
    teach_all(client)
    calibrate(client)
    with client.websocket_connect("/robot/progress") as ws:
        r = client.post("/plan", json={"image_size": SIZE, "cells": cells(3)})
        assert r.status_code == 202
        body = r.json()
        assert body["cells"] == 3 and isinstance(body["plan_id"], str)
        events = []
        while not events or events[-1]["type"] != "finished":
            events.append(ws.receive_json())
    assert [e["type"] for e in events] == ["plan_started", "cell_started", "drop_pose", "cell_done"] + [
        "cell_started", "drop_pose", "cell_done", "cell_started", "drop_pose", "cell_done", "finished"]
    assert all(set(e) >= {"type", "plan_id", "cell_index", "message"} and e["plan_id"] == body["plan_id"]
               for e in events)
    assert [e["cell_index"] for e in events if e["type"] == "cell_done"] == [0, 1, 2]
    wait_idle(client)
    status = client.get("/robot/status").json()
    assert status["state"] == "idle" and status["done"] == [0, 1, 2] and status["failed"] == []
    assert status["plan_id"] == body["plan_id"] and status["calibrated"] is True
    assert {"home", "above_box_red"} <= set(status["poses"])


def test_second_plan_while_running_is_busy_and_stop_halts_it(tmp_path, kin):
    gate = threading.Event()

    class Gated(FakeRobot):
        def send_joints(self, target):
            super().send_joints(target)
            if len(self.commands) > 3:
                gate.wait(5)

    client, runtime = make_client(tmp_path, kin, robot=Gated(initial=SEED))
    teach_all(client)
    calibrate(client)
    assert client.post("/plan", json={"image_size": SIZE, "cells": cells(3)}).status_code == 202
    busy = client.post("/plan", json={"image_size": SIZE, "cells": cells(1)})
    assert busy.status_code == 409 and busy.json()["code"] == "busy"
    assert client.post("/stop").json() == {"stopped": True}
    assert client.get("/robot/status").json()["state"] == "stopping"
    gate.set()
    runtime.executor.join(10)
    assert runtime.executor.events[-1]["type"] == "stopped"
    assert client.get("/robot/status").json()["state"] == "idle"
    assert runtime.robot.torque_enabled


def test_stop_when_idle_reports_false(client):
    assert client.post("/stop").json() == {"stopped": False}


def test_torque_off_is_a_separate_explicit_endpoint(tmp_path, kin):
    client, runtime = make_client(tmp_path, kin)
    assert client.post("/robot/torque-off").status_code == 200
    assert not runtime.robot.torque_enabled


def test_goto_moves_to_a_taught_pose_and_404s_on_untaught(client):
    teach_all(client)
    assert client.post("/robot/goto/home").status_code == 200
    assert client.post("/robot/goto/grasp_red").status_code == 404


def test_robot_endpoints_share_cors_and_private_network_headers(client):
    r = client.options("/plan", headers={"Origin": "https://x.github.io", "Access-Control-Request-Method": "POST",
                                        "Access-Control-Request-Private-Network": "true"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["access-control-allow-private-network"] == "true"


def test_default_app_never_opens_hardware(monkeypatch, tmp_path):
    monkeypatch.delenv("SMARTSEED_ROBOT", raising=False)
    monkeypatch.setenv("SMARTSEED_DATA_DIR", str(tmp_path))
    client = TestClient(create_app(detector=None, depth=None))
    assert client.get("/robot/status").json()["robot"] == "fake"


def test_real_mode_without_port_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="SMARTSEED_ROBOT_PORT"):
        build_runtime(mode="real", port=None, data_dir=tmp_path)


def test_torque_on_endpoint_and_motion_refused_while_torque_is_off(tmp_path, kin):
    client, runtime = make_client(tmp_path, kin)
    client.post("/robot/poses/home")
    client.post("/robot/torque-off")
    assert client.get("/robot/status").json()["torque"] is False
    refused = client.post("/robot/goto/home")
    assert refused.status_code == 409 and refused.json()["code"] == "torque_off"
    teach_all(client)
    calibrate(client)
    plan = client.post("/plan", json={"image_size": SIZE, "cells": cells(1)})
    assert plan.status_code == 409 and plan.json()["code"] == "torque_off"
    assert client.post("/robot/torque-on").json() == {"torque": True}
    assert client.get("/robot/status").json()["torque"] is True
    assert client.post("/robot/goto/home").status_code == 200


def test_act_start_can_be_taught_and_policies_are_listed_in_status(tmp_path, kin):
    from smartseed_robot.act import ActConfig

    runtime = build_runtime(mode="fake", data_dir=tmp_path, robot=FakeRobot(initial=SEED), kin=kin, config=FAST,
                            act=ActConfig(policies={"red": "fake/red"}), policy_factory=lambda spec: None)
    client = TestClient(create_app(detector=None, depth=None, robot=runtime))
    assert client.post("/robot/poses/act_start").status_code == 200
    status = client.get("/robot/status").json()
    assert status["policies"] == ["red"] and "act_start" in status["poses"]


def test_real_mode_opens_cameras_only_when_policies_are_configured(tmp_path, monkeypatch):
    from smartseed_robot import robot as robot_module
    from smartseed_robot.act import ActConfig

    made = []

    class Recorder(FakeRobot):
        def __init__(self, port, cameras=None):
            super().__init__()
            made.append((port, cameras))

    monkeypatch.setattr(robot_module, "LeRobotFollower", Recorder)
    build_runtime(mode="real", port="/dev/x", data_dir=tmp_path, act=ActConfig())
    build_runtime(mode="real", port="/dev/x", data_dir=tmp_path,
                  act=ActConfig(policies={"red": "r"}, cam_top=2, cam_wrist="/dev/video4"))
    assert made[0] == ("/dev/x", None)
    assert made[1] == ("/dev/x", {"top": 2, "wrist": "/dev/video4"})


def test_env_configures_policies_in_fake_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTSEED_ACT_POLICIES", '{"purple": "user/act-purple"}')
    runtime = build_runtime(mode="fake", data_dir=tmp_path)
    assert runtime.executor.status()["policies"] == ["purple"]


def test_plan_mode_and_drop_z_reach_the_executor(tmp_path, kin):
    client, runtime = make_client(tmp_path, kin)
    calibrate(client)
    with client.websocket_connect("/robot/progress") as ws:
        r = client.post("/plan", json={"image_size": SIZE, "cells": cells(1, "blue"), "mode": "place", "drop_z": 0.1})
        assert r.status_code == 202
        first = ws.receive_json()
    assert first["type"] == "plan_started" and first["mode"] == "place"
    wait_idle(client)
    assert client.get("/robot/status").json()["done"] == [0]


def test_plan_mode_defaults_to_full(client):
    teach_all(client)
    calibrate(client)
    assert client.post("/plan", json={"image_size": SIZE, "cells": cells(1)}).status_code == 202
    wait_idle(client)
    assert client.app.state.robot_runtime.executor.events[0]["mode"] == "full"


@pytest.mark.parametrize("extra", [{"mode": "dance"}, {"drop_z": 0.01}, {"drop_z": 0.3}])
def test_invalid_mode_or_drop_z_is_422(client, extra):
    assert client.post("/plan", json={"image_size": SIZE, "cells": cells(1), **extra}).status_code == 422


def test_grasp_mode_without_policy_is_a_409_with_code(client):
    r = client.post("/plan", json={"image_size": SIZE, "cells": cells(1), "mode": "grasp"})
    assert r.status_code == 409 and r.json()["code"] == "missing_pose"


HUB = {"RafaelJaime/act-smartseed-d1-c100": ["model.safetensors", "checkpoints/010000/pretrained_model/model.safetensors",
                                              "checkpoints/020000/pretrained_model/model.safetensors"]}


class StubHub:
    def __init__(self, repos=HUB):
        self.repos, self.down = repos, False

    def list_models(self, **kwargs):
        if self.down:
            raise OSError("offline")
        return [type("M", (), {"id": r}) for r in self.repos]

    def model_info(self, repo, **kwargs):
        return type("I", (), {"siblings": [type("S", (), {"rfilename": n}) for n in self.repos[repo]]})


def act_client(tmp_path, kin, hub=None, loaded=None):
    from smartseed_robot.act import ActConfig
    from smartseed_robot.catalog import ModelCatalog

    runtime = build_runtime(
        mode="fake", data_dir=tmp_path, robot=FakeRobot(initial=SEED), kin=kin, config=FAST,
        act=ActConfig(policies={"red": "env/red", "green": "env/green"}),
        policy_factory=lambda spec: loaded.append(spec) if loaded is not None else None,
        catalog=ModelCatalog(api=hub or StubHub()),
        spec_resolver=lambda repo, ckpt: repo if ckpt is None else f"/cache/{repo}/{ckpt}")
    return TestClient(create_app(detector=None, depth=None, robot=runtime)), runtime


def test_act_models_lists_hub_models_defaults_and_the_active_policy(tmp_path, kin):
    client, _ = act_client(tmp_path, kin)
    body = client.get("/robot/act/models").json()
    assert body["enabled"] is True and body["offline"] is False
    assert {"repo": "RafaelJaime/act-smartseed-d1-c100", "name": "act-smartseed-d1-c100",
            "checkpoints": ["010000", "020000"]} in body["models"]
    assert {"repo": "env/red", "name": "red", "checkpoints": []} in body["models"]  # env defaults stay selectable
    assert body["active"]["red"] == {"repo": "env/red", "checkpoint": None, "default": True}


def test_act_models_offline_still_lists_the_defaults(tmp_path, kin):
    hub = StubHub()
    hub.down = True
    body = act_client(tmp_path, kin, hub)[0].get("/robot/act/models").json()
    assert body["offline"] is True and [m["repo"] for m in body["models"]] == ["env/green", "env/red"]


def test_act_models_when_act_is_not_configured(client):
    assert client.get("/robot/act/models").json() == {"enabled": False, "offline": False, "models": [], "active": {}}
    refused = client.post("/robot/act/select", json={"color": "red", "repo": "x"})
    assert refused.status_code == 409 and refused.json()["code"] == "act_disabled"


def test_act_select_switches_the_colour_and_the_next_run_uses_it(tmp_path, kin):
    loaded = []
    client, runtime = act_client(tmp_path, kin, loaded=loaded)
    r = client.post("/robot/act/select", json={"color": "red", "repo": "RafaelJaime/act-smartseed-d1-c100",
                                               "checkpoint": "020000"})
    assert r.status_code == 200
    assert r.json()["active"]["red"] == {"repo": "RafaelJaime/act-smartseed-d1-c100", "checkpoint": "020000",
                                         "default": False}
    assert client.get("/robot/act/models").json()["active"]["red"]["checkpoint"] == "020000"
    runtime.executor.act.policy("red")
    assert loaded == ["/cache/RafaelJaime/act-smartseed-d1-c100/020000"]


def test_act_select_final_checkpoint_is_null(tmp_path, kin):
    client, _ = act_client(tmp_path, kin)
    r = client.post("/robot/act/select", json={"color": "green", "repo": "RafaelJaime/act-smartseed-d1-c100"})
    assert r.status_code == 200 and r.json()["active"]["green"]["checkpoint"] is None


@pytest.mark.parametrize("body, status", [
    ({"color": "blue", "repo": "env/red"}, 404),  # no policy for that colour
    ({"color": "red", "repo": "someone/else"}, 422),  # not in the catalog nor an env default
    ({"color": "red", "repo": "RafaelJaime/act-smartseed-d1-c100", "checkpoint": "999999"}, 422),
    ({"color": "red", "repo": "env/green", "checkpoint": "010000"}, 422)])
def test_act_select_validates_the_choice(tmp_path, kin, body, status):
    client, _ = act_client(tmp_path, kin)
    assert client.post("/robot/act/select", json=body).status_code == status
    assert client.get("/robot/act/models").json()["active"]["red"]["default"] is True


def test_act_select_is_refused_while_a_plan_runs(tmp_path, kin):
    client, runtime = act_client(tmp_path, kin)
    runtime.executor._state = "running"
    r = client.post("/robot/act/select", json={"color": "red", "repo": "env/green"})
    assert r.status_code == 409 and r.json()["code"] == "busy" and "running" in r.json()["detail"]
    assert client.get("/robot/act/models").json()["active"]["red"]["repo"] == "env/red"


def test_act_select_reports_a_failed_download(tmp_path, kin):
    from smartseed_robot.act import ActConfig
    from smartseed_robot.catalog import ModelCatalog

    def resolver(repo, ckpt):
        raise OSError("no space left")

    runtime = build_runtime(mode="fake", data_dir=tmp_path, robot=FakeRobot(initial=SEED), kin=kin, config=FAST,
                            act=ActConfig(policies={"red": "env/red"}), policy_factory=lambda spec: None,
                            catalog=ModelCatalog(api=StubHub()), spec_resolver=resolver)
    client = TestClient(create_app(detector=None, depth=None, robot=runtime))
    r = client.post("/robot/act/select", json={"color": "red", "repo": "RafaelJaime/act-smartseed-d1-c100",
                                                "checkpoint": "010000"})
    assert r.status_code == 502 and r.json()["code"] == "download_failed" and "no space left" in r.json()["detail"]
