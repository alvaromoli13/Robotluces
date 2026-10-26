#!/usr/bin/env bash
# LOCAL training on MPS (Apple Silicon).
#
#   POLICY_TYPE=act      -> trains from scratch. Fast and reliable.
#   POLICY_TYPE=smolvla  -> fine-tunes lerobot/smolvla_base. Better generalization,
#                           much slower on MPS. With 24 GB use BATCH_SIZE=1 or 2.
#
# Resume a cut run:  RESUME=1 ./scripts/20_train_local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; resolve_hf_user

# Without this, any op with no MPS kernel aborts the training midway.
export PYTORCH_ENABLE_MPS_FALLBACK=1
# On MPS do not use AMP/bf16 or torch.compile: support is incomplete. fp32 and go.

RUN="$(RUN_DIR)"
if [ "${RESUME:-0}" = "1" ]; then
  exec lerobot-train --config_path="${RUN}/checkpoints/last/pretrained_model/train_config.json" --resume=true
fi

POLICY_ARGS=(--policy.type="${POLICY_TYPE}")
if [ "${POLICY_TYPE}" = "smolvla" ]; then
  POLICY_ARGS=(--policy.path=lerobot/smolvla_base)
fi

c_bold "run: ${RUN}  |  ${POLICY_TYPE} @ ${DEVICE}  |  batch ${BATCH_SIZE}  |  ${STEPS} steps"

lerobot-train \
  --dataset.repo_id="$(DATASET_REPO)" \
  "${POLICY_ARGS[@]}" \
  --output_dir="${RUN}" \
  --job_name="${POLICY_TYPE}-${TASK_NAME}" \
  --policy.device="${DEVICE}" \
  --batch_size="${BATCH_SIZE}" \
  --steps="${STEPS}" \
  --policy.repo_id="$(POLICY_REPO)" \
  --policy.tags="${HF_TAGS}" \
  --wandb.enable="${WANDB:-false}"

c_grn "checkpoints in ${RUN}/checkpoints — the last one is pushed to $(POLICY_REPO)"
