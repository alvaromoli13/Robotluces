#!/usr/bin/env bash
# Runs on a 2-GPU Brev box: installs lerobot at the pinned commit, then trains two ACT variants of
# one dataset in parallel, one per GPU. Usage: train_pair.sh <dataset repo id> <model name prefix> (HF_USER overrides the Hub account the models go to)
set -uo pipefail
DATASET="$1"; NAME="$2"; HF_USER="${HF_USER:-RafaelJaime}"
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
python -c "import torch; print('torch', torch.__version__, 'gpus', torch.cuda.device_count())"
# Download the dataset once so the two runs do not race on the cache.
python -c "from lerobot.datasets.lerobot_dataset import LeRobotDataset; print(LeRobotDataset('$DATASET').meta.total_episodes, 'episodes')" || exit 1

run() {  # gpu variant extra-args...
  local gpu="$1" variant="$2"; shift 2
  local job="act-${NAME}-${variant}"
  cd "$HOME"
  CUDA_VISIBLE_DEVICES="$gpu" lerobot-train \
    --dataset.repo_id="$DATASET" \
    --policy.type=act \
    --policy.device=cuda \
    --batch_size=32 \
    --num_workers=12 \
    --steps=40000 \
    --save_freq=10000 \
    --log_freq=100 \
    --output_dir="$HOME/outputs/train/$job" \
    --job_name="$job" \
    --policy.repo_id="$HF_USER/$job" \
    --policy.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101"]' \
    --save_checkpoint_to_hub=true \
    --wandb.enable=false "$@" > "$HOME/train-$variant.log" 2>&1 \
    && touch "$HOME/DONE-$variant" || touch "$HOME/FAILED-$variant"
}

echo "== $(date) train"
run 0 c100 &
run 1 c50 --policy.chunk_size=50 --policy.n_action_steps=50 &
wait
echo "== $(date) all done"
touch "$HOME/TRAIN_DONE"
