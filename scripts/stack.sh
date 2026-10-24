#!/usr/bin/env bash
# One command for the full local stack: backend (real arm + ACT) on 127.0.0.1:8000 and
# the web on http://localhost:8080/. Run it from Terminal.app: macOS grants the camera
# permission to the app that launches the process, and Unpeel does not have it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT=8000
WEB_PORT="${SMARTSEED_WEB_PORT:-8080}"

export SMARTSEED_ROBOT="${SMARTSEED_ROBOT:-real}"
export SMARTSEED_ROBOT_PORT="${SMARTSEED_ROBOT_PORT:-/dev/tty.usbmodem5B8E1124861}"

usage() {
  cat >&2 <<'EOF'
SMARTSEED_ACT_POLICIES is required: a JSON map from the bowl colour id used in the web
to the policy repo (or local path). The colour must match the seed's bowl colour, e.g.:

  SMARTSEED_ACT_POLICIES='{"red":"RafaelJaime/act-smartseed-grasp"}' scripts/stack.sh

Optional: SMARTSEED_ROBOT (real|fake, default real), SMARTSEED_ROBOT_PORT,
SMARTSEED_CAM_TOP, SMARTSEED_CAM_WRIST, SMARTSEED_WEB_PORT (default 8080).
EOF
  exit 2
}

# The ACT policies are what makes a real run useful; with the fake robot they are optional.
if [ -z "${SMARTSEED_ACT_POLICIES:-}" ] && [ "$SMARTSEED_ROBOT" = real ]; then usage; fi
[ -n "${SMARTSEED_ACT_POLICIES:-}" ] && export SMARTSEED_ACT_POLICIES

for port in "$BACKEND_PORT" "$WEB_PORT"; do
  if pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)" && [ -n "$pids" ]; then
    echo "Port $port is already in use by PID $(echo "$pids" | tr '\n' ' ')- stop it first." >&2
    exit 1
  fi
done

cat >&2 <<EOF
SmartSeed local stack (robot: $SMARTSEED_ROBOT)
  Run this from Terminal.app or VS Code, not from Unpeel: only those have camera permission.
  The arm moves for real in 'real' mode; keep the area clear and the stop button at hand.
EOF

pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$ROOT/backend/run.sh" &
pids+=("$!")
python3 -m http.server "$WEB_PORT" --bind 127.0.0.1 -d "$ROOT/web" >/dev/null &
pids+=("$!")

echo "Web:     http://localhost:$WEB_PORT/" >&2
echo "Backend: http://127.0.0.1:$BACKEND_PORT/  (Ctrl-C stops both)" >&2

# Exit as soon as either process dies, so a crashed backend does not leave a stale web.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
echo "A process exited; shutting down." >&2
