#!/usr/bin/env bash
# Record the demonstration dataset and push it to the Hub.
#
# Keys while recording (terminal focused):
#   n / ->   next episode (cuts the current one)
#   r / <-   discard and re-record the current episode
#   q / ESC  finish, encode videos and upload
#
# To ADD episodes to an existing dataset you must give its FULL name, with the stamp lerobot
# added when it was created (look in ~/.cache/huggingface/lerobot/<user>/):
#   REPO=<user>/<name>_<YYYYMMDD_HHMMSS> RESUME=1 EPISODES=<how many more> ./scripts/11_record.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
. "${ROOT}/scripts/lib.sh"
load_env; activate_venv; require_ports; require_leader_port; resolve_hf_user

# lerobot 0.6 appends a _YYYYMMDD_HHMMSS stamp to every new repo_id, so a resume must name the
# stamped dataset exactly: REPO=<user>/<name>_<stamp> RESUME=1 EPISODES=<more> ./scripts/11_record.sh
# EPISODES overrides NUM_EPISODES (with --resume it is the number of episodes to add).
RESUME="${RESUME:-0}"
REPO="${REPO:-$(DATASET_REPO)}"
EPISODES="${EPISODES:-${NUM_EPISODES}}"
EXTRA=()
if [ "${RESUME}" = "1" ]; then
  EXTRA+=(--resume=true --dataset.root="${HF_LEROBOT_HOME:-${HOME}/.cache/huggingface/lerobot}/${REPO}")
fi

c_bold "dataset: ${REPO}  |  episodes: ${EPISODES}  |  task: ${TASK_PROMPT}  |  resume: ${RESUME}"

lerobot-record \
  --robot.type=so101_follower \
  --robot.port="${FOLLOWER_PORT}" \
  --robot.id="${FOLLOWER_ID}" \
  --robot.cameras="$(build_cameras)" \
  --teleop.type=so101_leader \
  --teleop.port="${LEADER_PORT}" \
  --teleop.id="${LEADER_ID}" \
  --display_data="${DISPLAY_DATA:-true}" \
  --dataset.repo_id="${REPO}" \
  --dataset.num_episodes="${EPISODES}" \
  --dataset.single_task="${TASK_PROMPT}" \
  --dataset.episode_time_s="${EPISODE_TIME_S}" \
  --dataset.reset_time_s="${RESET_TIME_S}" \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --dataset.tags="${HF_TAGS}" \
  ${EXTRA[@]+"${EXTRA[@]}"}

c_grn "dataset at https://huggingface.co/datasets/${REPO} (lerobot adds a _stamp if it is new)"
echo "visualizer: https://huggingface.co/spaces/lerobot/visualize_dataset"
