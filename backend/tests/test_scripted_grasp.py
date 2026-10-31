import math

import pytest

from smartseed_robot import scripted_grasp
from smartseed_robot.kinematics import PAN_AXIS_X

RADIUS = 0.007


def radial(seed):
    return math.atan2(seed[1], seed[0] - PAN_AXIS_X)


def test_the_radial_jaw_axis_comes_first_with_no_wrist_roll_when_nothing_is_near():
    seed = (0.25, 0.05)
    spin, tool_xy = scripted_grasp.jaw_axes(seed, [], RADIUS)[0]
    assert spin == pytest.approx(0.0, abs=1e-6)
    reach = scripted_grasp.FACE_GAP + RADIUS  # the seed sits one radius (plus the gap) beyond the tool, along the axis
    assert tool_xy == pytest.approx((seed[0] - reach * math.cos(radial(seed)), seed[1] - reach * math.sin(radial(seed))))


def test_a_neighbour_in_the_open_jaw_footprint_turns_the_wrist():
    seed = (0.25, 0.0)
    neighbour = (seed[0] + 0.03, seed[1])  # straight ahead along the radial axis, inside the footprint
    spin, tool_xy = scripted_grasp.jaw_axes(seed, [neighbour], RADIUS)[0]
    assert abs(spin) >= 30.0
    # and the chosen axis (the direction from the tool to the seed) really is clear of it
    phi = math.atan2(seed[1] - tool_xy[1], seed[0] - tool_xy[0])
    assert scripted_grasp.clearance(seed, phi, [neighbour]) > 0


def test_a_far_neighbour_does_not_change_the_choice():
    seed = (0.25, 0.0)
    assert scripted_grasp.jaw_axes(seed, [(0.25, 0.08)], RADIUS)[0][0] == pytest.approx(0.0, abs=1e-6)


def test_every_axis_is_listed_best_first_even_when_all_are_crowded():
    seed = (0.25, 0.0)
    crowd = [(seed[0] + 0.012 * math.cos(a), seed[1] + 0.012 * math.sin(a)) for a in (0, 1.5, 3.0, 4.5)]
    axes = scripted_grasp.jaw_axes(seed, crowd, RADIUS)
    assert len(axes) == 12 and len({round(s, 3) for s, _ in axes}) == 12
