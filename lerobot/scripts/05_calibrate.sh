#!/usr/bin/env bash
# Calibrate one arm. The id determines the calibration file: ALWAYS use the same id
# in calibrate / teleoperate / record / rollout, or the trained policy does not transfer.
#
# Procedure: 1) move the arm to the middle of every joint's range, Enter.
#            2) move each joint through its FULL range. Enter.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv

ARM="${1:-}"
case "${ARM}" in
  follower)
    require_ports
    lerobot-calibrate --robot.type=so101_follower --robot.port="${FOLLOWER_PORT}" --robot.id="${FOLLOWER_ID}"
    ;;
  leader)
    require_leader_port
    lerobot-calibrate --teleop.type=so101_leader --teleop.port="${LEADER_PORT}" --teleop.id="${LEADER_ID}"
    ;;
  *) die "usage: $0 follower|leader" ;;
esac

c_grn "calibration saved. A backup is recommended:"
echo "  cp -r ~/.cache/huggingface/lerobot/calibration ${ROOT}/data/calibration-backup"
