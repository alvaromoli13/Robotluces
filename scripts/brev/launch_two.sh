#!/usr/bin/env bash
# Usage: launch_two.sh <host> <dataset A> <model name A> <dataset B> <model name B>
# From this Mac, on a running 2-GPU Brev box: fixes the cache permissions, uploads the Hugging Face token and
# train_two.sh (over ssh, scp fails silently on these boxes), starts training in tmux and checks it is alive.
# Then run watch_pair.sh, which deletes the box at the end.
set -euo pipefail
HOST="$1"; DS_A="$2"; NAME_A="$3"; DS_B="$4"; NAME_B="$5"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOKEN="${HF_TOKEN_FILE:-$HOME/.cache/huggingface/token}"
[ -s "$TOKEN" ] || { echo "no Hugging Face token at $TOKEN (run 'hf auth login')"; exit 1; }

# ~/.cache can be a link to a root-owned /ephemeral/cache: take it before writing the token.
ssh "$HOST" 'c=$(readlink -f ~/.cache 2>/dev/null || echo ~/.cache); sudo mkdir -p "$c" && sudo chown -R "$(id -u):$(id -g)" "$c"'
ssh "$HOST" 'umask 077; mkdir -p ~/.cache/huggingface && cat > ~/.cache/huggingface/token' < "$TOKEN"
ssh "$HOST" 'cat > ~/train_two.sh && chmod +x ~/train_two.sh' < "$HERE/train_two.sh"
ssh "$HOST" "test -s ~/.cache/huggingface/token && cmp -s ~/train_two.sh - " < "$HERE/train_two.sh" \
  || { echo "upload check failed on $HOST"; exit 1; }
ssh "$HOST" "rm -f ~/DONE-* ~/FAILED-* ~/TRAIN_DONE; tmux new -d -s train '~/train_two.sh $DS_A $NAME_A $DS_B $NAME_B'"
sleep 20
ssh "$HOST" 'tmux has-session -t train && tail -3 ~/setup.log' || { echo "tmux session died on $HOST:"; ssh "$HOST" 'tail -20 ~/setup.log'; exit 1; }
echo "launched on $HOST: act-$NAME_A, act-$NAME_B"
