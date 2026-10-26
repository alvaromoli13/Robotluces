#!/usr/bin/env bash
# Shared by every script: loads .env, activates the venv, builds the camera config.
# Do not run directly; it is `source`d.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
LEROBOT_SRC="${ROOT}/vendor/lerobot"

c_red()  { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }
c_bold() { printf '\033[1m%s\033[0m\n' "$*"; }

die() { c_red "ERROR: $*"; exit 1; }

load_env() {
  [ -f "${ROOT}/.env" ] || die "missing ${ROOT}/.env — copy .env.example to .env and fill it in"
  # Variables given on the command line (VAR=x ./script) win over .env.
  local key overrides=""
  for key in $(sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' "${ROOT}/.env"); do
    if [ -n "${!key+x}" ]; then overrides+="${key}=$(printf '%q' "${!key}"); "; fi
  done
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  eval "${overrides}"
  set +a
}

activate_venv() {
  [ -d "${VENV}" ] || die "no venv — run scripts/00_install.sh"
  # shellcheck disable=SC1091
  . "${VENV}/bin/activate"
  # Another `hf` binary elsewhere on PATH can collide with the one from huggingface_hub.
  # Activating the venv puts its bin/ first on PATH; check that the right one is used.
  if ! hf auth whoami >/dev/null 2>&1; then
    if [ "$(command -v hf)" != "${VENV}/bin/hf" ]; then
      c_ylw "WARNING: 'hf' resolves to $(command -v hf), not the venv one. Use ${VENV}/bin/hf"
    fi
  fi
}

require_ports() {
  case "${FOLLOWER_PORT}" in *CHANGE_ME*) die "FOLLOWER_PORT not set in .env — run scripts/03_hardware.sh";; esac
  [ -e "${FOLLOWER_PORT}" ] || die "${FOLLOWER_PORT} does not exist — is the follower arm connected and powered?"
}

require_leader_port() {
  case "${LEADER_PORT}" in *CHANGE_ME*) die "LEADER_PORT not set in .env — run scripts/03_hardware.sh";; esac
  [ -e "${LEADER_PORT}" ] || die "${LEADER_PORT} does not exist — is the leader arm connected and powered?"
}

# Camera names (top / wrist) become the dataset feature names.
# They must be IDENTICAL in record and rollout or the policy cannot find its inputs.
# That is why they are generated here and not written by hand in each script.
build_cameras() {
  local cams="{ top: {type: opencv, index_or_path: ${CAM_TOP}, width: ${CAM_WIDTH}, height: ${CAM_HEIGHT}, fps: ${FPS}}"
  if [ -n "${CAM_WRIST:-}" ]; then
    cams="${cams}, wrist: {type: opencv, index_or_path: ${CAM_WRIST}, width: ${CAM_WIDTH}, height: ${CAM_HEIGHT}, fps: ${FPS}}"
  fi
  printf '%s}' "${cams}"
}

resolve_hf_user() {
  if [ -z "${HF_USER:-}" ]; then
    HF_USER="$(NO_COLOR=1 hf auth whoami 2>/dev/null | awk -F': *' 'NR==1 {print $2}')" || true
  fi
  [ -n "${HF_USER:-}" ] || die "no HF_USER — run 'hf auth login' or set it in .env"
  export HF_USER
}

DATASET_REPO() { printf '%s/%s' "${HF_USER}" "${TASK_NAME}"; }
POLICY_REPO()  { printf '%s/%s-%s' "${HF_USER}" "${POLICY_TYPE}" "${TASK_NAME}"; }
RUN_DIR()      { printf '%s/outputs/train/%s-%s' "${ROOT}" "${POLICY_TYPE}" "${TASK_NAME}"; }
