#!/usr/bin/env bash
# Hermetic tests for ticket 06 (broker service — bin/_broker.sh + bin/broker).
# No network, no real emulator/adb: the pool engine's bring-up/teardown are injected as fakes
# (POOL_ENV_UP/POOL_ENV_DOWN), so we exercise the request dispatch, cap-relay, launch-profile
# gate, the file-backed queue transport, and the full start→request→stop lifecycle against a
# REAL background broker process — all without booting anything. The live grant path is
# `bin/broker demo` against a real device.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

export HARNESS_ROOT="$ROOT"
SANDBOX="$(mktemp -d)"; trap 'rm -rf "$SANDBOX"' EXIT
export POOL_DIR="$SANDBOX/pool"
export BROKER_DIR="$SANDBOX/broker"
# Snappy timings so the lifecycle test doesn't dawdle (fakes answer instantly).
export BROKER_POLL=0.05 BROKER_CLIENT_POLL=0.05 BROKER_CLIENT_TIMEOUT=20

# --- fakes: stand in for bin/env-up and bin/env-down (same shape as tests/pool.sh) --------
FAKEBIN="$SANDBOX/bin"; mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/env-up" <<'EOF'
#!/usr/bin/env bash
port=5554 ; profile=writable-system   # env-up's default when honoring the spec (ticket 07)
while [ $# -gt 0 ]; do case "$1" in
  --port) port=$2; shift 2 ;; --port=*) port=${1#--port=}; shift ;;
  --writable-system) profile=writable-system; shift ;;
  --frida-only) profile=frida-only; shift ;;
  --profile) profile=$2; shift 2 ;; --profile=*) profile=${1#--profile=}; shift ;;
  *) shift ;;
esac; done
# Report the resolved profile like real env-up (ticket 08) so the pool can record it.
[ -n "${ENVUP_PROFILE_OUT:-}" ] && printf '%s\n' "$profile" > "$ENVUP_PROFILE_OUT"
[ "${FAKE_UP_DELAY:-0}" != 0 ] && sleep "$FAKE_UP_DELAY"   # stand in for a slow cold boot
[ "${FAKE_UP_FAIL:-0}" = 1 ] && { echo "fake env-up: forced failure" >&2; exit 1; }
printf 'emulator-%s\n' "$port"
EOF
cat > "$FAKEBIN/env-down" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$FAKEBIN/env-up" "$FAKEBIN/env-down"
export POOL_ENV_UP="$FAKEBIN/env-up" POOL_ENV_DOWN="$FAKEBIN/env-down"

# shellcheck source=/dev/null
. "$ROOT/bin/_pool.sh"
# shellcheck source=/dev/null
. "$ROOT/bin/_broker.sh"

SPEC="$ROOT/devices/rootbeer.yaml"   # any path; the fake env-up never reads it
reset() { rm -rf "$POOL_DIR" "$BROKER_DIR"; }

# with_timeout SECS cmd… — run cmd with a watchdog (macOS has no `timeout(1)`). Returns the
# command's rc, or 124 if the watchdog had to kill it (i.e. it hung).
with_timeout() {
  local secs=$1; shift
  "$@" & local cmd_pid=$!
  ( sleep "$secs"; kill -9 "$cmd_pid" 2>/dev/null ) & local dog=$!
  local rc=0; wait "$cmd_pid" 2>/dev/null || rc=$?
  kill "$dog" 2>/dev/null; wait "$dog" 2>/dev/null || true
  [ "$rc" -ge 128 ] && rc=124   # killed by the watchdog signal
  return "$rc"
}

# mk_req REQDIR VERB [args…] — write a queue request file the way a client would.
mk_req() {
  local rd=$1 verb=$2; shift 2
  mkdir -p "$rd"
  { printf '%s\n' "$verb"; [ $# -gt 0 ] && printf '%s\n' "$@"; } > "$rd/req"
}

echo "== launch profiles: known / no default override / the override gate (ticket 08) =="
check "frida-only is valid"        "$(broker_valid_profile frida-only     && echo y || echo n)" "y"
check "writable-system is valid"   "$(broker_valid_profile writable-system && echo y || echo n)" "y"
check "bogus profile invalid"      "$(broker_valid_profile bogus           && echo y || echo n)" "n"
# The broker owns no default profile now — an empty override means "honor each spec".
check "no default override"        "$BROKER_PROFILE_OVERRIDE" ""
check "empty override passes gate" "$(broker_profile_gate ""             2>/dev/null && echo y || echo n)" "y"
check "known override passes gate" "$(broker_profile_gate writable-system 2>/dev/null && echo y || echo n)" "y"
check "bogus override fails gate"  "$(broker_profile_gate bogus           2>/dev/null && echo y || echo n)" "n"
# policy label: per-spec when no override profile file exists.
check "policy label per-spec"      "$(BROKER_DIR="$SANDBOX/no-such" broker_policy_label)" "per-spec"

echo "== dispatch: acquire writes a contract with the real profile + registers a slot =="
reset
_BROKER_STOP=0
RD="$BROKER_DIR/queue/t-acq"; mk_req "$RD" acquire "$SPEC"
POOL_CAP=3 broker_handle "$RD"
check "acquire rc 0"      "$(cat "$RD/rc")"   "0"
# No override set, so the grant honors the spec — the fake env-up resolves writable-system.
check "acquire contract"  "$(cat "$RD/resp")" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"
check "one slot in pool"  "$(pool_count)"     "1"

echo "== dispatch: acquire with no spec is refused (rc 2) =="
reset
RD="$BROKER_DIR/queue/t-nospec"; mk_req "$RD" acquire
broker_handle "$RD"
check "no-spec rc 2"   "$(cat "$RD/rc")" "2"
check "no slot made"   "$(pool_count)"  "0"

echo "== dispatch: cap is enforced by the broker, not the caller (2nd acquire refused) =="
reset
RD1="$BROKER_DIR/queue/t-cap1"; mk_req "$RD1" acquire "$SPEC"
RD2="$BROKER_DIR/queue/t-cap2"; mk_req "$RD2" acquire "$SPEC"
POOL_CAP=1 broker_handle "$RD1"
POOL_CAP=1 broker_handle "$RD2"
check "1st grant rc 0"       "$(cat "$RD1/rc")" "0"
check "2nd grant refused rc 3" "$(cat "$RD2/rc")" "3"
check "still one slot"       "$(pool_count)"   "1"
grep -q "full" "$RD2/resp" && ok "refusal explains the pool is full" || bad "refusal reason: $(cat "$RD2/resp")"

echo "== dispatch: release tears down + deregisters =="
reset
RD="$BROKER_DIR/queue/t-up"; mk_req "$RD" acquire "$SPEC"; POOL_CAP=3 broker_handle "$RD"
RR="$BROKER_DIR/queue/t-rel"; mk_req "$RR" release emulator-5554; broker_handle "$RR"
check "release rc 0"      "$(cat "$RR/rc")"   "0"
check "release message"   "$(cat "$RR/resp")" "released emulator-5554"
check "registry clean"    "$(pool_count)"     "0"

echo "== dispatch: status / list / ping / shutdown / unknown =="
reset
RD="$BROKER_DIR/queue/t-s1"; mk_req "$RD" acquire "$SPEC"; POOL_CAP=3 broker_handle "$RD"
RS="$BROKER_DIR/queue/t-stat"; mk_req "$RS" status; broker_handle "$RS"
grep -q "1/3 in use" "$RS/resp" && ok "status shows 1/3 in use" || bad "status: $(cat "$RS/resp")"
RL="$BROKER_DIR/queue/t-list"; mk_req "$RL" list; broker_handle "$RL"
check "list shows the port" "$(cat "$RL/resp")" "5554"
# An empty pool is success, not an error, even under pipefail (pool_list's trailing grep rc 1).
reset
RLE="$BROKER_DIR/queue/t-liste"; mk_req "$RLE" list; broker_handle "$RLE"
check "empty list rc 0"    "$(cat "$RLE/rc")"   "0"
check "empty list is blank" "$(cat "$RLE/resp")" ""
RD="$BROKER_DIR/queue/t-s1"; mk_req "$RD" acquire "$SPEC"; POOL_CAP=3 broker_handle "$RD"
RP="$BROKER_DIR/queue/t-ping"; mk_req "$RP" ping; broker_handle "$RP"
# No override configured for this dispatch test, so ping reports the per-spec policy.
grep -q "^pong .*profile=per-spec" "$RP/resp" && ok "ping reports the profile policy" || bad "ping: $(cat "$RP/resp")"
_BROKER_STOP=0
RH="$BROKER_DIR/queue/t-sd"; mk_req "$RH" shutdown; broker_handle "$RH"
check "shutdown sets stop flag" "$_BROKER_STOP" "1"
check "shutdown resp"           "$(cat "$RH/resp")" "bye"
RU="$BROKER_DIR/queue/t-unk"; mk_req "$RU" flibble; broker_handle "$RU"
check "unknown verb rc 2" "$(cat "$RU/rc")" "2"

echo "== dispatch: bring-up failure is relayed as a refusal, slot reclaimed =="
reset
RD="$BROKER_DIR/queue/t-fail"; mk_req "$RD" acquire "$SPEC"
FAKE_UP_FAIL=1 POOL_CAP=3 broker_handle "$RD"
check "bring-up failure rc 5" "$(cat "$RD/rc")" "5"
check "no slot left behind"   "$(pool_count)"   "0"

echo "== client: a request against a stopped broker fails fast (rc 66) =="
reset
broker_request ping >/dev/null 2>&1; check "not-running rc 66" "$?" "66"

echo "== lifecycle: start → ping → acquire → release → stop, cross-process =="
reset
"$ROOT/bin/broker" start >/dev/null 2>&1; rc=$?
check "start rc 0"        "$rc" "0"
check "broker is running" "$(broker_running && echo y || echo n)" "y"
"$ROOT/bin/broker" ping >/dev/null 2>&1; check "ping rc 0" "$?" "0"
c1="$("$ROOT/bin/broker" acquire --spec "$SPEC")"; rc=$?
check "acquire rc 0"     "$rc" "0"
# Default start honors the spec, so the grant is a writable-system device (fake env-up).
check "acquire contract" "$c1" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"
check "pool has 1"       "$("$ROOT/bin/broker" list | grep -c .)" "1"
"$ROOT/bin/broker" release --serial emulator-5554 >/dev/null 2>&1; check "release rc 0" "$?" "0"
check "pool clean"       "$("$ROOT/bin/broker" list | grep -c . || true)" "0"
"$ROOT/bin/broker" stop >/dev/null 2>&1
check "stopped"          "$(broker_running && echo y || echo n)" "n"
check "pidfile removed"  "$([ -e "$BROKER_DIR/broker.pid" ] && echo present || echo gone)" "gone"
check "queue removed"    "$([ -d "$BROKER_DIR/queue" ] && echo present || echo gone)" "gone"

echo "== lifecycle: cap-full acquire returns a clean refusal over the wire (rc 3) =="
reset
POOL_CAP=1 "$ROOT/bin/broker" start >/dev/null 2>&1
"$ROOT/bin/broker" acquire --spec "$SPEC" >/dev/null 2>&1; check "1st acquire rc 0" "$?" "0"
out="$("$ROOT/bin/broker" acquire --spec "$SPEC" 2>/dev/null)"; rc=$?
check "2nd acquire rc 3" "$rc" "3"
grep -q "full" <<<"$out" && ok "wire refusal explains full pool" || bad "refusal: $out"
"$ROOT/bin/broker" stop >/dev/null 2>&1

echo "== start --profile writable-system now starts (wired, ticket 08); bogus still rc 2 =="
reset
"$ROOT/bin/broker" start --profile writable-system >/dev/null 2>&1; check "writable-system start rc 0" "$?" "0"
check "daemon running under the override" "$(broker_running && echo y || echo n)" "y"
pong="$("$ROOT/bin/broker" ping 2>/dev/null)"
grep -q "profile=writable-system" <<<"$pong" && ok "ping reports the override profile" || bad "ping: $pong"
"$ROOT/bin/broker" stop >/dev/null 2>&1
reset
"$ROOT/bin/broker" start --profile bogus >/dev/null 2>&1; check "bogus profile start rc 2" "$?" "2"
check "no daemon on bogus" "$(broker_running && echo y || echo n)" "n"

echo "== an override forces its profile across grants, reported in the contract (ticket 08) =="
reset
"$ROOT/bin/broker" start --profile frida-only >/dev/null 2>&1; check "override start rc 0" "$?" "0"
c="$("$ROOT/bin/broker" acquire --spec "$SPEC")"; rc=$?
check "acquire under override rc 0"        "$rc" "0"
check "contract shows the forced profile" "$c" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=frida-only"
pong="$("$ROOT/bin/broker" ping 2>/dev/null)"
grep -q "profile=frida-only" <<<"$pong" && ok "ping reports the forced profile" || bad "ping: $pong"
"$ROOT/bin/broker" stop >/dev/null 2>&1

echo "== a value-taking flag given no value errors, does NOT hang (bash 3.2 shift) =="
# On macOS bash 3.2 `shift 2` with one positional left is a no-op, so a naive parse loops
# forever. Each of these must return promptly (rc 2), never trip the 5s watchdog (124).
reset
with_timeout 5 "$ROOT/bin/broker" acquire --spec; check "acquire --spec <eol> rc 2" "$?" "2"
with_timeout 5 "$ROOT/bin/broker" release --serial; check "release --serial <eol> rc 2" "$?" "2"
with_timeout 5 "$ROOT/bin/broker" start --profile; check "start --profile <eol> rc 2" "$?" "2"
# both spellings of an empty --profile are a typo, not "no override" (that is omitting the flag).
with_timeout 5 "$ROOT/bin/broker" start --profile=; check "start --profile= (empty) rc 2" "$?" "2"

echo "== a client that gives up mid-acquire does not orphan the device (auto-release) =="
# Slow the fake boot to 2s and give the client a 1s timeout: it times out and removes its
# request dir while the daemon is still 'booting'. When the daemon finishes it must notice the
# abandonment and release the device it granted, so no slot is leaked.
reset
FAKE_UP_DELAY=2 "$ROOT/bin/broker" start >/dev/null 2>&1
BROKER_CLIENT_TIMEOUT=1 "$ROOT/bin/broker" acquire --spec "$SPEC" >/dev/null 2>&1; rc=$?
check "client acquire times out (rc 68)" "$rc" "68"
# Wait past the boot delay so the daemon completes the acquire and runs its abandonment release.
sleep 3
check "abandoned device auto-released" "$("$ROOT/bin/broker" list | grep -c . || true)" "0"
"$ROOT/bin/broker" stop >/dev/null 2>&1

echo "== a second daemon on the same BROKER_DIR refuses (atomic pidfile claim) =="
# A live pidfile means another broker already owns this dir; broker_serve must refuse rather
# than clobber it (which would leave two untracked daemons owning one pool).
reset
mkdir -p "$BROKER_DIR"
printf '%s\n' "$$" > "$BROKER_DIR/broker.pid"     # a live pid (this test process) owns it
with_timeout 5 broker_serve frida-only >/dev/null 2>&1; check "second serve refused (rc 1)" "$?" "1"
check "live pidfile untouched" "$(cat "$BROKER_DIR/broker.pid")" "$$"
rm -f "$BROKER_DIR/broker.pid"

echo "== no Inspect framework import anywhere in the harness (bin/) =="
# Scope to bin/ — that IS the harness (tests/ names the forbidden tokens on purpose, here).
# The plain verb "inspect" (a comment in _pool.sh) is fine; only a framework import/proxy is not.
if grep -rniE 'inspect_ai|sandbox_agent_bridge|from[[:space:]]+inspect|import[[:space:]]+inspect' "$ROOT/bin" >/dev/null 2>&1; then
  bad "found an Inspect framework reference in bin/"
else
  ok "no Inspect import in bin/"
fi

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
