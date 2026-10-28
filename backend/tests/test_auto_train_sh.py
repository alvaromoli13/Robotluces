"""`scripts/brev/auto_train.sh` driven by fake ssh / brev / python: no network, no box, no GPU."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "brev" / "auto_train.sh"
BLACK, WHITE = "me/act-sim-black-narrow-c100", "me/act-sim-white-narrow-c100"
NB, NW = "sim-black-narrow-c100", "sim-white-narrow-c100"

FAKE_SSH = """#!/usr/bin/env bash
cmd="${@: -1}"
echo "$cmd" >> "$FAKE/calls"
case "$cmd" in
  *MARKS*)
    [ -e "$FAKE/down" ] && exit 255
    n=$(( $(cat "$FAKE/counter" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE/counter"
    [ -f "$FAKE/status.$n" ] && cp "$FAKE/status.$n" "$FAKE/cur"
    cat "$FAKE/cur";;
  *"cat > ~/resume_run.sh"*) cat > "$FAKE/uploaded_resume_run.sh";;
  *"cat ~/"*) echo "log of $cmd";;
esac
exit 0
"""
FAKE_BREV = """#!/usr/bin/env bash
case "$1" in
  ls) if [ -e "$FAKE/loggedout" ]; then echo "You are currently logged out"; elif [ -e "$FAKE/deleted" ]; then echo "other-box RUNNING";
      else echo "smartseed-narrow RUNNING"; fi;;
  delete) echo "delete $*" >> "$FAKE/calls_brev"; touch "$FAKE/deleted";;
esac
"""
FAKE_PY = """#!/usr/bin/env bash
case "$*" in
  *auto_stop.py*hub-steps*) cat "$FAKE/hub_$(basename "${@: -1}")" 2>/dev/null;;
  *auto_stop.py*write-card*) echo "$*" >> "$FAKE/calls_cards";;
  *eval.py*)
    while [ $# -gt 0 ]; do case "$1" in --checkpoint) step="$2";; --color) color="$2";; --layout) layout="$2";; esac; shift; done
    echo "eval $color $step $layout" >> "$FAKE/calls_eval"
    [ -e "$FAKE/evalfail" ] && { echo Traceback; exit 1; }
    echo "act ($color): $(cat "$FAKE/eval_${color}_$step" 2>/dev/null || echo 0)/30 lifted a seed over 3 cm (0 %)";;
  *) exec "$REAL_PY" "$@";;
esac
"""


class Box:
    def __init__(self, tmp: Path):
        self.dir, self.bin = tmp / "fake", tmp / "bin"
        self.dir.mkdir(), self.bin.mkdir()
        for name, body in (("ssh", FAKE_SSH), ("brev", FAKE_BREV), ("py", FAKE_PY)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.tmp = tmp

    def status(self, n: int, marks: str = "", step: str = "1K", alive: int = 1):
        (self.dir / f"status.{n}").write_text(
            f"MARKS {marks}\nRUN {NB} {alive} step:{step}\nRUN {NW} {alive} step:{step}\n")

    def hub(self, name: str, steps: list[int]):
        (self.dir / f"hub_act-{name}").write_text(" ".join(f"{s:06d}" for s in steps))

    def result(self, color: str, step: int, k: int):
        (self.dir / f"eval_{color}_{step:06d}").write_text(str(k))

    def run(self, **env):
        e = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE": str(self.dir), "PYTHON": str(self.bin / "py"),
             "REAL_PY": sys.executable, "SLEEP_S": "0", "NOTIFY": "0", "STALL_MIN": "100000", "FIRST_STEP_MIN": "100000",
             "OUT_DIR": str(self.tmp / "out"), "LOGS": str(self.tmp / "logs"), "STATE": str(self.tmp / "state"), **env}
        p = subprocess.run(["bash", str(SCRIPT), "smartseed-narrow", BLACK, WHITE], env=e, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def read(self, name: str) -> str:
        f = self.dir / name
        return f.read_text() if f.exists() else ""

    @property
    def deleted(self) -> bool:
        return (self.dir / "deleted").exists()


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def curve(b: Box, color: str, name: str, counts: list[int]):
    b.hub(name, [10000 * (i + 1) for i in range(len(counts))])
    for i, k in enumerate(counts):
        b.result(color, 10000 * (i + 1), k)


def test_patience_stops_both_models_kills_their_runs_and_deletes_the_box(box):
    box.status(1)
    curve(box, "black", NB, [2, 6, 6, 5])
    curve(box, "white", NW, [3, 4, 4, 4])
    rc, out = box.run()
    assert rc == 0 and box.deleted, out
    assert "tmux new" not in box.read("calls")
    assert box.read("calls").count("pkill") == 2
    assert "BEST me/act-sim-black-narrow-c100: checkpoint 020000 6 30" in out
    assert "BEST me/act-sim-white-narrow-c100: checkpoint 020000 4 30" in out
    assert box.read("calls_cards").count("write-card") == 2
    assert set(box.read("calls_eval").split("\n")) >= {"eval black 010000 narrow", "eval white 040000 narrow"}
    assert (box.tmp / "out" / f"{NB}.json").exists()
    assert "step:" not in box.read("calls_brev")


def test_a_finished_run_that_still_improves_is_resumed_with_40k_more_steps_then_stops(box):
    box.status(1, marks=f"DONE-{NB} DONE-{NW} TRAIN_DONE")
    box.status(2, marks="", step="41K")
    curve(box, "black", NB, [1, 2, 3, 4, 4, 4])
    curve(box, "white", NW, [1, 2, 3, 4, 4, 4])
    rc, out = box.run()
    calls = box.read("calls")
    assert rc == 0 and box.deleted, out
    assert calls.count("tmux new -d -s resume-" + NB) == 1 and f"resume_run.sh {NB} 80000" in calls
    assert f"resume_run.sh {NW} 80000" in calls
    assert "lerobot-train" in box.read("uploaded_resume_run.sh") and "--resume=true" in box.read("uploaded_resume_run.sh")
    assert "BEST me/act-sim-black-narrow-c100: checkpoint 040000 4 30" in out


def test_no_resume_past_the_cap(box):
    box.status(1, marks=f"DONE-{NB} DONE-{NW}")
    for color, name in (("black", NB), ("white", NW)):
        box.hub(name, [110000, 120000])
        box.result(color, 110000, 1), box.result(color, 120000, 5)
    rc, out = box.run(START_STEPS="120000")
    assert rc == 0 and box.deleted, out
    assert "tmux new" not in box.read("calls")
    assert "checkpoint 120000 5 30" in out


def test_target_success_stops_a_model_early(box):
    box.status(1)
    curve(box, "black", NB, [28])
    curve(box, "white", NW, [28])
    rc, out = box.run()
    assert rc == 0 and "DECISION " + NB + ": stop target" in out and box.deleted


def test_setup_failure_deletes_the_box(box):
    box.status(1, marks="FAILED-setup TRAIN_DONE ")
    rc, out = box.run()
    assert rc == 1 and box.deleted and "SETUP FAILED" in out and "logs saved" in out


def test_both_runs_failed_delete_the_box_with_exit_1(box):
    box.status(1, marks=f"FAILED-{NB} FAILED-{NW}", alive=0)
    rc, out = box.run()
    assert rc == 1 and box.deleted, out


def test_a_stalled_step_deletes_the_box(box):
    box.status(1, step="9K")
    rc, out = box.run(STALL_MIN="3")
    assert rc == 1 and box.deleted and "STALLED" in out


def test_no_step_at_all_deletes_the_box(box):
    (box.dir / "status.1").write_text(f"MARKS \nRUN {NB} 1 none\nRUN {NW} 1 none\n")
    rc, out = box.run(FIRST_STEP_MIN="3")
    assert rc == 1 and box.deleted and "NO TRAINING STEP" in out


def test_an_unreachable_box_is_deleted_after_the_grace_period(box):
    (box.dir / "down").touch()
    rc, out = box.run(UNREACH_MIN="3")
    assert rc == 1 and box.deleted and "UNREACHABLE" in out


def test_logged_out_brev_exits_3_without_deleting(box):
    box.status(1, marks="FAILED-setup ")
    (box.dir / "loggedout").touch()
    rc, out = box.run(LOGIN_WAIT_MIN="0")
    assert rc == 3 and not box.deleted and "LOGIN NEEDED" in out
    assert box.read("calls_brev") == ""


def test_an_eval_that_keeps_failing_stops_the_model_instead_of_training_blind(box):
    box.status(1)
    curve(box, "black", NB, [1])
    curve(box, "white", NW, [1])
    (box.dir / "evalfail").touch()
    rc, out = box.run(EVAL_RETRIES="1")
    assert rc == 0 and box.deleted and f"STOP {NB}: eval-failed" in out
