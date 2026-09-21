#!/usr/bin/env bash
# Breadth driver: run each apk once at --time-limit $TL, holding total device
# concurrency at $MAXCONC. The broker serves acquires one-at-a-time and FAILS on a
# full pool, so we gate every launch on `inuse < MAXCONC` and wait for the grant
# (inuse bumps) before launching the next — never two pending acquires racing.
# Emits LAUNCH/DONE/ALL_DONE lines to driver.log for the monitor to pick up.
set -u
ROOT=/Users/whangshihee/swarm-root-eval
cd "$ROOT" || exit 2
source bin/env.sh >/dev/null 2>&1
export POOL_CAP=3
MAXCONC="${MAXCONC:-2}"
TL="${TL:-900}"
ITER="${ITER:-1}"
DLOG="$ROOT/.scratch/single-agent-sweep/driver.log"
RUN="$ROOT/.scratch/single-agent-sweep/run.sh"

inuse(){ POOL_CAP=3 bin/broker status 2>/dev/null | grep -oE '[0-9]+/[0-9]+ in use' | grep -oE '^[0-9]+'; }

for app in "$@"; do
  # gate: wait for a free slot under MAXCONC
  while :; do u=$(inuse); [ -z "$u" ] && u=0; [ "$u" -lt "$MAXCONC" ] && break; sleep 10; done
  u0=$(inuse); [ -z "$u0" ] && u0=0
  echo "LAUNCH $app iter=$ITER tl=$TL at=$(date -u +%FT%TZ) inuse=$u0" >> "$DLOG"
  ( "$RUN" "$app" "$TL" "$ITER"; echo "DONE $app rc=$? at=$(date -u +%FT%TZ)" >> "$DLOG" ) &
  # wait for this acquire to consume a slot (inuse increases) before next launch,
  # or bail if the run already ended (fast failure)
  for _ in $(seq 1 120); do
    sleep 10
    u=$(inuse); [ -z "$u" ] && u=0
    [ "$u" -gt "$u0" ] && break
    grep -q "^=== end app=$app " "$ROOT/.scratch/single-agent-sweep/launch/${app}.iter${ITER}.log" 2>/dev/null && break
  done
done
wait
echo "ALL_DONE iter=$ITER at=$(date -u +%FT%TZ)" >> "$DLOG"
