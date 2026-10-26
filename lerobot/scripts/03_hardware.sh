#!/usr/bin/env bash
# Discover serial ports and cameras. Copy the values to .env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
activate_venv

c_bold "== serial ports currently visible =="
ls -1 /dev/tty.usbmodem* /dev/tty.usbserial* 2>/dev/null || c_ylw "none — connect USB + POWER to the board"

cat <<'MSG'

To tell WHICH port is each arm, lerobot asks you to unplug one:
  lerobot-find-port
Repeat for the other arm. Write both down in .env
(FOLLOWER_PORT / LEADER_PORT).

MSG

read -r -p "Run lerobot-find-port now? [y/N] " ans
[ "${ans:-n}" = "y" ] && lerobot-find-port

c_bold "== cameras =="
echo "Detecting (takes a few seconds, opens every device)..."
lerobot-find-cameras opencv || c_ylw "camera detection failed — check Camera permission in System Settings"

cat <<'MSG'

Write the camera ids in .env (CAM_TOP / CAM_WRIST).
Note: indices CHANGE after a reboot or re-plug. Re-check every session.

Tips:
  - An iPhone works as an extra camera through Continuity Camera (same Apple ID,
    macOS 13+/iOS 16+). It shows up as one more OpenCV camera.
  - macOS asks for Camera permission the first time. Grant it to the Terminal.
MSG
