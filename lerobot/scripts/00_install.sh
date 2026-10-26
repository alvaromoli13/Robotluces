#!/usr/bin/env bash
# Full install on macOS Apple Silicon. Idempotent: safe to repeat.
# lerobot is checked out at LEROBOT_REF (default: the commit the backend and the published
# policies use). Set LEROBOT_REF=main to track upstream instead.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"

PY_VERSION=3.12
EXTRAS="${EXTRAS:-core_scripts,training,feetech,smolvla,pusht}"
LEROBOT_REF="${LEROBOT_REF:-e595b79}"

c_bold "== 1/6 system checks =="
[ "$(uname -s)" = "Darwin" ] || die "this script is for macOS"
[ "$(uname -m)" = "arm64" ] || die "Apple Silicon required (TorchCodec does not support Intel macOS)"
command -v git >/dev/null || die "git is missing"
command -v uv  >/dev/null || die "uv is missing — 'brew install uv'"

if ! command -v ffmpeg >/dev/null; then
  c_ylw "ffmpeg missing, installing with brew"
  brew install ffmpeg
fi
ffmpeg -encoders 2>/dev/null | grep -q libsvtav1 \
  || c_ylw "WARNING: ffmpeg without libsvtav1 — AV1 dataset encoding will fail. Install an ffmpeg build with SVT-AV1"

c_bold "== 2/6 python ${PY_VERSION} + venv =="
uv python install "${PY_VERSION}"
[ -d "${VENV}" ] || uv venv --python "${PY_VERSION}" "${VENV}"
PY="${VENV}/bin/python"

c_bold "== 3/6 clone lerobot @ ${LEROBOT_REF} =="
mkdir -p "${ROOT}/vendor"
if [ -d "${LEROBOT_SRC}/.git" ]; then
  git -C "${LEROBOT_SRC}" fetch --all --tags || c_ylw "fetch failed (offline?), continuing with what is there"
else
  git clone https://github.com/huggingface/lerobot.git "${LEROBOT_SRC}"
fi
git -C "${LEROBOT_SRC}" checkout "${LEROBOT_REF}" || c_ylw "checkout failed (local changes?), continuing with what is there"

c_bold "== 4/6 install lerobot [${EXTRAS}] =="
# Editable install from source: lets you read/patch the code.
( cd "${LEROBOT_SRC}" && uv pip install --python "${PY}" -e ".[${EXTRAS}]" )

c_bold "== 5/6 extra tools =="
uv pip install --python "${PY}" huggingface_hub wandb

c_bold "== 6/6 verification =="
"${PY}" "${ROOT}/scripts/01_verify.py" || true

cat <<'MSG'

Next steps:
  1. source .venv/bin/activate
  2. hf auth login                  # token with WRITE permission
  3. wandb login                    # optional
  4. ./scripts/02_prefetch.sh       # download weights up front
  5. ./scripts/99_smoke_sim.sh      # training smoke test without a robot
MSG
