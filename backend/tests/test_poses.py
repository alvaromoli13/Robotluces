import pytest

from smartseed_robot.poses import PoseError, PoseStore, REQUIRED_POSES
from smartseed_robot.robot import FakeRobot


def test_teach_stores_current_joints_and_persists(tmp_path):
    path = tmp_path / "poses.json"
    robot = FakeRobot(initial={"shoulder_pan": 7.0})
    store = PoseStore(path)
    saved = store.teach("home", robot)
    assert saved["shoulder_pan"] == 7.0
    assert PoseStore(path).get("home") == saved


def test_missing_lists_required_poses_not_taught(tmp_path):
    store = PoseStore(tmp_path / "poses.json")
    store.teach("home", FakeRobot())
    assert "home" not in store.missing(["red"])
    assert store.missing(["red", "green"]) == ["above_box_red", "above_box_green"]
    assert set(REQUIRED_POSES) >= {"home", "above_box_purple"}


@pytest.mark.parametrize("name", ["", "nowhere", "above_box_blue", "grasp_", "../x"])
def test_unknown_names_are_rejected(tmp_path, name):
    with pytest.raises(PoseError):
        PoseStore(tmp_path / "poses.json").teach(name, FakeRobot())


def test_grasp_poses_are_allowed_and_optional(tmp_path):
    store = PoseStore(tmp_path / "poses.json")
    store.teach("grasp_red", FakeRobot())
    assert store.get("grasp_red") is not None and store.get("grasp_green") is None
    assert "grasp_red" not in store.missing(["red"])


def test_corrupt_file_is_an_error_not_a_silent_reset(tmp_path):
    path = tmp_path / "poses.json"
    path.write_text("{not json")
    with pytest.raises(PoseError):
        PoseStore(path)
