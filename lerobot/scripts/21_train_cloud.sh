#!/usr/bin/env bash
# Training on Hugging Face Jobs GPUs. SAME CLI as local, it only adds --job.target.
# It is the fast path for SmolVLA/pi0: a laptop does not compete with an A10G/A100.
# Billed per second. `hf jobs hardware` lists flavors and prices.
#
# If the dataset only exists locally, it is uploaded automatically to a PRIVATE Hub repo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; resolve_hf_user

POLICY_ARGS=(--policy.type="${POLICY_TYPE}")
[ "${POLICY_TYPE}" = "smolvla" ] && POLICY_ARGS=(--policy.path=lerobot/smolvla_base)

c_bold "launching job on ${JOB_TARGET}"
c_ylw "Ctrl-C only detaches the logs; the job KEEPS running. 'hf jobs logs <id>' to reattach."

lerobot-train \
  --dataset.repo_id="$(DATASET_REPO)" \
  "${POLICY_ARGS[@]}" \
  --job_name="${POLICY_TYPE}-${TASK_NAME}" \
  --batch_size="${CLOUD_BATCH_SIZE:-64}" \
  --steps="${STEPS}" \
  --policy.repo_id="$(POLICY_REPO)" \
  --policy.tags="${HF_TAGS}" \
  --save_checkpoint_to_hub=true \
  --wandb.enable="${WANDB:-false}" \
  --job.target="${JOB_TARGET}" \
  --job.timeout="${JOB_TIMEOUT:-4h}"

cat <<MSG

Download the trained model for local inference:
  hf download $(POLICY_REPO)
A specific intermediate checkpoint (tag = step number):
  lerobot-rollout --policy.path=$(POLICY_REPO) --policy.pretrained_revision=010000 ...
MSG
