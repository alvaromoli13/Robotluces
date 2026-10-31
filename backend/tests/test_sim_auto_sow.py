"""`sim/auto_sow_eval.py`: the auto mode end to end in the twin, and how it counts what happened."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from sim import auto_sow_eval, eval as sim_eval, layout, make_dataset as md
from sim.measure_layout import project
from smartseed_robot.sim_robot import SimRobot


def test_the_scene_projector_is_the_nominal_projection_when_the_camera_is_nominal():
    robot = SimRobot()
    try:
        scene = auto_sow_eval.scene_projector(robot)
        for point in ((0.3, 0.0, layout.TRAY_TOP_Z), (0.2, -0.15, 0.0), (0.4, 0.12, 0.05)):
            assert scene(point) == pytest.approx(project(point), abs=1e-3)
    finally:
        robot.close()


def test_the_cells_of_the_nominal_tray_are_the_layouts_cells():
    (scene,) = sim_eval.heldout_scenes("black", 1, layout_mode="narrow")
    nominal = dataclasses.replace(scene, tray=md.Placement(layout.TRAY_CENTER, 0.0))
    cells = auto_sow_eval.tray_cells(nominal)
    assert len(cells) == layout.TRAY_ROWS * layout.TRAY_COLS
    for row, col, xy in cells:
        assert xy == pytest.approx(layout.cell_center(row, col)[:2], abs=1e-9)


def test_a_seed_is_in_a_cell_on_the_tray_rim_in_its_box_or_elsewhere():
    (scene,) = sim_eval.heldout_scenes("white", 1, layout_mode="narrow")
    cells = auto_sow_eval.tray_cells(scene)
    centre = cells[5][2]
    assert auto_sow_eval.where(scene, "white", np.array([*centre, 0.007]), cells) == "cell"
    assert auto_sow_eval.where(scene, "white", np.array([*centre, layout.TRAY_TOP_Z + 0.01]), cells) == "tray"  # on the rim
    assert auto_sow_eval.where(scene, "white", scene.seed_xyz(scene.present[0]), cells) == "box"
    assert auto_sow_eval.where(scene, "white", np.array([0.6, 0.3, 0.0]), cells) == "elsewhere"


def test_events_are_summed_into_attempts_by_result_and_the_stop_reasons():
    events = [{"type": "grasp_attempt", "result": r} for r in ("held", "empty", "empty", "dropped", "unreachable")]
    events += [{"type": "auto_stopped", "reason": "gave_up"}, {"type": "finished"}]
    s = auto_sow_eval.summarise_events(events)
    assert (s["attempts"], s["held"], s["empty"], s["dropped"], s["unreachable"]) == (5, 1, 2, 1, 1)
    assert s["stops"] == ["gave_up"] and s["error"] is None


def test_unsown_seeds_are_blamed_on_what_the_run_did_about_them():
    base = {"present": 5, "sown": 2, "in_box": 1, "tray": 1, "elsewhere": 1, "refused": None, "error": None,
            "stops": ["gave_up"]}
    causes = auto_sow_eval.failure_causes(base)
    assert causes["on the tray rim or a divider (missed the cell)"] == 1
    assert causes["out of the box onto the table (pushed or dropped)"] == 1
    assert causes["still in the box: given up after failed grasps"] == 1
    blind = auto_sow_eval.failure_causes(base | {"stops": ["no_seeds"]})
    assert blind["still in the box: not detected (against a wall or in a corner)"] == 1
    assert auto_sow_eval.failure_causes(base | {"refused": "unreachable"}) == {"plan refused (unreachable)": 3}


@pytest.mark.parametrize("color", ["black", "white"])
def test_one_nominal_scene_is_emptied_into_the_tray_by_the_real_executor(color, kin):
    (scene,) = sim_eval.heldout_scenes(color, 1, kin=kin, layout_mode="narrow")
    result = auto_sow_eval.run_scene(scene, kin, camera_noise=False)
    assert result["error"] is None and result["refused"] is None
    assert result["present"] >= 2 and result["sown"] == result["present"]
    assert result["in_box"] == 0 and result["elsewhere"] == 0 and result["stops"] == ["no_seeds"]
    assert result["held"] == result["attempts"] >= result["present"]
