"""`sim/auto_stop.py`: the stop/continue decision of the eval-driven Brev controller. Pure logic, no network."""
from __future__ import annotations

import json

import pytest

from sim import auto_stop as a


def res(*counts, episodes=30):
    return {f"{(i + 1) * 10000:06d}": c for i, c in enumerate(counts)}, episodes


def test_keeps_going_while_it_improves():
    r, n = res(1, 3, 5)
    d = a.decide(r, n)
    assert not d.stop and d.best_step == "030000" and d.best == 5


def test_no_results_means_continue():
    assert not a.decide({}, 30).stop


def test_stops_after_two_checkpoints_without_a_strictly_higher_count():
    r, n = res(2, 6, 6, 5)
    d = a.decide(r, n)
    assert d.stop and d.reason == "patience" and d.best_step == "020000"


def test_one_bad_checkpoint_is_not_enough():
    r, n = res(2, 6, 4)
    assert not a.decide(r, n).stop


def test_a_tie_is_not_an_improvement_and_the_earlier_step_is_the_best():
    r, n = res(4, 4, 4)
    d = a.decide(r, n)
    assert d.stop and d.best_step == "010000"


def test_an_improvement_resets_the_patience():
    r, n = res(2, 2, 3, 3)
    assert not a.decide(r, n).stop


def test_stops_at_ninety_percent_even_when_still_improving():
    d = a.decide({"010000": 27}, 30)
    assert d.stop and d.reason == "target"
    assert not a.decide({"010000": 26}, 30).stop  # 86.7 %


def test_stops_at_the_cap():
    d = a.decide({"110000": 1, "120000": 5}, 30)
    assert d.stop and d.reason == "cap" and d.best_step == "120000"


def test_results_are_ordered_by_step_not_by_key_order():
    d = a.decide({"030000": 6, "010000": 2, "020000": 6}, 30)
    assert d.best_step == "020000" and not d.stop  # 030000 ties 020000: one miss only


@pytest.mark.parametrize("limit,target", [(40000, 80000), (80000, 120000), (100000, 120000), (120000, None), (130000, None)])
def test_resume_target_adds_40k_capped_at_120k(limit, target):
    assert a.resume_target(limit) == target


def test_parse_eval_summary():
    out = "scene 3: ...\nact (black): 7/30 lifted a seed over 3 cm (23 %); ends holding one 2/30; max lift"
    assert a.parse_eval_summary(out) == (7, 30)
    assert a.parse_eval_summary("Traceback") is None


def test_log_roundtrip_and_pending_steps(tmp_path):
    p = tmp_path / "x.json"
    a.record(p, "010000", 3, 30, repo="r/m", color="black")
    a.record(p, "020000", 5, 30, repo="r/m", color="black")
    data = json.loads(p.read_text())
    assert data["repo"] == "r/m" and data["results"]["020000"] == {"successes": 5, "episodes": 30}
    assert a.pending_steps(p, ["010000", "020000", "030000"]) == ["030000"]
    assert a.pending_steps(tmp_path / "none.json", ["010000"]) == ["010000"]
    assert a.best_of(p) == ("020000", 5, 30)


def test_card_gets_one_best_checkpoint_block_and_is_idempotent():
    card = "---\ntags: [a]\n---\n# act\nbody\n"
    one = a.card_with_best(card, "020000", 5, 30, "black")
    assert one.startswith("---\ntags: [a]\n---") and "checkpoints/020000" in one and "5/30" in one
    two = a.card_with_best(one, "030000", 8, 30, "black")
    assert two.count("best-checkpoint") == 2 and "checkpoints/030000" in two and "checkpoints/020000" not in two
    assert "body" in two
