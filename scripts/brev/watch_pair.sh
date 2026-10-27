#!/usr/bin/env bash
# Usage: [PYTHON=<python with huggingface_hub>] [STEP=040000] watch_pair.sh <host> <model repo>...
# Watches a train_pair.sh / train_two.sh box and deletes it once every given model repo has its final checkpoint
# on the Hub. A failed run keeps the box for inspection; a box unreachable for 10 min ends the watch.
PY="${PYTHON:-python3}"  # needs huggingface_hub, e.g. PYTHON=backend/.venv/bin/python
HOST="$1"; shift; REPOS="$*"; STEP="${STEP:-040000}"; miss=0
caffeinate -i -w $$ &
while :; do
  st=$(ssh -o ConnectTimeout=20 "$HOST" 'ls ~ | grep -E "^(DONE-|FAILED-|TRAIN_DONE)" | tr "\n" " "' 2>/dev/null) || st=UNREACHABLE
  case "$st" in
    UNREACHABLE) miss=$((miss+1)); [ $miss -ge 10 ] && { echo "UNREACHABLE: no connection to $HOST for 10 min"; exit 2; };;
    *TRAIN_DONE*)
      echo "TRAIN_DONE $HOST $(date +%H:%M): $st"
      case "$st" in *FAILED-*) echo "a run FAILED on $HOST: machine kept for inspection"
        ssh "$HOST" 'for f in ~/train-*.log; do echo "== $f"; tail -c 1500 "$f" | tr "\r" "\n" | tail -15; done' 2>/dev/null
        exit 1;; esac
      break;;
    *) miss=0;;
  esac
  /bin/sleep 60
done
if "$PY" -c "
from huggingface_hub import HfApi
for r in '$REPOS'.split():
    f = {s.rfilename for s in HfApi().model_info(r).siblings}
    assert 'model.safetensors' in f and 'checkpoints/$STEP/pretrained_model/model.safetensors' in f, r
print('hub ok')"; then
  # brev delete may wait for a confirmation; answer it so the box is not left running.
  yes | brev delete "$HOST" && echo "DELETED $HOST $(date +%H:%M)"
else
  echo "HUB NOT VERIFIED on $HOST: machine NOT deleted"
fi
