import threading

import numpy as np
import pytest

from smartseed_robot.act import ACT_START_FALLBACK, ActConfig, ActGrasp, apply_inference_overrides
from smartseed_robot.robot import JOINTS, CameraUnavailable, FakeRobot


class FakePolicy:
    def __init__(self):
        self.resets, self.observations = 0, []

    def reset(self):
        self.resets += 1

    def step(self, observation):
        self.observations.append(observation)
        return {**dict.fromkeys(JOINTS, 1.0), "wrist_roll": 77.0}


def test_env_defaults_have_no_policies():
    cfg = ActConfig.from_env({})
    assert cfg.policies == {} and not cfg.enabled
    assert cfg.duration_s == 10.0 and cfg.cam_top == 0 and cfg.cam_wrist == 1


def test_env_parses_policies_duration_and_cameras():
    cfg = ActConfig.from_env({
        "SMARTSEED_ACT_POLICIES": '{"red": "user/act-red", "green": "/models/green"}',
        "SMARTSEED_ACT_DURATION_S": "7.5", "SMARTSEED_CAM_TOP": "2", "SMARTSEED_CAM_WRIST": "/dev/video4",
        "SMARTSEED_POLICY_DEVICE": "cpu"})
    assert cfg.policies == {"red": "user/act-red", "green": "/models/green"} and cfg.enabled
    assert cfg.duration_s == 7.5 and cfg.cam_top == 2 and cfg.cam_wrist == "/dev/video4"
    assert cfg.device == "cpu"


@pytest.mark.parametrize("raw", ["not json", '["red"]', '{"Red!": "x"}', '{"red": 3}', '{"red": ""}'])
def test_env_rejects_malformed_policies(raw):
    with pytest.raises(ValueError, match="SMARTSEED_ACT_POLICIES"):
        ActConfig.from_env({"SMARTSEED_ACT_POLICIES": raw})


def test_fallback_start_pose_is_the_mean_episode_start():
    assert list(ACT_START_FALLBACK) == list(JOINTS)
    assert ACT_START_FALLBACK["shoulder_lift"] == -102.7 and ACT_START_FALLBACK["gripper"] == 6.3


def test_fake_robot_observation_has_the_policy_frame():
    robot = FakeRobot(initial={"shoulder_pan": 3.0})
    obs = robot.read_observation()
    assert obs["observation.state"].shape == (6,) and obs["observation.state"][0] == 3.0
    assert obs["observation.state"].dtype == np.float32
    for cam in ("top", "wrist"):
        assert obs[f"observation.images.{cam}"].shape == (480, 640, 3)


def test_policies_load_lazily_once_and_are_cached():
    loaded = []

    def factory(spec):
        loaded.append(spec)
        return FakePolicy()

    act = ActGrasp(ActConfig(policies={"red": "repo/red", "green": "repo/green"}), factory)
    assert loaded == [] and act.colors == ["green", "red"] and act.has("red") and not act.has("blue")
    robot, stop = FakeRobot(), threading.Event()
    act.run("red", robot, stop, hz=1000, duration_s=0.005)
    act.run("red", robot, stop, hz=1000, duration_s=0.005)
    assert loaded == ["repo/red"]


def test_run_resets_the_policy_and_sends_one_action_per_step():
    policy = FakePolicy()
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.01), lambda spec: policy)
    robot = FakeRobot()
    assert act.run("red", robot, threading.Event(), hz=1000) is True
    assert policy.resets == 1 and len(policy.observations) == 10 and len(robot.commands) == 10
    assert robot.commands[0]["wrist_roll"] == 77.0 and set(robot.commands[0]) == set(JOINTS)
    assert "observation.images.top" in policy.observations[0]


def test_run_stops_within_one_step():
    stop, robot = threading.Event(), None

    class Stopping(FakeRobot):
        def send_joints(self, target):
            super().send_joints(target)
            if len(self.commands) == 4:
                stop.set()

    robot = Stopping()
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=1.0), lambda spec: FakePolicy())
    assert act.run("red", robot, stop, hz=1000) is False
    assert len(robot.commands) == 4


def test_a_late_step_does_not_burst_the_next_ones():
    """After a slow inference the loop resumes the period from now instead of firing the backlog at once."""
    import time

    class SlowOnce(FakePolicy):
        def step(self, observation):
            if len(self.observations) == 2:
                time.sleep(0.08)
            return super().step(observation)

    sent = []

    class Timed(FakeRobot):
        def send_joints(self, target):
            sent.append(time.monotonic())
            super().send_joints(target)

    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.1), lambda spec: SlowOnce())
    act.run("red", Timed(), threading.Event(), hz=100)
    gaps = np.diff(sent[2:6])
    assert gaps.min() > 0.007


def test_run_writes_timing_and_first_frames_to_the_debug_dir(tmp_path):
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.02, debug_dir=tmp_path), lambda spec: FakePolicy())
    act.run("red", FakeRobot(), threading.Event(), hz=1000)
    log = (tmp_path / "act_timing.log").read_text()
    assert "red" in log and "steps=20" in log and "late=" in log and "max_ms=" in log
    assert (tmp_path / "act_red_top.png").exists() and (tmp_path / "act_red_wrist.png").exists()


def test_select_swaps_the_policy_of_one_colour_and_reports_it_active():
    loaded = []

    def factory(spec):
        loaded.append(spec)
        return FakePolicy()

    resolved = []

    def resolver(repo, checkpoint):
        resolved.append((repo, checkpoint))
        return repo if checkpoint is None else f"/cache/{repo}/{checkpoint}"

    act = ActGrasp(ActConfig(policies={"red": "env/red", "green": "env/green"}), factory, resolver)
    assert act.active() == {"red": {"repo": "env/red", "checkpoint": None, "default": True},
                            "green": {"repo": "env/green", "checkpoint": None, "default": True}}
    robot, stop = FakeRobot(), threading.Event()
    act.run("red", robot, stop, hz=1000, duration_s=0.005)
    act.select("red", "hub/new", "020000")
    assert resolved == [("hub/new", "020000")] and loaded == ["env/red"]  # nothing loads until the next run
    assert act.active()["red"] == {"repo": "hub/new", "checkpoint": "020000", "default": False}
    assert act.active()["green"]["default"] is True
    act.run("red", robot, stop, hz=1000, duration_s=0.005)
    act.run("red", robot, stop, hz=1000, duration_s=0.005)
    assert loaded == ["env/red", "/cache/hub/new/020000"]


def test_select_the_env_default_again_goes_back_to_default():
    act = ActGrasp(ActConfig(policies={"red": "env/red"}), lambda spec: FakePolicy(), lambda repo, ckpt: repo)
    act.select("red", "hub/new")
    act.select("red", "env/red")
    assert act.active()["red"] == {"repo": "env/red", "checkpoint": None, "default": True}


def test_select_rejects_a_colour_without_a_policy_and_keeps_the_state():
    act = ActGrasp(ActConfig(policies={"red": "env/red"}), lambda spec: FakePolicy(), lambda repo, ckpt: repo)
    with pytest.raises(KeyError):
        act.select("blue", "hub/new")
    assert act.colors == ["red"]


def test_a_failed_resolution_leaves_the_active_policy_untouched():
    def resolver(repo, checkpoint):
        raise OSError("no network")

    act = ActGrasp(ActConfig(policies={"red": "env/red"}), lambda spec: FakePolicy(), resolver)
    with pytest.raises(OSError):
        act.select("red", "hub/new", "010000")
    assert act.active()["red"]["repo"] == "env/red"


def test_dead_cameras_are_reopened_before_the_run():
    robot = FakeRobot()
    robot.drop_cameras()
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.01), lambda spec: FakePolicy())
    assert act.run("red", robot, threading.Event(), hz=1000) is True
    assert robot.reconnects == 1


def test_a_camera_dying_mid_run_is_reopened_and_the_step_retried():
    class Glitch(FakeRobot):
        reads = 0

        def read_observation(self):
            self.reads += 1
            if self.reads == 3:
                self.drop_cameras()
            return super().read_observation()

    robot = Glitch()
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.01), lambda spec: FakePolicy())
    assert act.run("red", robot, threading.Event(), hz=1000) is True
    assert robot.reconnects == 1


def test_a_failed_reconnect_aborts_the_run_with_camera_unavailable():
    robot = FakeRobot()
    robot.drop_cameras(reconnectable=False)
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.01), lambda spec: FakePolicy())
    with pytest.raises(CameraUnavailable):
        act.run("red", robot, threading.Event(), hz=1000)


def test_a_non_camera_failure_is_not_masked_by_a_reconnect():
    class BusDown(FakeRobot):
        def read_observation(self):
            raise OSError("bus down")

    robot = BusDown()
    act = ActGrasp(ActConfig(policies={"red": "x"}, duration_s=0.01), lambda spec: FakePolicy())
    with pytest.raises(OSError):
        act.run("red", robot, threading.Event(), hz=1000)
    assert robot.reconnects == 0


class _ActCfg:
    chunk_size, n_action_steps, temporal_ensemble_coeff = 100, 100, None


def test_inference_overrides_shorten_the_open_loop_chunk():
    cfg = apply_inference_overrides(_ActCfg(), n_action_steps=10)
    assert (cfg.n_action_steps, cfg.temporal_ensemble_coeff) == (10, None)


def test_temporal_ensembling_replans_every_step():
    cfg = apply_inference_overrides(_ActCfg(), temporal_ensemble_coeff=0.01)
    assert (cfg.n_action_steps, cfg.temporal_ensemble_coeff) == (1, 0.01)


def test_no_overrides_keep_the_trained_config():
    cfg = apply_inference_overrides(_ActCfg())
    assert (cfg.n_action_steps, cfg.temporal_ensemble_coeff) == (100, None)


@pytest.mark.parametrize("steps", [0, 101])
def test_n_action_steps_must_fit_the_chunk(steps):
    with pytest.raises(ValueError):
        apply_inference_overrides(_ActCfg(), n_action_steps=steps)


def test_ensembling_and_a_longer_chunk_are_exclusive():
    with pytest.raises(ValueError):
        apply_inference_overrides(_ActCfg(), n_action_steps=10, temporal_ensemble_coeff=0.01)
