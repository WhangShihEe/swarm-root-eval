#!/usr/bin/env bash
# run.sh <app> <time_limit> <iter>  — launch one single_agent trial, log to launch/<app>.iter<iter>.log
set -u
app="$1"; tl="${2:-900}"; iter="${3:-1}"
ROOT=/Users/whangshihee/swarm-root-eval
cd "$ROOT" || exit 2
source bin/env.sh >/dev/null 2>&1
export POOL_CAP=3
MODEL="openai-api/litellm/bedrock-claude-opus-4.8"
LOG="$ROOT/.scratch/single-agent-sweep/launch/${app}.iter${iter}.log"
echo "=== launch app=$app tl=$tl iter=$iter start=$(date -u +%FT%TZ) ===" > "$LOG"
cd "$ROOT/swarm-eval" || exit 2
uv run python single_agent.py "devices/${app}.yaml" --model "$MODEL" --time-limit "$tl" >> "$LOG" 2>&1
echo "=== end app=$app rc=$? finish=$(date -u +%FT%TZ) ===" >> "$LOG"
