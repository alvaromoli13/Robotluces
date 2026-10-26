#!/usr/bin/env bash
# Inference: the policy drives the robot on its own.
#   ./scripts/30_rollout.sh              -> local (outputs/.../checkpoints/last)
#   ./scripts/30_rollout.sh hub          -> downloads the policy from the Hub
#   ./scripts/30_rollout.sh <path|repo>  -> explicit local path or Hub repo id
#
# RTC (real-time chunking) smooths the execution of slow VLAs (SmolVLA, pi0).
# It is enabled only if POLICY_TYPE != act.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; require_ports; resolve_hf_user

SRC="${1:-local}"
case "${SRC}" in
  local) POLICY_PATH="$(RUN_DIR)/checkpoints/last/pretrained_model" ;;
  hub)   POLICY_PATH="$(POLICY_REPO)" ;;
  *)     POLICY_PATH="${SRC}" ;;   # explicit path or repo id
esac
[ "${SRC}" != "local" ] || [ -d "${POLICY_PATH}" ] || die "${POLICY_PATH} does not exist — have you trained yet?"

EXTRA=()
[ "${POLICY_TYPE}" != "act" ] && EXTRA+=(--inference.type=rtc)

c_bold "policy: ${POLICY_PATH}"
c_ylw "HAND ON THE POWER CABLE. First rollout = unpredictable motion."

lerobot-rollout \
  --strategy.type=base \
  --policy.path="${POLICY_PATH}" \
  --robot.type=so101_follower \
  --robot.port="${FOLLOWER_PORT}" \
  --robot.id="${FOLLOWER_ID}" \
  --robot.cameras="$(build_cameras)" \
  --task="${TASK_PROMPT}" \
  --duration="${DURATION:-60}" \
  ${EXTRA[@]+"${EXTRA[@]}"}
