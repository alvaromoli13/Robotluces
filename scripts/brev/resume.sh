#!/usr/bin/env bash
# Runs on a 1-GPU Brev box: resumes an ACT run from a Hub checkpoint (optimizer state included) and trains
# it to a new total step count, pushing to a new repo. Usage: resume.sh <src repo> <step> <total steps> <new repo>
set -uo pipefail
SRC="$1"; STEP="$2"; TOTAL="$3"; DST="$4"
JOB="${DST#*/}"
OUT="$HOME/outputs/train/$JOB"
export PATH="$HOME/.local/bin:$PATH"
exec > >(tee -a "$HOME/setup.log") 2>&1

echo "== $(date) setup"
nvidia-smi --query-gpu=name,memory.total --format=csv
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg git >/dev/null || true
[ -d "$HOME/lerobot" ] || git clone -q https://github.com/huggingface/lerobot.git "$HOME/lerobot"
cd "$HOME/lerobot" && git checkout -q e595b79
[ -d .venv ] || uv venv -q --python 3.12 .venv
. .venv/bin/activate
uv pip install -q -e ".[training]" || exit 1

# Lay the checkpoint out as lerobot-train expects for --resume: <out>/checkpoints/<step> + last -> <step>.
python - "$SRC" "$STEP" "$TOTAL" "$DST" "$OUT" <<'EOF' || exit 1
import json, os, shutil, sys
from huggingface_hub import snapshot_download
src, step, total, dst, out = sys.argv[1:]
d = snapshot_download(src, allow_patterns=[f"checkpoints/{step}/*"])
ck = os.path.join(out, "checkpoints")
os.makedirs(ck, exist_ok=True)
shutil.copytree(os.path.join(d, "checkpoints", step), os.path.join(ck, step), dirs_exist_ok=True)
link = os.path.join(ck, "last")
if os.path.lexists(link):
    os.remove(link)
os.symlink(step, link)
p = os.path.join(ck, step, "pretrained_model", "train_config.json")
cfg = json.load(open(p))
cfg["steps"], cfg["output_dir"], cfg["job_name"] = int(total), out, dst.split("/")[-1]
cfg["policy"]["repo_id"], cfg["policy"]["device"] = dst, "cuda"
cfg["num_workers"] = min(cfg.get("num_workers", 12), os.cpu_count() - 2)
json.dump(cfg, open(p, "w"), indent=2)
print("resume from", p, "steps", cfg["steps"], "batch", cfg["batch_size"], "repo", dst)
EOF

echo "== $(date) train"
cd "$HOME"
lerobot-train --config_path="$OUT/checkpoints/last/pretrained_model/train_config.json" --resume=true \
  > "$HOME/train.log" 2>&1 && touch "$HOME/DONE" || touch "$HOME/FAILED"
echo "== $(date) all done"
