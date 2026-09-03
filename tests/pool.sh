#!/usr/bin/env bash
# Hermetic tests for ticket 05 (pool engine — bin/_pool.sh).
# No network, no real emulator/adb: the bring-up/teardown commands are injected as fakes
# (POOL_ENV_UP/POOL_ENV_DOWN) so we exercise port allocation, the file-backed registry,
# cap enforcement, status transitions, and the acquire/release flow end-to-end without
# booting anything. The live bring-up is covered by `bin/pool demo` against a real device.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

# A sandbox POOL_DIR per run, and HARNESS_ROOT so default command paths resolve.
export HARNESS_ROOT="$ROOT"
POOL_ROOT="$(mktemp -d)"; trap 'rm -rf "$POOL_ROOT"' EXIT
export POOL_DIR="$POOL_ROOT/pool"

# --- fakes: stand in for bin/env-up and bin/env-down -------------------------------------
# fake env-up: parse --port/--spec, echo the serial env-up would (emulator-<port>) on
# stdout, and record what the engine passed (env + args) to $FAKE_LOG so tests can assert
# the isolated ANDROID_AVD_HOME + explicit port. Also records the slot status it observed
# mid-bring-up to $FAKE_STATUS (proves the slot is registered 'building' before boot).
FAKEBIN="$POOL_ROOT/bin"; mkdir -p "$FAKEBIN"
export FAKE_LOG="$POOL_ROOT/envup.log"
export FAKE_STATUS="$POOL_ROOT/envup.status"
cat > "$FAKEBIN/env-up" <<'EOF'
#!/usr/bin/env bash
port= ; spec= ; profile=writable-system   # env-up's default when honoring the spec (ticket 07)
while [ $# -gt 0 ]; do case "$1" in
  --port) port=$2; shift 2 ;; --port=*) port=${1#--port=}; shift ;;
  --spec) spec=$2; shift 2 ;; --spec=*) spec=${1#--spec=}; shift ;;
  --writable-system) profile=writable-system; shift ;;
  --frida-only) profile=frida-only; shift ;;
  --profile) profile=$2; shift 2 ;; --profile=*) profile=${1#--profile=}; shift ;;
  *) shift ;;
esac; done
printf 'ARGS port=%s spec=%s avd_home=%s profile=%s\n' "$port" "$spec" "${ANDROID_AVD_HOME:-}" "$profile" >> "$FAKE_LOG"
# Report the resolved profile like real env-up (ticket 08) so the engine can record it.
[ -n "${ENVUP_PROFILE_OUT:-}" ] && printf '%s\n' "$profile" > "$ENVUP_PROFILE_OUT"
# Peek at the registry mid-bring-up: the engine should have written status=building.
if [ -n "${POOL_DIR:-}" ] && [ -f "$POOL_DIR/slots/$port" ]; then
  sed -n 's/^status=//p' "$POOL_DIR/slots/$port" >> "$FAKE_STATUS"
fi
[ "${FAKE_UP_FAIL:-0}" = 1 ] && { echo "fake env-up: forced failure" >&2; exit 1; }
printf 'emulator-%s\n' "$port"
EOF
cat > "$FAKEBIN/env-down" <<'EOF'
#!/usr/bin/env bash
port= ; spec=
while [ $# -gt 0 ]; do case "$1" in
  --port) port=$2; shift 2 ;; --port=*) port=${1#--port=}; shift ;;
  --spec) spec=$2; shift 2 ;; --spec=*) spec=${1#--spec=}; shift ;;
  *) shift ;;
esac; done
printf 'DOWN port=%s spec=%s avd_home=%s\n' "$port" "$spec" "${ANDROID_AVD_HOME:-}" >> "${FAKE_DOWN_LOG:-/dev/null}"
exit 0
EOF
chmod +x "$FAKEBIN/env-up" "$FAKEBIN/env-down"
export POOL_ENV_UP="$FAKEBIN/env-up" POOL_ENV_DOWN="$FAKEBIN/env-down"
export FAKE_DOWN_LOG="$POOL_ROOT/envdown.log"

# shellcheck source=/dev/null
. "$ROOT/bin/_pool.sh"

SPEC="$ROOT/devices/rootbeer.yaml"   # any path; the fake env-up never reads it

reset_pool() { rm -rf "$POOL_DIR"; : > "$FAKE_LOG"; : > "$FAKE_STATUS"; : > "$FAKE_DOWN_LOG"; }

echo "== pure: adb port = console + 1 =="
check "5554 -> 5555" "$(pool_adb_port 5554)" "5555"
check "5556 -> 5557" "$(pool_adb_port 5556)" "5557"

echo "== pure: pool_ports is the even 5554–5584 window =="
check "first port"  "$(pool_ports | head -1)" "5554"
check "last port"   "$(pool_ports | tail -1)" "5584"
check "16 ports"    "$(pool_ports | grep -c .)" "16"
check "all even"    "$(pool_ports | awk '$1%2' | grep -c .)" "0"

echo "== free port: lowest unclaimed, then the next after a slot exists =="
reset_pool
check "empty pool -> 5554" "$(_pool_free_port)" "5554"

echo "== acquire (N=1 default path): registers slot + prints contract =="
reset_pool
out="$(POOL_CAP=3 pool_acquire "$SPEC")"; rc=$?
check "acquire rc 0"        "$rc" "0"
check "contract line"       "$out" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"
check "one slot registered" "$(pool_count)" "1"
check "slot serial"         "$(pool_slot_get 5554 serial)"   "emulator-5554"
check "slot adb_port"       "$(pool_slot_get 5554 adb_port)" "5555"
check "slot status in-use"  "$(pool_slot_get 5554 status)"   "in-use"
check "slot spec recorded"  "$(pool_slot_get 5554 spec)"     "$SPEC"
# ticket 08: the engine records the real profile env-up resolved (spec default = writable-system)
check "slot profile recorded" "$(pool_slot_get 5554 profile)" "writable-system"
# env-up was called with the explicit port and a per-slot ANDROID_AVD_HOME under POOL_DIR
grep -q "port=5554 " "$FAKE_LOG" && ok "env-up got --port 5554" || bad "env-up port"
grep -q "avd_home=$POOL_DIR/5554/avd" "$FAKE_LOG" && ok "env-up got isolated avd_home" || bad "env-up avd_home"
# and the slot was 'building' while env-up ran (registered before bring-up)
check "status building mid-boot" "$(cat "$FAKE_STATUS")" "building"

echo "== extra args pass through to env-up =="
# A wrapper fake that dumps its full argv, so we can assert the engine forwards trailing
# args (e.g. --target-apk) after its own --spec/--port.
reset_pool
cat > "$FAKEBIN/env-up-echo" <<'EOF'
#!/usr/bin/env bash
printf 'ARGV %s\n' "$*" >> "$FAKE_LOG"
prev=; port=5554; for a in "$@"; do [ "$prev" = --port ] && port=$a; prev=$a; done
printf 'emulator-%s\n' "$port"
EOF
chmod +x "$FAKEBIN/env-up-echo"
POOL_ENV_UP="$FAKEBIN/env-up-echo" POOL_CAP=3 pool_acquire "$SPEC" --target-apk /x/y.apk >/dev/null
grep -q -- "--target-apk /x/y.apk" "$FAKE_LOG" && ok "forwarded --target-apk to env-up" || bad "extra args not forwarded"

echo "== the launch profile env-up resolves is recorded + reported (ticket 08) =="
# A profile override passes through to env-up; the engine records the REAL profile env-up
# resolved (here frida-only) and puts it in the connection contract + the slot registry.
reset_pool
c="$(POOL_CAP=3 pool_acquire "$SPEC" --profile frida-only)"
check "contract carries the resolved profile" "$c" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=frida-only"
check "slot records the resolved profile"     "$(pool_slot_get 5554 profile)" "frida-only"
grep -q "profile=frida-only" "$FAKE_LOG" && ok "env-up saw --profile frida-only" || bad "override not forwarded to env-up"

echo "== two acquires get distinct ports + isolated avd homes =="
reset_pool
c1="$(POOL_CAP=3 pool_acquire "$SPEC")"
c2="$(POOL_CAP=3 pool_acquire "$SPEC")"
check "slot count 2"    "$(pool_count)" "2"
check "first  is 5554"  "$c1" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"
check "second is 5556"  "$c2" "serial=emulator-5556 console_port=5556 adb_port=5557 profile=writable-system"
check "distinct avd home 5554" "$(pool_slot_get 5554 avd_home)" "$POOL_DIR/5554/avd"
check "distinct avd home 5556" "$(pool_slot_get 5556 avd_home)" "$POOL_DIR/5556/avd"

echo "== cap enforcement: (N+1)th acquire refused, registry unchanged =="
reset_pool
POOL_CAP=1 pool_acquire "$SPEC" >/dev/null; rc1=$?
POOL_CAP=1 pool_acquire "$SPEC" >/dev/null 2>&1; rc2=$?
check "1st acquire ok (rc 0)"      "$rc1" "0"
check "2nd acquire refused (rc 3)" "$rc2" "3"
check "still one slot"             "$(pool_count)" "1"

echo "== release: teardown + deregister; env-down gets port + avd home =="
reset_pool
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null
pool_release emulator-5554; rc=$?
check "release rc 0"       "$rc" "0"
check "registry clean"     "$(pool_count)" "0"
check "slot file gone"     "$([ -f "$(pool_slot_file 5554)" ] && echo yes || echo no)" "no"
check "avd dir removed"    "$([ -d "$POOL_DIR/5554" ] && echo yes || echo no)" "no"
grep -q "port=5554 " "$FAKE_DOWN_LOG" && ok "env-down got --port 5554" || bad "env-down port"
grep -q "avd_home=$POOL_DIR/5554/avd" "$FAKE_DOWN_LOG" && ok "env-down got isolated avd_home" || bad "env-down avd_home"

echo "== release by port and by serial both work =="
reset_pool
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null   # 5554
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null   # 5556
pool_release 5554 && pool_release emulator-5556
check "both released" "$(pool_count)" "0"

echo "== released port is reused by the next acquire (rebuild from scratch) =="
reset_pool
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null   # 5554
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null   # 5556
pool_release 5554
c="$(POOL_CAP=3 pool_acquire "$SPEC")"        # should reclaim the lowest free = 5554
check "reuses freed 5554" "$c" "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"

echo "== bring-up failure reclaims the slot (registry stays clean) =="
reset_pool
out="$(FAKE_UP_FAIL=1 POOL_CAP=3 pool_acquire "$SPEC" 2>/dev/null)"; rc=$?
check "acquire fails rc 5"   "$rc" "5"
check "no slot left behind"  "$(pool_count)" "0"
check "failed avd dir gone"  "$([ -d "$POOL_DIR/5554" ] && echo yes || echo no)" "no"
grep -q "port=5554 " "$FAKE_DOWN_LOG" && ok "env-down called to clean the partial" || bad "no cleanup teardown"

echo "== acquire rejects a passed-through --port/--spec (engine owns them) =="
reset_pool
POOL_CAP=3 pool_acquire "$SPEC" --port 5560 >/dev/null 2>&1; check "--port passthrough rc 2" "$?" "2"
POOL_CAP=3 pool_acquire "$SPEC" --spec other.yaml >/dev/null 2>&1; check "--spec passthrough rc 2" "$?" "2"
check "no slot created on reject" "$(pool_count)" "0"
check "env-up not called on reject" "$([ -s "$FAKE_LOG" ] && echo nonempty || echo empty)" "empty"

echo "== registry survives a value with sed metacharacters (| & / \\) =="
reset_pool
mkdir -p "$(_pool_slots_dir)"
: > "$(pool_slot_file 5554)"
META='a|b&c/d\e'
pool_slot_set 5554 spec "$META"
pool_slot_set 5554 status building
pool_slot_set 5554 status in-use          # replace must not corrupt the metachar value
check "metachar value intact" "$(pool_slot_get 5554 spec)" "$META"
check "replaced key correct"  "$(pool_slot_get 5554 status)" "in-use"
rm -rf "$(_pool_slots_dir)"

echo "== resolve: unknown serial/port is rejected =="
reset_pool
pool_resolve_port emulator-9999 >/dev/null 2>&1; check "unknown serial rc 1" "$?" "1"
pool_resolve_port notaport      >/dev/null 2>&1; check "garbage rc 1"        "$?" "1"

echo "== teardown_all clears a full pool =="
reset_pool
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null
POOL_CAP=3 pool_acquire "$SPEC" >/dev/null
check "three up"        "$(pool_count)" "3"
pool_teardown_all
check "all torn down"   "$(pool_count)" "0"

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
