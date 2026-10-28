#!/usr/bin/env bash
# Eval-driven controller for a train_two.sh box (replaces watch_pair.sh when the number of steps must not be fixed).
# Usage: [PYTHON=<python with huggingface_hub + the sim deps>] auto_train.sh <host> <model repo A> <model repo B>
#   e.g. auto_train.sh my-box RafaelJaime/act-sim-black-narrow-c100 RafaelJaime/act-sim-white-narrow-c100
# Remote scope: ssh to <host> only (read logs and markers, start a resumed run, stop a run) and `brev delete <host>`.
#
# Per model, whenever a new checkpoint step is on the Hub it runs, locally and one at a time,
#   sim/eval.py --repo <repo> --color <c> --layout narrow --checkpoint <step> --episodes 30
# and logs step -> successes in sim/out/auto_train/<name>.json. sim/auto_stop.py decides (see its docstring): stop after 2
# checkpoints without a strictly higher success count, at >= 90 %, or at the 120k cap. A run that reaches its --steps limit
# and is not stopped is resumed on the box with +40k steps (resume_run.sh, lerobot --resume=true, same Hub repo).
# When both models are done it writes the best checkpoint into each Hub model card, saves the logs and deletes the box.
#
# Safety, as watch_pair.sh: delete the box on setup failure, when every run failed, no training step after FIRST_STEP_MIN,
# a step stalled for STALL_MIN, or the box unreachable for UNREACH_MIN. The Brev login is checked before any delete: if it
# expired the script waits (LOGIN_WAIT_MIN) for `brev login` and exits 3 "LOGIN NEEDED" if nobody does.
# Tunables (env): SLEEP_S=60 STALL_MIN=20 FIRST_STEP_MIN=40 UNREACH_MIN=10 START_STEPS=40000 EVAL_EPISODES=30 RSS_MAX_MB=6000
#   EVAL_RETRIES=2 LOGIN_WAIT_MIN=180 NOTIFY=1 STATE=<dir> LOGS=<dir>. State lives in files, so a restart continues.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
HOST="$1"; shift
SLEEP_S="${SLEEP_S:-60}"; STALL_MIN="${STALL_MIN:-20}"; FIRST_STEP_MIN="${FIRST_STEP_MIN:-40}"; UNREACH_MIN="${UNREACH_MIN:-10}"
START_STEPS="${START_STEPS:-40000}"; EVAL_EPISODES="${EVAL_EPISODES:-30}"; RSS_MAX_MB="${RSS_MAX_MB:-6000}"
EVAL_RETRIES="${EVAL_RETRIES:-2}"; LOGIN_WAIT_MIN="${LOGIN_WAIT_MIN:-180}"; NOTIFY="${NOTIFY:-1}"
OUT_DIR="${OUT_DIR:-$ROOT/sim/out/auto_train}"; STATE="${STATE:-$OUT_DIR/state-$HOST}"
LOGS="${LOGS:-$HOME/brev-logs/$HOST-auto-$(date +%Y%m%d-%H%M)}"
STOP="$PY $ROOT/sim/auto_stop.py"
NAMES=""; miss=0; tick=0; EVAL_PID=""; EVAL_N=""; EVAL_STEP=""; EVAL_OUT=""; marks=""
mkdir -p "$OUT_DIR" "$STATE"
command -v caffeinate >/dev/null && { caffeinate -i -w $$ & }

for repo in "$@"; do
  n="${repo##*/}"; n="${n#act-}"; NAMES="$NAMES $n"; mkdir -p "$STATE/$n"
  case "$n" in *black*) color=black;; *white*) color=white;; *) echo "cannot tell the colour of $repo"; exit 2;; esac
  [ -f "$STATE/$n/repo" ] || {
    echo "$repo" > "$STATE/$n/repo"; echo "$color" > "$STATE/$n/color"; echo running > "$STATE/$n/status"
    echo "$START_STEPS" > "$STATE/$n/limit"; echo 0 > "$STATE/$n/still"; echo 0 > "$STATE/$n/age"; echo 0 > "$STATE/$n/ended"
    echo none > "$STATE/$n/last"; echo 0 > "$STATE/$n/evalfail"; echo 0 > "$STATE/$n/failed"; }
done
[ -n "$NAMES" ] || { echo "usage: auto_train.sh <host> <repo>..."; exit 2; }

sget() { cat "$STATE/$1/$2"; }
sset() { echo "$3" > "$STATE/$1/$2"; }
log() { echo "[$(date +%H:%M:%S)] $*"; }
notify() { log "$*"; [ "$NOTIFY" = 1 ] && command -v osascript >/dev/null && osascript -e "display notification \"$*\" with title \"auto_train $HOST\"" >/dev/null 2>&1; return 0; }
jsonlog() { echo "$OUT_DIR/$1.json"; }

ssh_() { ssh -o ConnectTimeout=20 "$HOST" "$@"; }

save_logs() {
  mkdir -p "$LOGS"
  local f
  for f in setup.log $(ssh_ 'cd ~ && ls train-*.log 2>/dev/null' 2>/dev/null); do
    ssh_ "cat ~/$f" > "$LOGS/$f" 2>/dev/null
  done
  cp -R "$OUT_DIR"/*.json "$LOGS/" 2>/dev/null
  echo "logs saved to $LOGS"
}

delete_box() {  # exit code
  local waited=0
  while brev ls </dev/null 2>&1 | grep -q 'logged out'; do
    notify "LOGIN NEEDED: Brev session expired, $HOST is still running. Run 'brev login'."
    [ "$waited" -ge "$LOGIN_WAIT_MIN" ] && { echo "LOGIN NEEDED: Brev session expired, $HOST is still running. Run 'brev login', then rerun this script."; exit 3; }
    /bin/sleep 30; waited=$((waited+1)) # about 2 polls a minute
    [ "$SLEEP_S" -eq 0 ] && waited=$LOGIN_WAIT_MIN
  done
  # Plain stdin: `yes | brev delete` hung. Cap the call at 2 min.
  brev delete "$HOST" </dev/null & local pid=$!
  for _ in $(seq 1 24); do kill -0 "$pid" 2>/dev/null || break; /bin/sleep "$(( SLEEP_S > 0 ? 5 : 0 ))"; done
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 20); do
    brev ls </dev/null 2>&1 | grep -E "^ *$HOST " | grep -qv DELETING || { echo "DELETED (or DELETING) $HOST $(date +%H:%M)"; exit "$1"; }
    /bin/sleep "$(( SLEEP_S > 0 ? 15 : 0 ))"
  done
  echo "DELETE NOT CONFIRMED for $HOST: check 'brev ls'"; exit 4
}

status_cmd() {
  local n cmd='cd ~ 2>/dev/null; echo "MARKS $(ls 2>/dev/null | grep -E "^(DONE-|FAILED-)" | tr "\n" " ")"'
  for n in $NAMES; do
    cmd="$cmd"'; a=0; pgrep -f "[o]utputs/train/act-'"$n"'" >/dev/null && a=1; s=$(tr "\r" "\n" < ~/train-'"$n"'.log 2>/dev/null | grep -o "step:[0-9.]*K*" | tail -1); echo "RUN '"$n"' $a ${s:-none}"'
  done
  printf '%s' "$cmd"
}

stop_model() {  # name reason
  local n="$1"
  [ "$(sget "$n" status)" = stopped ] && return 0
  log "STOP $n: $2"
  sset "$n" status stopped; sset "$n" reason "$2"
  ssh_ "pkill -f '[o]utputs/train/act-$n'; tmux kill-session -t resume-$n 2>/dev/null; true" >/dev/null 2>&1
}

launch_resume() {  # name total steps
  local n="$1" steps="$2"
  log "RESUME $n to $steps steps"
  ssh_ 'cat > ~/resume_run.sh && chmod +x ~/resume_run.sh' < "$HERE/resume_run.sh" || return 1
  ssh_ "rm -f ~/DONE-$n ~/FAILED-$n ~/TRAIN_DONE; tmux new -d -s resume-$n '~/resume_run.sh $n $steps'" || return 1
  sset "$n" limit "$steps"; sset "$n" still 0; sset "$n" age 0; sset "$n" ended 0; sset "$n" last none
}

check_model() {  # name alive step token
  local n="$1" alive="$2" tok="$3" st tgt still
  [ "$(sget "$n" status)" = running ] || return 0
  case " $marks " in
    *" FAILED-$n "*) log "FAILED run $n"; sset "$n" status finished; sset "$n" failed 1; return 0;;
    *" DONE-$n "*)
      tgt=$($STOP resume-target "$(sget "$n" limit)")
      if [ -z "$tgt" ]; then log "$n reached the step cap"; sset "$n" status finished; return 0; fi
      launch_resume "$n" "$tgt" || { log "RESUME of $n failed to launch"; sset "$n" status finished; sset "$n" failed 1; }
      return 0;;
  esac
  if [ "$alive" = 0 ]; then
    sset "$n" ended $(( $(sget "$n" ended) + 1 ))
    if [ "$(sget "$n" ended)" -ge 3 ]; then log "run $n ended without DONE/FAILED marker"; sset "$n" status finished; sset "$n" failed 1; fi
    return 0
  fi
  sset "$n" ended 0; sset "$n" age $(( $(sget "$n" age) + 1 ))
  if [ "$tok" = none ]; then
    [ "$(sget "$n" age)" -ge "$FIRST_STEP_MIN" ] && { echo "NO TRAINING STEP after $(sget "$n" age) min for $n on $HOST"; save_logs; delete_box 1; }
  elif [ "$tok" = "$(sget "$n" last)" ]; then
    still=$(( $(sget "$n" still) + 1 )); sset "$n" still "$still"
    [ "$still" -ge "$STALL_MIN" ] && { echo "STALLED at '$tok' for $still min ($n) on $HOST"; save_logs; delete_box 1; }
  else
    sset "$n" still 0; sset "$n" last "$tok"
  fi
}

pending_for() {  # name -> pending steps
  local n="$1" steps
  steps=$($STOP hub-steps "$(sget "$n" repo)" 2>/dev/null) || return 0
  $STOP pending --log "$(jsonlog "$n")" --steps "$steps"
}

eval_children_rss_mb() {
  local kids; kids=$(pgrep -P "$EVAL_PID" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
  [ -n "$kids" ] && ps -o rss= -p "$kids" 2>/dev/null | awk '{s+=$1} END {printf "%d", s/1024}' || echo 0
}

handle_eval() {
  local n s out rc res k e dec
  if [ -n "$EVAL_PID" ]; then
    if kill -0 "$EVAL_PID" 2>/dev/null; then
      local rss; rss=$(eval_children_rss_mb)
      if [ "${rss:-0}" -gt "$RSS_MAX_MB" ]; then
        log "EVAL $EVAL_N $EVAL_STEP uses $rss MB RSS (> $RSS_MAX_MB): killing it"
        pkill -P "$EVAL_PID" 2>/dev/null; kill "$EVAL_PID" 2>/dev/null; /bin/sleep 1
      fi
      return 0
    fi
    n="$EVAL_N"; s="$EVAL_STEP"; out="$EVAL_OUT"; EVAL_PID=""
    rc=$(cat "$out.rc" 2>/dev/null || echo 1)
    res=$($STOP parse < "$out" 2>/dev/null) || res=""
    if [ -n "$res" ] && [ "$rc" = 0 ]; then
      set -- $res; k="$1"; e="$2"
      $STOP record --log "$(jsonlog "$n")" --step "$s" --successes "$k" --episodes "$e" --repo "$(sget "$n" repo)" --color "$(sget "$n" color)"
      log "EVAL $n step $s: $k/$e"
      sset "$n" evalfail 0
      dec=$($STOP decide --log "$(jsonlog "$n")")
      log "DECISION $n: $dec"
      case "$dec" in stop*) set -- $dec; stop_model "$n" "$2";; esac
    else
      sset "$n" evalfail $(( $(sget "$n" evalfail) + 1 ))
      log "EVAL $n step $s FAILED (rc $rc, attempt $(sget "$n" evalfail)): $(tail -c 300 "$out" | tr '\n' ' ')"
      [ "$(sget "$n" evalfail)" -gt "$EVAL_RETRIES" ] && stop_model "$n" eval-failed
    fi
    return 0
  fi
  for n in $NAMES; do
    [ "$(sget "$n" status)" = stopped ] && continue
    s=$(pending_for "$n" | awk '{print $1}')
    [ -n "$s" ] || continue
    EVAL_N="$n"; EVAL_STEP="$s"; EVAL_OUT="$STATE/$n/eval-$s.out"; rm -f "$EVAL_OUT.rc"
    log "EVAL start $n step $s"
    ( cd "$ROOT" && "$PY" sim/eval.py --repo "$(sget "$n" repo)" --color "$(sget "$n" color)" --layout narrow \
        --checkpoint "$s" --episodes "$EVAL_EPISODES" > "$EVAL_OUT" 2>&1; echo $? > "$EVAL_OUT.rc" ) &
    EVAL_PID=$!
    return 0
  done
}

finish() {
  local n any_failed=0 b
  for n in $NAMES; do
    [ "$(sget "$n" failed)" = 1 ] && any_failed=1
    b=$($STOP best --log "$(jsonlog "$n")" 2>/dev/null) && {
      echo "BEST $(sget "$n" repo): checkpoint $b ($(sget "$n" reason 2>/dev/null))"
      $STOP write-card --repo "$(sget "$n" repo)" --log "$(jsonlog "$n")" || echo "model card of $(sget "$n" repo) NOT updated"
    } || echo "BEST $(sget "$n" repo): no evaluated checkpoint"
  done
  save_logs
  delete_box "$any_failed"
}

log "auto_train on $HOST: $NAMES (state $STATE)"
while :; do
  st=$(ssh_ "$(status_cmd)" 2>/dev/null) || st=UNREACHABLE
  if [ "$st" = UNREACHABLE ] || [ -z "$st" ]; then
    miss=$((miss+1))
    [ $miss -ge "$UNREACH_MIN" ] && { echo "UNREACHABLE: no connection to $HOST for $miss min"; delete_box 1; }
  else
    miss=0
    marks="$(echo "$st" | sed -n 's/^MARKS //p')"
    case " $marks " in *" FAILED-setup "*) echo "SETUP FAILED on $HOST: $marks"; save_logs; delete_box 1;; esac
    while read -r kind a b c; do
      [ "$kind" = RUN ] && check_model "$a" "$b" "$c"
    done <<<"$st"
  fi
  handle_eval
  tick=$((tick+1))
  [ $((tick % 10)) -eq 0 ] && brev ls </dev/null 2>&1 | grep -q 'logged out' && notify "Brev login expired: run 'brev login' before the box is deleted"
  # A model that is not training any more is done once all its Hub checkpoints are evaluated.
  open=0
  for n in $NAMES; do
    case "$(sget "$n" status)" in
      running) open=1;;
      finished) [ -z "$EVAL_PID" ] && [ -z "$(pending_for "$n")" ] && sset "$n" status stopped && sset "$n" reason "run-ended" || open=1;;
    esac
  done
  [ "$open" = 0 ] && [ -z "$EVAL_PID" ] && finish
  /bin/sleep "$SLEEP_S"
done
