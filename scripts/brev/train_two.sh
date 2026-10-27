#!/usr/bin/env bash
# Runs on a 2-GPU Brev box: installs lerobot at the pinned commit, then trains one ACT (chunk 100) per dataset,
# one per GPU. Usage: train_two.sh <dataset A> <model name A> <dataset B> <model name B>
# (models go to $HF_USER/act-<name>; HF_USER defaults to RafaelJaime). Writes DONE-<name>/FAILED-<name>, then TRAIN_DONE.
set -uo pipefail
DS_A="$1"; NAME_A="$2"; DS_B="$3"; NAME_B="$4"; HF_USER="${HF_USER:-RafaelJaime}"
export PATH="$HOME/.local/bin:$PATH"
exec > >(tee -a "$HOME/setup.log") 2>&1
# Any exit before training starts (failed install, unreadable dataset...) must still end the run, so the watcher
# deletes the box instead of waiting on an idle GPU.
trap '[ -e "$HOME/TRAIN_DONE" ] || { touch "$HOME/FAILED-setup" "$HOME/TRAIN_DONE"; echo "== $(date) setup FAILED"; }' EXIT

echo "== $(date) setup"
# Hyperstack boxes link ~/.cache to a root-owned /ephemeral/cache: the dataset download then fails with
# PermissionError. Take ownership of the cache before anything writes to it.
cache="$(readlink -f "$HOME/.cache" 2>/dev/null || echo "$HOME/.cache")"
sudo mkdir -p "$cache" && sudo chown -R "$(id -u):$(id -g)" "$cache" || exit 1
mkdir -p "$HOME/.cache/huggingface" && [ -w "$HOME/.cache/huggingface" ] || exit 1
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
# Download both datasets up front so the two runs do not race on the cache.
for ds in "$DS_A" "$DS_B"; do
  python -c "from lerobot.datasets.lerobot_dataset import LeRobotDataset; print('$ds', LeRobotDataset('$ds').meta.total_episodes, 'episodes')" || exit 1
done

run() {  # gpu dataset name
  local gpu="$1" ds="$2" job="act-$3"
  cd "$HOME" || return 1
  CUDA_VISIBLE_DEVICES="$gpu" lerobot-train \
    --dataset.repo_id="$ds" \
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
    --policy.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101","simulation"]' \
    --save_checkpoint_to_hub=true \
    --wandb.enable=false > "$HOME/train-$3.log" 2>&1 \
    && touch "$HOME/DONE-$3" || touch "$HOME/FAILED-$3"
}

echo "== $(date) train"
run 0 "$DS_A" "$NAME_A" &
run 1 "$DS_B" "$NAME_B" &
wait
echo "== $(date) all done"
touch "$HOME/TRAIN_DONE"
