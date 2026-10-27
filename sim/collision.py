"""Wall pass-through detector for the twin: how deep does any arm geom get into a box or tray wall?

Two modes, same report:

- `contact` (the v2 scene): reads MuJoCo's own contact list after every physics step. Every jaw geom collides with
  the walls there (see `sim/README.md`, "Collision model"), so a contact between an arm geom and a wall geom is a
  real contact; its `dist` is negative while the geoms interpenetrate, and `mj_contactForce` gives the normal force.
- `geometry` (the audit of the v1 scenes): asks `mj_geomDistance` for the signed distance of every arm geom to every
  wall geom, whatever the collision bits say. In v1 the moving-jaw hull and the pads did not collide with walls, so
  the contact list is empty there while the geometry overlaps.

An episode is valid only if the deepest penetration is at most `MAX_PENETRATION_M` and no wall contact pushed with
more than `MAX_FORCE_N`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_PENETRATION_M = 0.001
MAX_FORCE_N = 2.0
CULL_M = 0.03  # geometry mode: pairs whose bounding spheres are further apart than this are not measured


def is_wall(name: str) -> bool:
    """Box and tray walls and the tray dividers; never a floor, the mat, the paper or the table."""
    return "_wall_" in name or name.startswith(("tray_wall", "tray_div"))


def wall_geoms(model) -> list[int]:
    return [g for g in range(model.ngeom) if is_wall(model.geom(g).name or "")]


def arm_geoms(model) -> list[int]:
    """Collision geoms (group 3: hulls and pads) of every body below `base`."""
    base = model.body("base").id
    return [g for g in range(model.ngeom) if model.geom_group[g] == 3 and model.body_rootid[model.geom_bodyid[g]] == base]


def min_wall_distance(model, data, arm=None, walls=None, cull: float = CULL_M) -> float:
    """Signed distance (m) from the arm's collision geoms to the closest wall: negative when they overlap. Needs
    up-to-date kinematics (`mj_forward`, `mj_kinematics` or a step). `cull` caps the answer."""
    import mujoco

    arm = arm_geoms(model) if arm is None else arm
    walls = wall_geoms(model) if walls is None else walls
    fromto = np.zeros(6)
    best = cull
    ap, wp = data.geom_xpos[arm], data.geom_xpos[walls]
    reach = np.linalg.norm(ap[:, None, :] - wp[None, :, :], axis=2) - model.geom_rbound[arm][:, None] - model.geom_rbound[walls][None, :]
    for i, j in zip(*np.nonzero(reach < best)):
        best = min(best, mujoco.mj_geomDistance(model, data, arm[i], walls[j], best, fromto))
    return float(best)


@dataclass(frozen=True)
class WallReport:
    max_penetration_m: float
    max_force_n: float
    contact_steps: int  # physics steps (contact mode) or checks (geometry mode) with any arm-wall overlap
    contacts: int  # arm-wall contacts summed over those steps
    checks: int

    @property
    def valid(self) -> bool:
        return self.max_penetration_m <= MAX_PENETRATION_M and self.max_force_n <= MAX_FORCE_N

    def as_info(self) -> dict:
        return {"wall_max_penetration_mm": 1000 * self.max_penetration_m, "wall_max_force_n": self.max_force_n,
                "wall_contact_steps": self.contact_steps, "wall_contacts": self.contacts}


class WallMonitor:
    """Step hook: `robot.step_hook = WallMonitor(robot._model)`; read `report()` after the episode. In geometry mode
    only every `every`-th call measures (a distance query per arm/wall pair is not free)."""

    def __init__(self, model, mode: str = "contact", every: int = 10):
        if mode not in ("contact", "geometry"):
            raise ValueError(mode)
        self.mode, self.every = mode, max(1, every)
        arm, walls = arm_geoms(model), wall_geoms(model)
        self._arm, self._walls = arm, walls
        self._is_arm = np.zeros(model.ngeom, bool)
        self._is_arm[arm] = True
        self._is_wall = np.zeros(model.ngeom, bool)
        self._is_wall[walls] = True
        self.reset()

    def reset(self) -> None:
        self._pen, self._force, self._steps, self._contacts, self._calls, self._checks = 0.0, 0.0, 0, 0, 0, 0

    def __call__(self, model, data) -> None:
        self._calls += 1
        if self.mode == "geometry":
            if (self._calls - 1) % self.every:
                return
            self._checks += 1
            dist = min_wall_distance(model, data, self._arm, self._walls, cull=0.0)
            if dist < 0:
                self._pen, self._steps, self._contacts = max(self._pen, -dist), self._steps + 1, self._contacts + 1
            return
        self._checks += 1
        import mujoco

        hit, force = 0, np.zeros(6)
        for i in range(data.ncon):
            c = data.contact[i]
            g1, g2 = c.geom1, c.geom2
            if (self._is_arm[g1] and self._is_wall[g2]) or (self._is_arm[g2] and self._is_wall[g1]):
                hit += 1
                self._pen = max(self._pen, -float(c.dist))
                mujoco.mj_contactForce(model, data, i, force)
                self._force = max(self._force, float(force[0]))
        if hit:
            self._steps += 1
            self._contacts += hit

    def report(self) -> WallReport:
        return WallReport(self._pen, self._force, self._steps, self._contacts, self._checks)
