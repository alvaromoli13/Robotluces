import numpy as np
import pytest

from smartseed_robot.kinematics import PAN_AXIS_X, IKError, pose_above, pose_pitched
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


def pitch_of(kin, joints):
    """Angle between the approach axis and straight down, degrees."""
    axis = kin.tool_pose(joints)[:3, 2]
    return float(np.degrees(np.arccos(np.clip(-axis[2], -1.0, 1.0))))


def test_pose_pitched_zero_is_pose_above_and_ninety_is_horizontal_outwards():
    assert pose_pitched(0.2, 0.2, 0.1, 0.0) == pytest.approx(pose_above(0.2, 0.2, 0.1))
    flat = pose_pitched(0.3, 0.0, 0.1, 90.0)
    assert flat[:3, 2] == pytest.approx([1, 0, 0], abs=1e-9)
    assert np.linalg.det(flat[:3, :3]) == pytest.approx(1.0)
    tilted = pose_pitched(PAN_AXIS_X, 0.3, 0.1, 30.0)  # outwards = along +y from the pan axis
    assert tilted[:3, 2] == pytest.approx([0, np.sin(np.radians(30)), -np.cos(np.radians(30))])
    assert tilted[:3, 3] == pytest.approx([PAN_AXIS_X, 0.3, 0.1])


def test_a_near_target_keeps_the_gripper_straight_down(kin):
    joints, pitch = kin.solve_with_pitch(0.25, 0.0, 0.06, seed=SEED)
    assert pitch == 0.0 and pitch_of(kin, joints) < 10.0


@pytest.mark.parametrize("xyz", [(0.35, 0.0, 0.06), (0.44, 0.0, 0.06), (0.40, 0.05, 0.10)])
def test_a_far_target_tilts_the_gripper_outwards_only_as_much_as_needed(kin, xyz):
    joints, pitch = kin.solve_with_pitch(*xyz, seed=FOLDED)
    assert 0.0 < pitch < 90.0
    assert kin.tool_xyz(joints) == pytest.approx(xyz, abs=0.003)
    assert pitch_of(kin, joints) == pytest.approx(pitch, abs=10.0)  # the approach axis really follows the pitch
    assert kin.tool_pose(joints)[:3, 2][:2] @ (np.array(xyz[:2]) - [PAN_AXIS_X, 0.0]) > 0  # away from the arm


def test_the_further_the_target_the_more_the_gripper_tilts(kin):
    pitches = [kin.solve_with_pitch(x, 0.0, 0.06, seed=FOLDED)[1] for x in (0.25, 0.30, 0.35, 0.40, 0.44)]
    assert pitches == sorted(pitches) and pitches[0] == 0.0 and pitches[-1] > pitches[1]


def test_an_unreachable_target_raises_and_does_not_poison_the_next_solve(kin):
    with pytest.raises(IKError):
        kin.solve(0.9, 0.0, 0.1, seed=SEED)
    assert kin.solve_with_pitch(0.25, 0.0, 0.06, seed=SEED)[1] == 0.0


def test_position_only_fallback_when_no_pitch_is_tried(kin):
    joints, pitch = kin.solve_with_pitch(0.35, 0.0, 0.06, seed=FOLDED, pitches=())
    assert pitch is None and kin.tool_xyz(joints) == pytest.approx((0.35, 0.0, 0.06), abs=0.003)


def test_solve_with_no_pitch_and_no_reach_still_raises(kin):
    with pytest.raises(IKError):
        kin.solve_with_pitch(0.9, 0.0, 0.1, seed=SEED, pitches=())


def test_spin_turns_the_pose_about_the_approach_axis_and_defaults_to_none():
    base = pose_pitched(0.2, 0.1, 0.05, 0.0)
    assert pose_pitched(0.2, 0.1, 0.05, 0.0, 0.0) == pytest.approx(base)
    spun = pose_pitched(0.2, 0.1, 0.05, 0.0, 90.0)
    assert spun[:3, 2] == pytest.approx(base[:3, 2])  # approach axis unchanged
    assert spun[:3, 0] == pytest.approx(base[:3, 1])  # x now where y was
    assert spun[:3, 3] == pytest.approx(base[:3, 3])


def test_solve_with_spin_reaches_the_same_point_with_a_different_wrist_roll(kin):
    plain = kin.solve(*XYZ_FOR_SPIN, seed=SEED)
    spun = kin.solve(*XYZ_FOR_SPIN, seed=SEED, spin_deg=40.0)
    assert kin.tool_xyz(spun) == pytest.approx(XYZ_FOR_SPIN, abs=0.003)
    assert abs(spun["wrist_roll"] - plain["wrist_roll"]) > 20.0


XYZ_FOR_SPIN = (0.25, 0.0, 0.06)
