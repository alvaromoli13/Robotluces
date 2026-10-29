"""Scene layout of the SmartSeed twin and the generator of `sim/scene.xml`.

Run `python -m sim.layout` (from the repo root) to rewrite `scene.xml`; a test fails when the committed file and
this generator disagree. Frame: the robot base frame of the backend (x forward away from the base, y left, z up,
metres), the same one `Kinematics.tool_xyz` and `Calibration.pixel_to_robot` use. In the top camera image, up is
+x and right is -y.

Every number is tagged MEASURED (taken from this repo's calibration, FK or a dataset), FITTED (optimised against
the real frames by `sim/fit_top_camera.py`) or ESTIMATED (read off the real top frame by back-projecting pixels
onto a plane of known height, or a guess). `sim/README.md` lists them with the residuals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
SCENE_PATH = SIM_DIR / "scene.xml"
TIMESTEP = 1 / 300  # 10 physics substeps per 30 Hz control step

# MEASURED: backend/data/calibration.json (gitignored there), pixel in the 640x480 top frame -> tool_xyz (FK) of the
# gripper tip the operator dragged over that point. The tip height is not recorded.
CALIBRATION_POINTS = (
    (256.64473684210526, 221.72962648556876, 0.29587978000915216, 0.04426554005991229),
    (254.089558573854, 88.65662139219016, 0.4192147934563827, 0.032358080316208744),
    (445.78735144312395, 81.44524617996605, 0.40926988869766096, -0.10913721129382639),
    (447.1986417657046, 219.98938879456708, 0.2820296930508766, -0.09205916997888285),
)
CALIBRATION_TOOL_Z = 0.12  # FITTED: the single plane height that best explains the four clicks (still ~40 px mean off)
BASE_PAN_AXIS = (0.0388, 0.0)  # MEASURED: URDF/MJCF shoulder_pan axis in the base frame (xy)

# FITTED (sim/fit_top_camera.py): top camera pose in the base frame, `xyaxes` of the MuJoCo camera, vertical fov.
TOP_CAMERA_POS = (0.2998, -0.0216, 0.4997)
TOP_CAMERA_XYAXES = (-0.15474, -0.98796, 0.00057, 0.98796, -0.15474, -0.00029)
TOP_CAMERA_FOVY = 56.183

# The wrist camera lives in the vendored MJCF (see sim/assets/README.md): it rides on the `gripper` body.

# MEASURED (FK of the recorded grasp, episode 0 of smartseed-grasp-d1-clean): the jaws close on the black seed
# with the tool frame at z = -0.0003 m, so the seed centre is at ~0 and the box floor top at about -0.007. The mat top
# (-0.008) is what the boxes, the tray and the camera back-projections stand on: visible, so it must not move.
# T5f: the table PLANE was -0.011 (the tool frame of the taught `home`), but the arm's lowest collision geoms (the
# fixed pad and hull) sit at -0.0195 at both taught poses (`home`, `act_start`), where the real arm rests on a hard
# surface, and every frame of the real d1/d2 episodes stays above -0.0202 (see `sim/README.md`, "Table collisions"). A
# ground at -0.011 or -0.008 put every demo 8-12 mm inside it. So the hard ground (table, paper sheet, mat) now ends at
# -0.0215 / -0.0205 / -0.0197. `MAT_TOP_Z` below is only the plane the mat was SEEN at: the boxes and the tray still
# stand with their floors and rims at the heights read off the top frame (the measured seed height depends on them).
TABLE_Z = -0.0215
MAT_THICKNESS = 0.0018
MAT_SURFACE_Z = TABLE_Z + MAT_THICKNESS
MAT_TOP_Z = -0.008  # the plane the box floors, the tray floor and the mat outline were read at

# The mat, tray and boxes are axis-aligned in the top image, but the camera is yawed against the robot: image up is
# the base-frame direction at this angle, so the board (everything static on the table) is rotated by it.
BOARD_YAW = math.atan2(TOP_CAMERA_XYAXES[4], TOP_CAMERA_XYAXES[3])

CARDBOARD = (0.78, 0.60, 0.40, 1)
CARDBOARD_DARK = (0.62, 0.46, 0.30, 1)
MAT_RGBA = (0.20, 0.19, 0.27, 1)
# ESTIMATED from the real wrist frames (d1 black, d2 white) against the jaw tip width (about 12 mm) and the
# gripper reading: the real jaws stop at about 6.9 on a black seed and 7.4 on a white one, against 6.0 closed empty.
SEED_RADIUS = {"white": 0.0074, "black": 0.0068}
SEED_MASS = 0.001


@dataclass(frozen=True)
class OpenBox:
    """Open-top cardboard box: floor plate plus four walls."""
    name: str
    center: tuple[float, float]
    outer_half: tuple[float, float]  # half extents along x and y of the outside
    height: float
    wall: float = 0.004
    floor: float = 0.0015  # thin cardboard: with the seed radius this puts the seed centre at the measured tool height
    rim_rgba: tuple = CARDBOARD
    floor_rgba: tuple = CARDBOARD

    @property
    def inner_half(self) -> tuple[float, float]:
        return self.outer_half[0] - self.wall, self.outer_half[1] - self.wall

    @property
    def top_z(self) -> float:
        return MAT_TOP_Z + self.height

    @property
    def floor_z(self) -> float:
        """Height of the inside floor (where seeds rest)."""
        return MAT_TOP_Z + self.floor


# ESTIMATED: centres and sizes back-projected from the real top frame (rim height 0.035), see sim/README.md.
WHITE_BOX = OpenBox("box_white", (0.178, 0.173), (0.092, 0.060), 0.035)
BLACK_BOX = OpenBox("box_black", (0.183, -0.158), (0.085, 0.065), 0.035, rim_rgba=(0.07, 0.06, 0.05, 1))

# ESTIMATED: 3x4 seedling tray (3 columns across the image, 4 rows going away from the base).
TRAY_ROWS, TRAY_COLS = 4, 3
TRAY_CENTER = (0.347, 0.019)
TRAY_OUTER_HALF = (0.096, 0.075)  # along x' (rows) and y' (columns): 19.2 x 15.0 cm
TRAY_WALL = 0.003
TRAY_TOP_Z = MAT_TOP_Z + 0.045
CELL_FLOOR_Z = MAT_TOP_Z + 0.008
MAT_CENTER, MAT_HALF = (0.291, 0.007), (0.224, 0.249)  # ESTIMATED: 44.7 x 49.8 cm at MAT_TOP_Z, bottom edge guessed


def mat_outline() -> tuple[tuple[float, float], tuple[float, float]]:
    """(centre, half extents) of the mat in the board frame at its real surface height: the outline that was read off
    the top frame at MAT_TOP_Z, scaled about the camera axis so it projects to the same pixels from MAT_SURFACE_Z."""
    k = (TOP_CAMERA_POS[2] - MAT_SURFACE_Z) / (TOP_CAMERA_POS[2] - MAT_TOP_Z)
    cx, cy = to_board(TOP_CAMERA_POS[:2])
    return ((cx + k * (MAT_CENTER[0] - cx), cy + k * (MAT_CENTER[1] - cy)), (k * MAT_HALF[0], k * MAT_HALF[1]))

# Black seed 0 is MEASURED: the recorded grasp (episode 0 of d1-clean) closes with the tool frame at base xy
# (0.1503, -0.1320); the jaws open along the tool z axis (0.844, -0.524) there, so the seed sits one black radius
# beyond the tool along it, between the pads: (0.1560, -0.1356). The other positions are read off the top frame
# (+-3 mm) for the first two of each colour and ESTIMATED for the extras (board frame, metres).
SEEDS_PER_BOX = 4
_WHITE_SEEDS = ((0.217, 0.186), (0.159, 0.179), (0.200, 0.150), (0.140, 0.205))
_BLACK_SEEDS = ((0.1751, -0.1098), (0.135, -0.185), (0.150, -0.140), (0.215, -0.180))


def to_world(xy) -> tuple[float, float]:
    """Board frame (x' up in the top image, y' left) -> robot base frame."""
    c, s = math.cos(BOARD_YAW), math.sin(BOARD_YAW)
    return c * xy[0] - s * xy[1], s * xy[0] + c * xy[1]


def to_board(xy) -> tuple[float, float]:
    c, s = math.cos(-BOARD_YAW), math.sin(-BOARD_YAW)
    return c * xy[0] - s * xy[1], s * xy[0] + c * xy[1]


def tray_bounds() -> tuple[float, float, float, float]:
    """(x0, x1, y0, y1) of the tray outline in the board frame."""
    return (TRAY_CENTER[0] - TRAY_OUTER_HALF[0], TRAY_CENTER[0] + TRAY_OUTER_HALF[0],
            TRAY_CENTER[1] - TRAY_OUTER_HALF[1], TRAY_CENTER[1] + TRAY_OUTER_HALF[1])


def _pitch() -> tuple[float, float]:
    return ((2 * TRAY_OUTER_HALF[0] - 2 * TRAY_WALL) / TRAY_ROWS, (2 * TRAY_OUTER_HALF[1] - 2 * TRAY_WALL) / TRAY_COLS)


def cell_center(row: int, col: int) -> tuple[float, float, float]:
    """Centre of a cell at its floor, in the base frame. Row 0 is the far row, column 0 the left one in the top
    image."""
    px, py = _pitch()
    x, y = to_world((TRAY_CENTER[0] + (TRAY_ROWS / 2 - 0.5 - row) * px,
                     TRAY_CENTER[1] + (TRAY_COLS / 2 - 0.5 - col) * py))
    return x, y, CELL_FLOOR_Z


def seed_board_positions(color: str) -> tuple[tuple[float, float], ...]:
    """Nominal seed centres of a box in the board frame (x' up in the top image, y' left)."""
    return _WHITE_SEEDS if color == "white" else _BLACK_SEEDS


def seed_positions(color: str) -> list[tuple[float, float, float]]:
    """Seed centres in the base frame, resting on their box floor."""
    box, offsets = (WHITE_BOX, _WHITE_SEEDS) if color == "white" else (BLACK_BOX, _BLACK_SEEDS)
    return [(*to_world(xy), box.floor_z + SEED_RADIUS[color] + 1e-4) for xy in offsets]


def _f(values) -> str:
    return " ".join(f"{v:.5f}".rstrip("0").rstrip(".") if v else "0" for v in values)


def _box(name: str, pos, half, rgba, cls: str = "env") -> str:  # `wall` for walls and dividers, `env` for floors
    return (f'    <geom name="{name}" type="box" pos="{_f(pos)}" size="{_f(half)}" rgba="{_f(rgba)}" '
            f'class="{cls}"/>')


def _body(name: str, center, geoms: list[str]) -> list[str]:
    """One body per movable object (tray, each box), its origin at the object's centre on the board plane, so the
    geoms are written relative to it. The dataset generator moves and turns the object through `body_pos` and
    `body_quat`: MuJoCo builds its static broad phase when the model is compiled, so editing the `geom_pos` of a
    static geom at run time would leave its collisions at the nominal place."""
    return [f'    <body name="{name}" pos="{_f((*center, 0.0))}">', *geoms, '    </body>']


def _open_box(b: OpenBox) -> list[str]:
    center, (cx, cy) = b.center, (0.0, 0.0)  # geoms are relative to the box body
    (hx, hy), h, w, z0 = b.outer_half, b.height, b.wall, MAT_TOP_Z
    zc, hz = (MAT_SURFACE_Z + z0 + h) / 2, (z0 + h - MAT_SURFACE_Z) / 2  # walls reach down to the mat: no gap under them
    return _body(b.name, center, [
        _box(f"{b.name}_floor", (cx, cy, (MAT_SURFACE_Z + z0 + b.floor) / 2), (hx, hy, (z0 + b.floor - MAT_SURFACE_Z) / 2),
             b.floor_rgba),  # solid down to the mat: the top is what the seeds rest on, nothing sinks under it
        _box(f"{b.name}_wall_far", (cx + hx - w / 2, cy, zc), (w / 2, hy, hz), b.rim_rgba, "wall"),
        _box(f"{b.name}_wall_near", (cx - hx + w / 2, cy, zc), (w / 2, hy, hz), b.rim_rgba, "wall"),
        _box(f"{b.name}_wall_left", (cx, cy + hy - w / 2, zc), (hx - w, w / 2, hz), b.rim_rgba, "wall"),
        _box(f"{b.name}_wall_right", (cx, cy - hy + w / 2, zc), (hx - w, w / 2, hz), b.rim_rgba, "wall"),
    ])


def _tray() -> list[str]:
    (cx, cy), (hx, hy), w = (0.0, 0.0), TRAY_OUTER_HALF, TRAY_WALL  # relative to the tray body
    z0, h, fl = MAT_TOP_Z, TRAY_TOP_Z - MAT_TOP_Z, CELL_FLOOR_Z - MAT_TOP_Z  # wall height, floor thickness
    px, py = _pitch()
    zc, hz = (MAT_SURFACE_Z + z0 + h) / 2, (z0 + h - MAT_SURFACE_Z) / 2  # walls and dividers reach down to the mat
    geoms = [
        _box("tray_floor", (cx, cy, (MAT_SURFACE_Z + z0 + fl) / 2), (hx, hy, (z0 + fl - MAT_SURFACE_Z) / 2), CARDBOARD),
        _box("tray_wall_far", (cx + hx - w / 2, cy, zc), (w / 2, hy, hz), CARDBOARD, "wall"),
        _box("tray_wall_near", (cx - hx + w / 2, cy, zc), (w / 2, hy, hz), CARDBOARD, "wall"),
        _box("tray_wall_left", (cx, cy + hy - w / 2, zc), (hx - w, w / 2, hz), CARDBOARD, "wall"),
        _box("tray_wall_right", (cx, cy - hy + w / 2, zc), (hx - w, w / 2, hz), CARDBOARD, "wall"),
    ]
    for i in range(1, TRAY_ROWS):  # dividers between rows (across y)
        x = cx - hx + w + i * px
        geoms.append(_box(f"tray_div_row{i}", (x, cy, zc), (w / 2, hy - w, hz), CARDBOARD_DARK, "wall"))
    for j in range(1, TRAY_COLS):  # dividers between columns (across x)
        y = cy - hy + w + j * py
        geoms.append(_box(f"tray_div_col{j}", (cx, y, zc), (hx - w, w / 2, hz), CARDBOARD_DARK, "wall"))
    return _body("tray", TRAY_CENTER, geoms)


def _seeds() -> list[str]:
    out = []
    for color, rgba in (("white", (0.93, 0.92, 0.88, 1)), ("black", (0.05, 0.05, 0.05, 1))):
        for i, pos in enumerate(seed_positions(color)):
            out.append(f'    <body name="seed_{color}_{i}" pos="{_f(pos)}">\n'
                       f'      <freejoint name="seed_{color}_{i}_free"/>\n'
                       f'      <geom name="seed_{color}_{i}_geom" type="sphere" size="{SEED_RADIUS[color]}" '
                       f'mass="{SEED_MASS}" rgba="{_f(rgba)}" class="seed"/>\n    </body>')
    return out


def build_scene_xml() -> str:
    mat_c, mat_h = mat_outline()
    lines = [
        "<!-- Generated by `python -m sim.layout`; edit sim/layout.py, not this file. -->",
        '<mujoco model="smartseed_scene">',
        '  <include file="assets/so101/so101_new_calib_camera.xml"/>',
        ' <compiler meshdir="assets/so101/assets" autolimits="true"/>'
        f'  <option timestep="{TIMESTEP:.10f}" integrator="implicitfast" cone="elliptic" impratio="10"/>',
        '  <visual>',
        '    <global offwidth="640" offheight="480"/>',
        '    <quality shadowsize="2048"/>',
        '    <headlight ambient="0.30 0.30 0.30" diffuse="0.25 0.25 0.25" specular="0 0 0"/>',
        '  </visual>',
        '  <default>',
        # bit 1 = arm (contype 1), bit 2 = scene: the arm hits the scene, the scene hits itself and the seeds
        # T5f: the table, the paper and the mat are hard in reality: every arm geom (bits 1 hulls, 8 pads, 16 moving
        # hull) and the seeds (bit 2) stop at them. Stiff contact, `priority` so it wins over the arm's soft defaults
        '    <default class="ground"><geom contype="4" conaffinity="27" priority="1" friction="0.9 0.005 0.0001" '
        'solref="0.004 1" solimp="0.95 0.99 0.001"/></default>',
        # box and tray floors: cardboard on the hard mat. T5f: stiff like the ground under them (they used to be soft and
        # rest on the mat 1.5 mm below, which caught a seed that a pad pressed into the floor); they stand on the mat now
        '    <default class="env"><geom contype="2" conaffinity="3" priority="1" friction="0.9 0.005 0.0001" '
        'solref="0.004 1" solimp="0.95 0.99 0.001"/></default>',
        # walls and dividers of the boxes and the tray: bit 16 is what the jaw hull and the pads carry, so every jaw
        # geom stops at a wall (and the floors stay as they were); `priority` makes the wall's stiff contact
        # parameters win over the arm's soft defaults
        '    <default class="wall"><geom contype="2" conaffinity="19" priority="1" friction="0.9 0.005 0.0001" '
        'solref="0.004 1" solimp="0.95 0.99 0.001"/></default>',
        '    <default class="seed"><geom contype="2" conaffinity="10" friction="1.2 0.02 0.002" condim="4" '
        'solref="0.004 1" solimp="0.95 0.99 0.001"/></default>',
        '  </default>',
        '  <asset>',
        '    <material name="matte" specular="0" shininess="0"/>',
        '  </asset>',
        '  <worldbody>',
        '    <light name="ceiling" pos="0.3 0 1.5" dir="0 0 -1" directional="true" diffuse="0.35 0.35 0.35" '
        'specular="0 0 0" castshadow="true"/>',
        f'    <camera name="top" pos="{_f(TOP_CAMERA_POS)}" xyaxes="{_f(TOP_CAMERA_XYAXES)}" '
        f'fovy="{TOP_CAMERA_FOVY:.4f}"/>',
        f'    <geom name="table" type="plane" pos="0 0 {TABLE_Z}" size="1.5 1.5 0.01" rgba="0.80 0.82 0.80 1" '
        'class="ground"/>',
        f'    <body name="board" euler="0 0 {BOARD_YAW:.6f}">',
        _box("paper", (mat_c[0], mat_c[1], TABLE_Z + 0.0005),
             (mat_h[0] + 0.045, mat_h[1] + 0.045, 0.0005), (0.93, 0.94, 0.95, 1), "ground"),
        _box("mat", (*mat_c, TABLE_Z + MAT_THICKNESS / 2), (*mat_h, MAT_THICKNESS / 2), MAT_RGBA, "ground"),
        *_tray(), *_open_box(WHITE_BOX), *_open_box(BLACK_BOX),
        '    </body>',
        *_seeds(),
        '  </worldbody>',
        '</mujoco>',
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    SCENE_PATH.write_text(build_scene_xml())
    print(f"wrote {SCENE_PATH}")
