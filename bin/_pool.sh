# shellcheck shell=bash
# Pool engine (ticket 05) — launch, track, and reclaim N provisioned devices.
#
# The in-process engine the broker (ticket 06) wraps: it brings up N *provisioned* devices
# at once on distinct console/adb port pairs (reusing ticket 04's env-up), tracks them in a
# file-backed registry, and hands out addressable connection contracts. There is no standing
# service and no scheduling policy here — acquire builds a fresh device, release tears it
# down. "Reset = full rebuild": a released slot is destroyed, and the next acquire rebuilds
# from scratch (no golden snapshot). CONTEXT.md: "Pool engine", "Connection contract".
#
# Isolation model — each slot gets:
#   * a distinct even console port in 5554–5584 (adb port = console+1), and
#   * its own ANDROID_AVD_HOME under the slot dir, so its AVD + writable userdata are
#     isolated from every other slot even when N slots share one device-spec.
# env-up/env-down already honor ANDROID_AVD_HOME and --port, so the engine reuses them
# verbatim (both the bring-up and the teardown paths) rather than reimplementing t=0.
#
# The registry is a directory of one key=value file per slot (serial/console_port/adb_port/
# status/spec/avd_home). It is file-backed, not in-memory, so a standing broker (ticket 06)
# can survive across requests and a demo can inspect it between calls. Statuses actually set:
#   building  — slot reserved, env-up bring-up in progress (create + cold boot + provision)
#   in-use    — handed out to a caller by acquire
#   down      — teardown in progress (transient during release)
# The ticket's illustrative booting/ready states are folded into building: the engine reuses
# env-up as one atomic bring-up (a finer booting/provisioning split would mean forking
# env-up's internals) and acquire hands the device out on completion, so a slot is never
# booting-separately or provisioned-but-free. A future pre-warming pool would add `ready`.
#
# Pure/registry helpers (ports, slot CRUD, free-port pick, cap) are unit-tested in
# tests/pool.sh with a fake env-up/env-down; the live bring-up is exercised by `bin/pool
# demo` against a real emulator.

# --- config: pool dir, cap, and the (overridable) bring-up/teardown commands -------------
# POOL_DIR    where the registry + per-slot AVD homes live (default: repo-local .pool/).
# POOL_CAP    max concurrent devices (a single config value, default 3; N=1 is the default
#             path and is NOT special-cased — acquire just builds one).
# POOL_ENV_UP / POOL_ENV_DOWN  the bring-up/teardown commands; overridable so the hermetic
#             tests can inject fakes instead of booting a real emulator.
pool_dir()      { printf '%s\n' "${POOL_DIR:-${HARNESS_ROOT:-$PWD}/.pool}"; }
pool_cap()      { printf '%s\n' "${POOL_CAP:-3}"; }
_pool_env_up()  { printf '%s\n' "${POOL_ENV_UP:-${HARNESS_ROOT:-$PWD}/bin/env-up}"; }
_pool_env_down(){ printf '%s\n' "${POOL_ENV_DOWN:-${HARNESS_ROOT:-$PWD}/bin/env-down}"; }
_pool_slots_dir(){ printf '%s\n' "$(pool_dir)/slots"; }

# --- ports -------------------------------------------------------------------------------
# adb only auto-discovers 5554–5584 and the console port must be even (adb takes port+1);
# the same window env-up validates. 16 even ports => a hard ceiling of 16 slots, well above
# any sane POOL_CAP.
POOL_PORT_MIN=5554
POOL_PORT_MAX=5584

# pool_adb_port CONSOLE — echo the adb port paired with an even console port (console+1).
pool_adb_port() { printf '%s\n' "$(( $1 + 1 ))"; }

# pool_ports — echo every valid even console port in range, ascending.
pool_ports() {
  local p
  for (( p=POOL_PORT_MIN; p<=POOL_PORT_MAX; p+=2 )); do printf '%s\n' "$p"; done
}

# --- registry: per-slot key=value files --------------------------------------------------

# pool_slot_file PORT — path to the slot's registry file (may not exist).
pool_slot_file() { printf '%s\n' "$(_pool_slots_dir)/$1"; }

# pool_has_slot PORT — 0 iff a slot is registered for PORT.
pool_has_slot() { [ -f "$(pool_slot_file "$1")" ]; }

# pool_slot_get PORT KEY — echo the slot's value for KEY (empty if absent).
pool_slot_get() {
  local f; f="$(pool_slot_file "$1")"
  [ -f "$f" ] || return 0
  sed -n "s/^$2=//p" "$f" | head -1
}

# pool_slot_set PORT KEY VALUE — set KEY=VALUE in the slot file (replace or append). KEY is
# always a fixed literal here (serial/status/…), so `grep -v` on it is safe; VALUE goes
# through printf and is NEVER fed to sed — a value with sed metacharacters (| & / \ — e.g. a
# POOL_DIR or spec path containing them) would otherwise corrupt the registry. Rewrite via a
# temp + mv so a concurrent reader never sees a half-written file.
pool_slot_set() {
  local k=$2 v=$3 f tmp; f="$(pool_slot_file "$1")"; tmp="$f.$$"
  { [ -f "$f" ] && grep -v "^$k=" "$f"; printf '%s=%s\n' "$k" "$v"; } > "$tmp" && mv "$tmp" "$f"
}

# pool_list — echo the registered console ports, ascending (empty if the pool is empty).
pool_list() {
  local d; d="$(_pool_slots_dir)"
  [ -d "$d" ] || return 0
  ls -1 "$d" 2>/dev/null | grep -E '^[0-9]+$' | sort -n
}

# pool_count — number of registered slots.
pool_count() { pool_list | grep -c . ; }

# _pool_free_port — read-only query: echo the lowest even console port in range with no
# registered slot (empty if every port is taken). Used by tests/status previews; acquire does
# NOT use it to claim a port (that reservation is an atomic mkdir, to avoid a read-then-write
# race). Registry is the source of truth; a live adb collision check is the broker's concern.
_pool_free_port() {
  local p
  for p in $(pool_ports); do
    pool_has_slot "$p" || { printf '%s\n' "$p"; return 0; }
  done
  return 0
}

# --- connection contract -----------------------------------------------------------------

# pool_contract PORT — echo the connection contract as one parseable key=value line:
#   serial=emulator-5554 console_port=5554 adb_port=5555
pool_contract() {
  printf 'serial=%s console_port=%s adb_port=%s\n' \
    "$(pool_slot_get "$1" serial)" "$1" "$(pool_slot_get "$1" adb_port)"
}

# --- acquire / release -------------------------------------------------------------------

# pool_acquire SPEC [extra env-up args…] — bring up one provisioned device and register it.
# Reserves a free port, gives the slot its own ANDROID_AVD_HOME, enforces the cap, and reuses
# env-up (ticket 04) to create+boot+provision. Trailing args forward to env-up (e.g.
# --target-apk, --window), but NOT --spec/--port: the engine owns those. On success prints the
# connection contract on stdout and returns 0. On refusal/failure prints a reason to stderr
# and returns non-zero:
#   2 no spec / a reserved flag passed through · 3 pool full (cap reached) · 4 no free port ·
#   5 bring-up failed.
pool_acquire() {
  local spec=$1; shift 2>/dev/null || true
  [ -n "$spec" ] || { echo "pool: acquire needs a device-spec (SPEC)" >&2; return 2; }

  # The engine assigns --spec/--port; a passthrough copy would let env-up honor the LAST
  # --port and desync the registry (slot named X, emulator booted on Y, release kills neither).
  local a
  for a in "$@"; do
    case "$a" in
      --spec|--spec=*|--port|--port=*)
        echo "pool: the engine assigns --spec/--port; don't pass them to acquire (got '$a')" >&2
        return 2 ;;
    esac
  done

  local slots port= p slotdir avd_home
  slots="$(_pool_slots_dir)"; mkdir -p "$slots"

  # Atomically reserve a free even port by creating its slot dir. `mkdir` (no -p) fails if the
  # dir already exists, so two concurrent acquires — a standing broker (ticket 06) may serve
  # requests back-to-back — can never win the same port. (A read-then-write free-port pick
  # would race in that gap; that is why reservation is the atomic mkdir, not _pool_free_port.)
  for p in $(pool_ports); do
    pool_has_slot "$p" && continue
    slotdir="$(pool_dir)/$p"
    if mkdir "$slotdir" 2>/dev/null; then port="$p"; break; fi
  done
  [ -n "$port" ] || { echo "pool: no free console port in ${POOL_PORT_MIN}-${POOL_PORT_MAX}" >&2; return 4; }
  avd_home="$slotdir/avd"; mkdir -p "$avd_home"

  # Register the slot (status=building) so pool_count/pool_list and a concurrent `pool status`
  # see the port claimed while env-up runs, then enforce the cap authoritatively against the
  # registry (count now includes this slot); back the reservation out cleanly if over cap.
  {
    printf 'console_port=%s\n' "$port"
    printf 'adb_port=%s\n'     "$(pool_adb_port "$port")"
    printf 'serial=emulator-%s\n' "$port"
    printf 'status=building\n'
    printf 'spec=%s\n'         "$spec"
    printf 'avd_home=%s\n'     "$avd_home"
  } > "$(pool_slot_file "$port")"

  local cap count; cap="$(pool_cap)"; count="$(pool_count)"
  if [ "$count" -gt "$cap" ]; then
    echo "pool: full — $((count - 1))/$cap devices already in use (cap=POOL_CAP); release one first" >&2
    _pool_teardown_slot "$port"
    return 3
  fi

  # Bring up on the slot's isolated AVD home + explicit port, reusing ticket 04's env-up.
  # env-up prints only the serial on stdout; its progress goes to stderr (kept, so a demo
  # shows the boot). Capture the serial to confirm the contract.
  local serial rc
  serial="$(ANDROID_AVD_HOME="$avd_home" "$(_pool_env_up)" --spec "$spec" --port "$port" "$@")"
  rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$serial" ]; then
    echo "pool: bring-up failed for $spec on port $port (env-up rc=$rc) — reclaiming slot" >&2
    _pool_teardown_slot "$port"
    return 5
  fi

  pool_slot_set "$port" serial "$serial"
  pool_slot_set "$port" status in-use
  pool_contract "$port"
}

# _pool_teardown_slot PORT — tear the instance down (kill emulator + delete AVD via env-down
# on the slot's own AVD home) and remove the registry entry + slot dir. Idempotent. Shared
# by release and by acquire's failure path.
_pool_teardown_slot() {
  local port=$1 spec avd_home
  pool_has_slot "$port" || return 0
  spec="$(pool_slot_get "$port" spec)"
  avd_home="$(pool_slot_get "$port" avd_home)"
  pool_slot_set "$port" status down

  # env-down works from --spec (reads just .name); pass --port so it kills the right
  # instance, and the slot's ANDROID_AVD_HOME so it deletes the right (isolated) AVD.
  ANDROID_AVD_HOME="$avd_home" "$(_pool_env_down)" --spec "$spec" --port "$port" >&2 || true

  rm -f "$(pool_slot_file "$port")"
  [ -n "$avd_home" ] && rm -rf "$(dirname "$avd_home")"
  return 0
}

# pool_resolve_port ID — echo the console port for a console port or an emulator-<port>
# serial; empty + rc 1 if it names no registered slot.
pool_resolve_port() {
  local id=$1 port
  case "$id" in emulator-*) port="${id#emulator-}" ;; *) port="$id" ;; esac
  case "$port" in ''|*[!0-9]*) echo "pool: not a port or serial: '$id'" >&2; return 1 ;; esac
  pool_has_slot "$port" || { echo "pool: no slot for '$id'" >&2; return 1; }
  printf '%s\n' "$port"
}

# pool_release ID — reclaim the slot named by a console port or emulator-<port> serial:
# full teardown + deregister. The next acquire rebuilds from scratch.
pool_release() {
  local port; port="$(pool_resolve_port "$1")" || return 1
  _pool_teardown_slot "$port"
}

# pool_teardown_all — release every registered slot (used by `pool down-all` and demos).
pool_teardown_all() {
  local port
  for port in $(pool_list); do _pool_teardown_slot "$port"; done
}

# --- status ------------------------------------------------------------------------------

# pool_status — print the registry as a table (header always; rows for each slot).
pool_status() {
  local cap count port
  cap="$(pool_cap)"; count="$(pool_count)"
  printf 'pool: %s/%s in use (POOL_DIR=%s)\n' "$count" "$cap" "$(pool_dir)"
  printf '  %-16s %-8s %-8s %-10s %s\n' SERIAL CONSOLE ADB STATUS SPEC
  for port in $(pool_list); do
    printf '  %-16s %-8s %-8s %-10s %s\n' \
      "$(pool_slot_get "$port" serial)" "$port" \
      "$(pool_slot_get "$port" adb_port)" \
      "$(pool_slot_get "$port" status)" \
      "$(pool_slot_get "$port" spec)"
  done
}
