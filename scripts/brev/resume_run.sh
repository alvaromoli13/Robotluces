#!/usr/bin/env bash
# Runs on the Brev box (started by auto_train.sh in tmux): resumes one ACT run from its last local checkpoint with a
# higher total step count. Same output dir, same Hub repo, so checkpoints keep being pushed to checkpoints/<step>.
# Usage: resume_run.sh <model name> <total steps>      (model name as in train_two.sh, output dir act-<name>)
# Writes DONE-<name> / FAILED-<name> like train_two.sh; the training log is appended to ~/train-<name>.log.
set -uo pipefail
NAME="$1"; STEPS="$2"
OUT="$HOME/outputs/train/act-$NAME"
export PATH="$HOME/.local/bin:$PATH"
rm -f "$HOME/DONE-$NAME" "$HOME/FAILED-$NAME"
cfg="$OUT/checkpoints/last/pretrained_model/train_config.json"
[ -f "$cfg" ] || { echo "== $(date) no checkpoint to resume: $cfg" >> "$HOME/train-$NAME.log"; touch "$HOME/FAILED-$NAME"; exit 1; }
cd "$HOME/lerobot" && . .venv/bin/activate && cd "$HOME" || { touch "$HOME/FAILED-$NAME"; exit 1; }
echo "== $(date) resume $NAME to $STEPS steps" >> "$HOME/train-$NAME.log"
lerobot-train --config_path="$cfg" --resume=true --steps="$STEPS" >> "$HOME/train-$NAME.log" 2>&1 \
  && touch "$HOME/DONE-$NAME" || touch "$HOME/FAILED-$NAME"
