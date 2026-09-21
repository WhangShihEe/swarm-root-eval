#!/usr/bin/env bash
# drun.sh <app> <working_limit> <iter> [wall_ceiling]  — one DEPTH trial (sequential).
# Uses Inspect --working-limit (real working-time budget, immune to 429 backoff) plus a
# generous --time-limit wall ceiling so a heavily-throttled run can't spin forever.
# Logs to launch/<app>.iter<iter>.log; appends DONE to depth.log for the monitor.
set -u
app="$1"; wl="${2:-600}"; iter="${3:-2}"; wall="${4:-4200}"
ROOT=/Users/whangshihee/swarm-root-eval
cd "$ROOT" || exit 2
source bin/env.sh >/dev/null 2>&1
export POOL_CAP=3
MODEL="openai-api/litellm/bedrock-claude-opus-4.8"
LOG="$ROOT/.scratch/single-agent-sweep/launch/${app}.iter${iter}.log"
DLOG="$ROOT/.scratch/single-agent-sweep/depth.log"
echo "=== DEPTH launch app=$app wl=$wl wall=$wall iter=$iter start=$(date -u +%FT%TZ) ===" > "$LOG"
echo "LAUNCH $app iter=$iter wl=$wl wall=$wall at=$(date -u +%FT%TZ)" >> "$DLOG"
cd "$ROOT/swarm-eval" || exit 2
uv run python single_agent.py "devices/${app}.yaml" --model "$MODEL" \
    --working-limit "$wl" --time-limit "$wall" >> "$LOG" 2>&1
rc=$?
echo "=== end app=$app rc=$rc finish=$(date -u +%FT%TZ) ===" >> "$LOG"
echo "DONE $app iter=$iter rc=$rc at=$(date -u +%FT%TZ)" >> "$DLOG"
