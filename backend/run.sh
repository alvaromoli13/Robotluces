#!/usr/bin/env bash
# SMARTSEED_ROBOT=sim with SMARTSEED_SIM_VIEWER=1 opens the MuJoCo window; on macOS that needs `mjpython`.
cd "$(dirname "$0")" || exit 1
py=python
[ "${SMARTSEED_SIM_VIEWER:-}" = 1 ] && py=mjpython
exec uv run "$py" -m smartseed_vision
