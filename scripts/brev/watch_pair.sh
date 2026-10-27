#!/usr/bin/env bash
# Usage: [PYTHON=<python with huggingface_hub>] [STEP=040000] watch_pair.sh <host> <model repo>...
# Watches a train_pair.sh / train_two.sh box and always ends by deleting it, so a GPU never bills idle:
#  - all runs done and every repo has its final checkpoint on the Hub -> delete (exit 0)
#  - a run or the setup failed, training stalled, or the box is unreachable -> save the logs locally, delete (exit 1)
#  - the Brev CLI session expired -> exit 3 "LOGIN NEEDED" without deleting; log in again and rerun this script.
# Tunables: STALL_MIN (no new training step for this long, default 20), FIRST_STEP_MIN (no step yet, default 40).
PY="${PYTHON:-python3}"  # needs huggingface_hub, e.g. PYTHON=backend/.venv/bin/python
HOST="$1"; shift; REPOS="$*"; STEP="${STEP:-040000}"
STALL_MIN="${STALL_MIN:-20}"; FIRST_STEP_MIN="${FIRST_STEP_MIN:-40}"
LOGS="${LOGS:-$HOME/brev-logs/$HOST-$(date +%Y%m%d-%H%M)}"
miss=0; elapsed=0; last_steps=""; still=0
caffeinate -i -w $$ &

save_logs() {
  mkdir -p "$LOGS"
  for f in setup.log $(ssh -o ConnectTimeout=20 "$HOST" 'cd ~ && ls train-*.log 2>/dev/null' 2>/dev/null); do
    ssh -o ConnectTimeout=20 "$HOST" "cat ~/$f" > "$LOGS/$f" 2>/dev/null
  done
  echo "logs saved to $LOGS"
}

delete_box() {  # exit code
  if brev ls </dev/null 2>&1 | grep -q 'logged out'; then
    echo "LOGIN NEEDED: Brev session expired, $HOST is still running. Run 'brev login', then rerun this script."
    exit 3
  fi
  yes | brev delete "$HOST"
  for _ in $(seq 1 20); do
    brev ls </dev/null 2>&1 | grep -E "^ *$HOST " | grep -qv DELETING || { echo "DELETED (or DELETING) $HOST $(date +%H:%M)"; exit "$1"; }
    /bin/sleep 15
  done
  echo "DELETE NOT CONFIRMED for $HOST: check 'brev ls'"; exit 4
}

while :; do
  st=$(ssh -o ConnectTimeout=20 "$HOST" 'ls ~ | grep -E "^(DONE-|FAILED-|TRAIN_DONE)" | tr "\n" " "' 2>/dev/null) || st=UNREACHABLE
  case "$st" in
    UNREACHABLE)
      miss=$((miss+1))
      [ $miss -ge 10 ] && { echo "UNREACHABLE: no connection to $HOST for 10 min"; delete_box 1; };;
    *FAILED-setup*|*TRAIN_DONE*FAILED-*|*FAILED-*TRAIN_DONE*)
      # Setup failed, or every run ended and at least one failed. A single failed run while the other still trains
      # falls through to the progress check below, which deletes the box if that run stalls.
      echo "FAILED on $HOST $(date +%H:%M): $st"; save_logs
      ssh "$HOST" 'for f in ~/setup.log ~/train-*.log; do echo "== $f"; tail -c 1500 "$f" | tr "\r" "\n" | tail -15; done' 2>/dev/null
      delete_box 1;;
    *TRAIN_DONE*) echo "TRAIN_DONE $HOST $(date +%H:%M): $st"; break;;
    *)
      miss=0
      steps=$(ssh -o ConnectTimeout=20 "$HOST" 'for f in ~/train-*.log; do [ -f "$f" ] && tr "\r" "\n" < "$f" | grep -o "step:[0-9.]*K*" | tail -1; done | tr "\n" " "' 2>/dev/null)
      if [ -z "$steps" ]; then
        [ $elapsed -ge "$FIRST_STEP_MIN" ] && { echo "NO TRAINING STEP after $elapsed min on $HOST"; save_logs; delete_box 1; }
      elif [ "$steps" = "$last_steps" ]; then
        still=$((still+1))
        [ $still -ge "$STALL_MIN" ] && { echo "STALLED at '$steps' for $still min on $HOST"; save_logs; delete_box 1; }
      else
        [ -z "$last_steps" ] && echo "TRAINING STARTED on $HOST $(date +%H:%M): $steps"
        still=0; last_steps="$steps"
      fi;;
  esac
  elapsed=$((elapsed+1))
  /bin/sleep 60
done

save_logs
if "$PY" -c "
from huggingface_hub import HfApi
for r in '$REPOS'.split():
    f = {s.rfilename for s in HfApi().model_info(r).siblings}
    assert 'model.safetensors' in f and 'checkpoints/$STEP/pretrained_model/model.safetensors' in f, r
print('hub ok')"; then
  delete_box 0
else
  # The weights may still be uploading; give the Hub a few minutes, then delete anyway (the logs are saved).
  /bin/sleep 300
  "$PY" -c "
from huggingface_hub import HfApi
for r in '$REPOS'.split():
    assert 'model.safetensors' in {s.rfilename for s in HfApi().model_info(r).siblings}, r
print('hub ok after retry')" || echo "HUB NOT VERIFIED: deleting $HOST anyway, logs in $LOGS"
  delete_box 0
fi
