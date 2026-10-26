#!/usr/bin/env bash
# Usage: [PYTHON=<python with huggingface_hub>] watch_one.sh <host> <repo> <final step>. Deletes the box once the final checkpoint is on the Hub.
# A failed run keeps the box for inspection; a box that stays unreachable for 10 min ends the watch.
PY="${PYTHON:-python3}"  # needs huggingface_hub, e.g. PYTHON=backend/.venv/bin/python
HOST="$1"; REPO="$2"; STEP="$3"; miss=0
caffeinate -i -w $$ &
while :; do
  st=$(ssh -o ConnectTimeout=20 "$HOST" 'ls ~ | grep -E "^(DONE|FAILED)$" | tr "\n" " "' 2>/dev/null) || st=UNREACHABLE
  case "$st" in
    *FAILED*) echo "FAILED on $HOST"; ssh "$HOST" 'tail -c 1500 ~/train.log' 2>/dev/null | tr '\r' '\n' | tail -20; exit 1;;
    *DONE*) echo "DONE $HOST $(date +%H:%M)"; break;;
    UNREACHABLE) miss=$((miss+1)); [ $miss -ge 10 ] && { echo "UNREACHABLE: no connection to $HOST for 10 min"; exit 2; };;
    *) miss=0;;
  esac
  /bin/sleep 60
done
if "$PY" -c "
from huggingface_hub import HfApi
f = {s.rfilename for s in HfApi().model_info('$REPO').siblings}
assert 'model.safetensors' in f and 'checkpoints/$STEP/pretrained_model/model.safetensors' in f
print('hub ok')"; then
  brev delete "$HOST" && echo "DELETED $HOST $(date +%H:%M)"
else
  echo "HUB NOT VERIFIED on $HOST: machine NOT deleted"
fi
