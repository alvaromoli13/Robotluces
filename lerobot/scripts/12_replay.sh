#!/usr/bin/env bash
# Replay a recorded episode on the follower. Mechanical repeatability test:
# if the replay does not reproduce the motion, the problem is hardware/calibration, not the policy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; require_ports; resolve_hf_user

EPISODE="${1:-0}"
lerobot-replay \
  --robot.type=so101_follower \
  --robot.port="${FOLLOWER_PORT}" \
  --robot.id="${FOLLOWER_ID}" \
  --dataset.repo_id="$(DATASET_REPO)" \
  --dataset.episode="${EPISODE}"
