#!/usr/bin/env bash
# Assign id and baudrate to each STS3215 motor. This writes the EEPROM: ONLY ONCE per arm.
# If the arms come already assembled, this is ALREADY DONE. Do not repeat it without a reason.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv

ARM="${1:-}"
case "${ARM}" in
  follower) require_ports;      lerobot-setup-motors --robot.type=so101_follower --robot.port="${FOLLOWER_PORT}" ;;
  leader)   require_leader_port; lerobot-setup-motors --teleop.type=so101_leader  --teleop.port="${LEADER_PORT}" ;;
  *) die "usage: $0 follower|leader" ;;
esac
