import pytest

from smartseed_robot.kinematics import Kinematics


@pytest.fixture(scope="session")
def kin():
    return Kinematics()
