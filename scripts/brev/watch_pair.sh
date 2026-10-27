#!/usr/bin/env bash
# Usage: [PYTHON=<python with huggingface_hub>] watch_pair.sh <host> <model name prefix> [final step]
# Watches a train_pair.sh box and deletes it once both act-<prefix>-c100 and -c50 have their final checkpoint
# on the Hub. A failed run keeps the box for inspection; a box unreachable for 10 min ends the watch.
PY="${PYTHON:-python3}"  # needs huggingface_hub, e.g. PYTHON=backend/.venv/bin/python
HOST="$1"; NAME="$2"; STEP="${3:-040000}"; HF_USER="${HF_USER:-RafaelJaime}"; miss=0
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
for v in ('c100', 'c50'):
    f = {s.rfilename for s in HfApi().model_info('$HF_USER/act-$NAME-' + v).siblings}
    assert 'model.safetensors' in f and 'checkpoints/$STEP/pretrained_model/model.safetensors' in f, v
print('hub ok')"; then
  # brev delete may wait for a confirmation; answer it so the box is not left running.
  yes | brev delete "$HOST" && echo "DELETED $HOST $(date +%H:%M)"
else
  echo "HUB NOT VERIFIED on $HOST: machine NOT deleted"
fi
