#!/usr/bin/env bash
# Smoke test WITHOUT A ROBOT: 50 ACT steps on a public dataset.
# Validates in one go: torch+MPS, video decoding, the dataset pipeline and lerobot-train.
# If this passes, your environment is healthy. Run it BEFORE touching hardware.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
activate_venv
export PYTORCH_ENABLE_MPS_FALLBACK=1

lerobot-train \
  --dataset.repo_id=lerobot/svla_so101_pickplace \
  --policy.type=act \
  --output_dir="${ROOT}/outputs/smoke" \
  --job_name=smoke \
  --policy.device=mps \
  --batch_size=2 \
  --steps=50 \
  --save_checkpoint=false \
  --policy.push_to_hub=false \
  --wandb.enable=false

c_grn "OK: training environment works"
echo "clean up: rm -rf ${ROOT}/outputs/smoke"
