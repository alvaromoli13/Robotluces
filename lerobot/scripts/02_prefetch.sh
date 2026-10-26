#!/usr/bin/env bash
# Pre-download EVERYTHING that is fetched from the internet on first use.
# Run it on a good connection; event wifi is usually a bottleneck.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
activate_venv

WITH_PI0="${WITH_PI0:-0}"   # WITH_PI0=1 also downloads pi0 (~7 GB)

c_bold "== policy weights =="
# SmolVLA: the base checkpoint that is fine-tuned.
hf download lerobot/smolvla_base
# VLM backbone that SmolVLA loads separately in some versions.
hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct || c_ylw "SmolVLM2 not downloaded (may not be needed)"

if [ "${WITH_PI0}" = "1" ]; then
  hf download lerobot/pi0 || c_ylw "pi0 failed — it needs the [pi] extra"
fi

c_bold "== ACT vision backbone =="
# ACT trains from scratch but uses an ImageNet-pretrained ResNet18 that torchvision
# downloads from download.pytorch.org on the first train. Without this, the first
# `lerobot-train` sits waiting for the network.
python - <<'PY'
import torchvision
weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
torchvision.models.resnet18(weights=weights)
print("resnet18 ImageNet cached in ~/.cache/torch/hub/checkpoints")
PY

c_bold "== example dataset (for the smoke test and as a reference) =="
hf download lerobot/svla_so101_pickplace --repo-type dataset \
  || c_ylw "example dataset not downloaded (not critical)"

c_bold "== done =="
du -sh ~/.cache/huggingface ~/.cache/torch 2>/dev/null || true
