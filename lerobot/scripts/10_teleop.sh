#!/usr/bin/env bash
# Leader -> follower teleoperation with camera visualization (rerun).
# Use it to: validate the calibration, place the cameras, rehearse the task before recording.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; require_ports; require_leader_port

lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port="${FOLLOWER_PORT}" \
  --robot.id="${FOLLOWER_ID}" \
  --robot.cameras="$(build_cameras)" \
  --teleop.type=so101_leader \
  --teleop.port="${LEADER_PORT}" \
  --teleop.id="${LEADER_ID}" \
  --display_data=true
