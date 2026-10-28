"""Stop / continue decision of the eval-driven Brev controller (`scripts/brev/auto_train.sh`). Pure logic plus a small CLI.

Per model, each Hub checkpoint step is evaluated on held-out scenes and logged as step -> successes
(`sim/out/auto_train/<name>.json`). A model stops when, on that log,
  - its best success rate reached TARGET (90 %), or
  - PATIENCE (2) consecutive checkpoints did not beat the best count so far (strictly higher = improved; patience 2 with a
    checkpoint every 10k steps = 20k steps), or
  - the last evaluated checkpoint is at the CAP (120000 steps).
Otherwise a run that reached its `--steps` limit is resumed with `resume_target`: +40k steps, capped at 120k.
The best checkpoint is the earliest one with the highest count.

CLI (used by the shell script): record, decide, resume-target, pending, parse, best, hub-steps, write-card.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CAP = 120_000
EXTEND = 40_000
PATIENCE = 2
TARGET = 0.9
CARD_START, CARD_END = "<!-- best-checkpoint -->", "<!-- /best-checkpoint -->"


@dataclass(frozen=True)
class Decision:
    stop: bool
    reason: str  # "target" | "patience" | "cap" | "continue"
    best_step: str | None
    best: int
    episodes: int


def decide(results: Mapping[str, int], episodes: int, *, cap: int = CAP, patience: int = PATIENCE,
           target: float = TARGET) -> Decision:
    best, best_step, misses, last = -1, None, 0, 0
    for step in sorted(results, key=int):
        last = int(step)
        if results[step] > best:
            best, best_step, misses = results[step], step, 0
        else:
            misses += 1
    if best_step is None:
        return Decision(False, "continue", None, 0, episodes)
    reason = ("target" if best / episodes >= target else "patience" if misses >= patience
              else "cap" if last >= cap else "continue")
    return Decision(reason != "continue", reason, best_step, best, episodes)


def resume_target(limit: int, cap: int = CAP, extend: int = EXTEND) -> int | None:
    """New `--steps` for a run that finished at `limit`, or None at the cap."""
    return None if limit >= cap else min(limit + extend, cap)


def parse_eval_summary(text: str) -> tuple[int, int] | None:
    """(successes, episodes) from the last `Summary.line` of `sim/eval.py`."""
    found = re.findall(r"(\d+)/(\d+) lifted a seed", text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def load(path: Path) -> dict:
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {"results": {}}


def record(path: Path, step: str, successes: int, episodes: int, *, repo: str = "", color: str = "") -> None:
    data = load(path)
    data.update({k: v for k, v in (("repo", repo), ("color", color)) if v})
    data["results"][step] = {"successes": successes, "episodes": episodes}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def decide_log(path: Path, **kw) -> Decision:
    res = load(path)["results"]
    episodes = max((r["episodes"] for r in res.values()), default=1)
    return decide({s: r["successes"] for s, r in res.items()}, episodes, **kw)


def pending_steps(path: Path, hub_steps: list[str]) -> list[str]:
    done = set(load(path)["results"])
    return sorted((s for s in hub_steps if s not in done), key=int)


def best_of(path: Path) -> tuple[str, int, int] | None:
    d = decide_log(path)
    return None if d.best_step is None else (d.best_step, d.best, d.episodes)


def card_with_best(readme: str, step: str, successes: int, episodes: int, color: str) -> str:
    block = (f"{CARD_START}\n## Best checkpoint\n\n`checkpoints/{step}` is the best checkpoint on held-out narrow-layout "
             f"scenes of the SmartSeed MuJoCo twin ({color} seed): {successes}/{episodes} episodes lifted a seed over 3 cm "
             f"(`sim/eval.py --layout narrow`). Picked by `scripts/brev/auto_train.sh`; no checkpoint was deleted or "
             f"overwritten, and the repo root holds the weights of the last step, not necessarily this one.\n{CARD_END}\n")
    pattern = re.compile(re.escape(CARD_START) + r".*?" + re.escape(CARD_END) + r"\n?", re.S)
    if pattern.search(readme):
        return pattern.sub(lambda _: block, readme)
    return readme.rstrip("\n") + "\n\n" + block


def hub_steps(repo: str) -> list[str]:
    from huggingface_hub import HfApi

    names = {s.rfilename for s in HfApi().model_info(repo).siblings}
    found = {m.group(1) for n in names if (m := re.fullmatch(r"checkpoints/(\d+)/pretrained_model/model\.safetensors", n))}
    return sorted(found, key=int)


def write_card(repo: str, log: Path) -> None:
    """Add or refresh the best-checkpoint block of the model card (README.md only; nothing else is touched)."""
    from huggingface_hub import HfApi, hf_hub_download

    best = best_of(log)
    if best is None:
        raise SystemExit("no evaluated checkpoint")
    path = hf_hub_download(repo, "README.md", force_download=True)
    new = card_with_best(Path(path).read_text(), *best, load(log).get("color", ""))
    HfApi().upload_file(path_or_fileobj=new.encode(), path_in_repo="README.md", repo_id=repo,
                        commit_message=f"docs: best checkpoint {best[0]} ({best[1]}/{best[2]} held-out)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--log", required=True), r.add_argument("--step", required=True)
    r.add_argument("--successes", type=int, required=True), r.add_argument("--episodes", type=int, required=True)
    r.add_argument("--repo", default=""), r.add_argument("--color", default="")
    d = sub.add_parser("decide")
    d.add_argument("--log", required=True)
    d.add_argument("--cap", type=int, default=CAP), d.add_argument("--patience", type=int, default=PATIENCE)
    d.add_argument("--target", type=float, default=TARGET)
    sub.add_parser("resume-target").add_argument("limit", type=int)
    p = sub.add_parser("pending")
    p.add_argument("--log", required=True), p.add_argument("--steps", default="")
    sub.add_parser("parse")
    sub.add_parser("best").add_argument("--log", required=True)
    sub.add_parser("hub-steps").add_argument("repo")
    w = sub.add_parser("write-card")
    w.add_argument("--repo", required=True), w.add_argument("--log", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "record":
        record(Path(a.log), a.step, a.successes, a.episodes, repo=a.repo, color=a.color)
    elif a.cmd == "decide":
        x = decide_log(Path(a.log), cap=a.cap, patience=a.patience, target=a.target)
        print(f"{'stop' if x.stop else 'continue'} {x.reason} best {x.best_step} {x.best}/{x.episodes}")
    elif a.cmd == "resume-target":
        t = resume_target(a.limit)
        print("" if t is None else t)
    elif a.cmd == "pending":
        print(" ".join(pending_steps(Path(a.log), a.steps.split())))
    elif a.cmd == "parse":
        s = parse_eval_summary(sys.stdin.read())
        if s is None:
            return 1
        print(*s)
    elif a.cmd == "best":
        b = best_of(Path(a.log))
        if b is None:
            return 1
        print(*b)
    elif a.cmd == "hub-steps":
        print(" ".join(hub_steps(a.repo)))
    elif a.cmd == "write-card":
        write_card(a.repo, Path(a.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
