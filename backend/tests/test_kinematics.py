import numpy as np
import pytest

from smartseed_robot.kinematics import IKError, pose_above
from smartseed_robot.robot import ARM_JOINTS

SEED = {"shoulder_pan": 0.0, "shoulder_lift": -30.0, "elbow_flex": 60.0, "wrist_flex": 30.0, "wrist_roll": 0.0}
# a straight-down approach limits the SO-101 reach to roughly 0.28 m at table height
REACHABLE = [(0.25, 0.0, 0.06), (0.22, 0.10, 0.06), (0.24, -0.08, 0.08), (0.20, -0.12, 0.06)]


def test_fk_matches_urdf_neutral_pose(kin):
    x, y, z = kin.tool_xyz(dict.fromkeys(ARM_JOINTS, 0.0))
    assert (x, y, z) == pytest.approx((0.391, 0.0, 0.226), abs=0.002)


def test_pose_above_points_gripper_down_and_yaws_towards_target():
    pose = pose_above(0.2, 0.2, 0.1)
    assert pose[:3, 3] == pytest.approx([0.2, 0.2, 0.1])
    assert pose[:3, 2] == pytest.approx([0, 0, -1])
    assert np.linalg.det(pose[:3, :3]) == pytest.approx(1.0)


@pytest.mark.parametrize("xyz", REACHABLE)
def test_ik_hits_target_within_a_few_mm_pointing_down(kin, xyz):
    joints = kin.solve(*xyz, seed=SEED)
    assert set(joints) == set(ARM_JOINTS)
    assert kin.tool_xyz(joints) == pytest.approx(xyz, abs=0.003)
    assert kin.tool_pose(joints)[:3, 2][2] < -0.9


@pytest.mark.parametrize("xyz", REACHABLE)
def test_fk_ik_round_trip(kin, xyz):
    solved = kin.solve(*xyz, seed=SEED)
    again = kin.solve(*kin.tool_xyz(solved), seed=solved)
    assert kin.tool_xyz(again) == pytest.approx(xyz, abs=0.003)


FOLDED = {"shoulder_pan": 7.4, "shoulder_lift": -102.9, "elbow_flex": 97.1, "wrist_flex": -101.1, "wrist_roll": -0.4}


@pytest.mark.parametrize("xyz", [(0.30, 0.0, 0.06), (0.38, -0.05, 0.06)])
def test_ik_tilts_the_gripper_for_cells_beyond_the_straight_down_reach(kin, xyz):
    # the taught home is folded; real tray cells sit 0.3-0.45 m out, where pointing down is impossible
    joints = kin.solve(*xyz, seed=FOLDED)
    assert kin.tool_xyz(joints) == pytest.approx(xyz, abs=0.003)


def test_unreachable_target_raises(kin):
    with pytest.raises(IKError):
        kin.solve(0.9, 0.0, 0.1, seed=SEED)
