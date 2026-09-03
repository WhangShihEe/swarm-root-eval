# shellcheck shell=bash
# Broker engine (ticket 06) — a standing host process that grants scoped device access.
#
# The broker wraps the ticket-05 pool engine (bin/_pool.sh) as a long-running process
# started BEFORE any Inspect eval. It is the single owner of the emulator pool and the gate
# that makes emulators a scarce, shared resource: a client asks it to `acquire` a device, the
# broker enforces the cap (it, not the caller), launches + provisions on grant, and hands back
# a connection contract the client then drives over adb itself (frida / objection / adb shell —
# brokered-adb, not a gesture API). `release` tears the device down and rebuilds from scratch,
# freeing the slot. CONTEXT.md: "Broker", "Brokered-adb", "Connection contract".
#
# Transport — a file-backed request/response queue, not a socket. Each client request is a
# directory under BROKER_DIR/queue/<id>/ holding a `req` file (verb on line 1, one arg per
# line after); the serving process answers by writing `rc` then `resp` into the same dir
# (atomic temp+mv), and the client polls for `resp`. This is bash-native (no nc/socat), works
# across separate host processes, and makes the broker the single serializer of pool access —
# requests are handled one at a time, so the cap is always enforced against a consistent
# registry. Reaching the broker from inside a sandbox over host.docker.internal is a later
# concern (ticket says: not required here); the queue dir is the seam a socket shim would wrap.
#
# Serial by design: a request is handled to completion before the next is picked up, so an
# in-flight `acquire` blocks the queue while its emulator cold-boots + provisions (minutes).
# That keeps the owner single-threaded and the cap trivially correct; a concurrency layer is a
# later optimization, not needed for a cap-3 pool where N=1 is the default path.
#
# Launch profile — a brokered device comes up under the profile its SPEC defines (writable-/
# system by default — ticket 07). The broker no longer owns a default profile; `start
# --profile <p>` is an optional OVERRIDE forced across every grant (a lighter frida-only
# footprint for a whole run, say), forwarded to env-up via the pool. The connection contract,
# `ping`, and `status` report the REAL profile each device came up under (spec-resolved, or the
# override) — not a fixed string (ticket 08).
#
# The dispatch/registry logic is unit-tested in tests/broker.sh with the pool engine's fake
# env-up/env-down injected (POOL_ENV_UP/POOL_ENV_DOWN), and the start→request→stop lifecycle is
# exercised end-to-end against a real background broker process — all with no real emulator.
# The live grant path is `bin/broker demo`.

# --- config ------------------------------------------------------------------------------
# BROKER_DIR             where the queue + pidfile + profile marker live (default: .broker/).
# BROKER_POLL            serve-loop scan interval, seconds (default 0.2).
# BROKER_CLIENT_TIMEOUT  how long a client waits for a response, seconds (default 1800 — a cold
#                        boot + provision is minutes, and because the broker is serial a client
#                        may queue behind another's boot, so it must out-wait BOTH; if it does
#                        give up, the daemon auto-releases any device it went on to grant).
# BROKER_CLIENT_POLL     client poll interval while waiting, seconds (default 0.2).
# Pool config (POOL_DIR / POOL_CAP / POOL_ENV_UP / POOL_ENV_DOWN) is the pool engine's; the
# broker just drives pool_acquire/pool_release, so the cap it enforces is POOL_CAP (default 3).
broker_dir()          { printf '%s\n' "${BROKER_DIR:-${HARNESS_ROOT:-$PWD}/.broker}"; }
broker_queue()        { printf '%s\n' "$(broker_dir)/queue"; }
broker_pidfile()      { printf '%s\n' "$(broker_dir)/broker.pid"; }
broker_profile_file() { printf '%s\n' "$(broker_dir)/profile"; }

# --- launch profiles (ticket 08) ---------------------------------------------------------
# The broker no longer owns a default profile: a grant HONORS THE SPEC (writable-/system by
# default — ticket 07). `broker start --profile <p>` is an optional OVERRIDE, forced across
# every grant, forwarded to env-up via the pool on each acquire. env-up resolves + reports the
# real profile and the pool records it, so the contract/ping/status show what a device actually
# came up under. Both wired profiles are deliverable now, so nothing force-downgrades.
BROKER_PROFILES="frida-only writable-system"
BROKER_PROFILE_OVERRIDE=""    # no override: each grant honors its own spec's profile

# broker_valid_profile P — 0 iff P names a known launch profile.
broker_valid_profile() {
  case " $BROKER_PROFILES " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# broker_profile_gate P — 0 iff P is a usable profile OVERRIDE: empty (no override ⇒ honor the
# spec) or a known profile name. Else prints the reason to stderr and returns 2. Both wired
# profiles are deliverable (ticket 07), so the gate only rejects an unknown name. The single
# source of truth for the override policy + its message, called by BOTH the daemon
# (broker_serve) and the CLI (`bin/broker start`) so the two can't drift.
broker_profile_gate() {
  local p=$1
  [ -n "$p" ] || return 0    # no override: honor each spec's profile
  broker_valid_profile "$p" \
    || { echo "broker: unknown launch profile '$p' (known: $BROKER_PROFILES)" >&2; return 2; }
}

# broker_override — the profile override the running broker was started under, or empty when it
# honors each spec's profile (the default). Persisted in the profile file.
broker_override() { cat "$(broker_profile_file)" 2>/dev/null; }

# broker_policy_label — a parseable description of the broker's profile policy for ping/status:
# the override profile when one is forced, else `per-spec` (each grant follows its own spec).
broker_policy_label() {
  local o; o="$(broker_override)"
  [ -n "$o" ] && printf '%s\n' "$o" || printf 'per-spec\n'
}

# --- liveness ----------------------------------------------------------------------------

# broker_pid — echo the serving process's pid (empty if no pidfile).
broker_pid() { cat "$(broker_pidfile)" 2>/dev/null; }

# broker_running — 0 iff a broker process for this BROKER_DIR is alive.
broker_running() {
  local pid; pid="$(broker_pid)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

# --- serve loop (the standing process) ---------------------------------------------------

# broker_serve [PROFILE] — run the request loop in the current process (the daemon body).
# Owns the pool: it claims the pidfile, answers queued requests one at a time, and on exit
# (a stop signal or a fatal error) reclaims every device so no orphaned emulator outlives the
# broker. Blocks until told to stop; returns 2 if the profile is unusable.
broker_serve() {
  local prof="${1:-$BROKER_PROFILE_OVERRIDE}"
  broker_profile_gate "$prof" || return 2

  local pf; pf="$(broker_pidfile)"; mkdir -p "$(broker_dir)"
  # Claim ownership atomically: a noclobber create fails if a pidfile already exists, so two
  # racing `broker start`s can't both become the pool's owner (last-writer-wins would leave one
  # daemon untracked and leaking on shutdown). A pidfile whose pid is dead is a stale crash
  # artifact — take it over; a live one means another broker already owns this BROKER_DIR.
  if ! ( set -o noclobber; printf '%s\n' "$$" > "$pf" ) 2>/dev/null; then
    local other; other="$(cat "$pf" 2>/dev/null)"
    if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
      echo "broker: another broker (pid=$other) already owns $pf — stop it first" >&2
      return 1
    fi
    printf '%s\n' "$$" > "$pf"          # stale pidfile from a crashed broker: reclaim it
  fi
  mkdir -p "$(broker_queue)"
  printf '%s\n' "$prof" > "$(broker_profile_file)"

  _BROKER_STOP=0
  trap '_broker_cleanup' EXIT
  trap '_BROKER_STOP=1'  TERM INT

  echo "broker: serving (pid=$$ profile=$(broker_policy_label) cap=$(pool_cap) pool_dir=$(pool_dir))" >&2
  local reqdir
  while [ "$_BROKER_STOP" -eq 0 ]; do
    for reqdir in "$(broker_queue)"/*; do
      [ -d "$reqdir" ] || continue            # no requests: the literal glob, skipped
      [ -f "$reqdir/req" ]  || continue       # still being staged (shouldn't happen: mv is atomic)
      # Already answered, awaiting client pickup. A client removes its dir once it reads resp;
      # a dir that lingers means the client crashed after we answered. We skip it (cheaply) but
      # do not GC it here — `broker stop` wipes the queue, and a per-eval broker's lifetime
      # bounds any accumulation. A long-lived broker would want a reaper; out of scope now.
      [ -f "$reqdir/resp" ] && continue
      broker_handle "$reqdir"
      [ "$_BROKER_STOP" -eq 1 ] && break
    done
    [ "$_BROKER_STOP" -eq 1 ] && break
    sleep "${BROKER_POLL:-0.2}"
  done
  # EXIT trap runs _broker_cleanup.
}

# _broker_cleanup — reclaim the pool and drop the pidfile. Idempotent; the EXIT trap's one
# call is enough, but a stray second call (belt and braces) is harmless.
_broker_cleanup() {
  trap - EXIT TERM INT
  pool_teardown_all 2>/dev/null || true       # the broker owns the pool — don't leak devices
  rm -f "$(broker_pidfile)" "$(broker_profile_file)"
}

# broker_handle REQDIR — answer one request. Reads REQDIR/req (verb + args), drives the pool
# engine, and writes REQDIR/rc then REQDIR/resp (rc first, so a client that sees resp can read
# a settled rc). Sets _BROKER_STOP on a `shutdown` verb. Never fails the loop.
broker_handle() {
  local reqdir=$1 verb line body rc=0 err grant_serial=""
  local args=()
  { IFS= read -r verb || true
    while IFS= read -r line; do args+=("$line"); done
  } < "$reqdir/req"
  err="$reqdir/err"

  case "$verb" in
    acquire)
      local spec="" rest=()
      [ "${#args[@]}" -ge 1 ] && spec="${args[0]}"
      [ "${#args[@]}" -ge 2 ] && rest=("${args[@]:1}")
      if [ -z "$spec" ]; then
        body="broker: acquire needs a device-spec"; rc=2
      else
        # The start-time override (if any) is forced across every grant: forward it to env-up
        # via the pool, appended LAST so it wins over any profile flag a client passed in rest.
        # Empty override ⇒ nothing appended ⇒ env-up honors the spec's profile.
        local override prof_args=()
        override="$(broker_override)"
        [ -n "$override" ] && prof_args=(--profile "$override")
        local out
        out="$(pool_acquire "$spec" ${rest[@]+"${rest[@]}"} ${prof_args[@]+"${prof_args[@]}"} 2>"$err")"; rc=$?
        cat "$err" >&2 2>/dev/null || true    # surface env-up progress/refusal into the broker log
        if [ "$rc" -eq 0 ]; then
          body="$out"                         # the pool contract already carries the real profile=
          grant_serial="${out#serial=}"; grant_serial="${grant_serial%% *}"
        else
          body="$(cat "$err" 2>/dev/null)"    # relay the engine's reason as a clean refusal
          [ -n "$body" ] || body="broker: acquire failed (rc=$rc)"
        fi
      fi
      ;;
    release)
      local id=""
      [ "${#args[@]}" -ge 1 ] && id="${args[0]}"
      if [ -z "$id" ]; then
        body="broker: release needs a serial or console port"; rc=2
      else
        pool_release "$id" 2>"$err"; rc=$?
        if [ "$rc" -eq 0 ]; then body="released $id"
        else body="$(cat "$err" 2>/dev/null)"; [ -n "$body" ] || body="broker: release failed (rc=$rc)"; fi
      fi
      ;;
    status)   body="$(pool_status)"; rc=0 ;;
    list)     body="$(pool_list)";   rc=0 ;;   # an empty pool is success, not an error
                                               # (pool_list's trailing grep would else rc 1 under pipefail)
    ping)     body="pong pid=$$ profile=$(broker_policy_label) cap=$(pool_cap) in-use=$(pool_count)"; rc=0 ;;
    shutdown) body="bye"; rc=0; _BROKER_STOP=1 ;;
    *)        body="broker: unknown request '$verb'"; rc=2 ;;
  esac

  rm -f "$err"

  # If the client already gave up (timed out — broker_request removes its request dir) there is
  # no one to hand the result to. For a granted device that means an unclaimed, status=in-use
  # emulator holding a scarce slot until the next `broker stop`, so release it now. (A serial
  # acquire can take minutes; a client queued behind another's cold boot is the case that times
  # out, per the "serial by design" note above.) The check-then-release has a millisecond race
  # against a client that reads resp at that instant, but its timeout is seconds-to-minutes, so
  # the window is negligible; a stray double-release is harmless (pool_release no-ops a gone slot).
  if [ ! -d "$reqdir" ]; then
    [ -n "$grant_serial" ] && pool_release "$grant_serial" >/dev/null 2>&1 || true
    return 0
  fi

  printf '%s\n' "$rc"   > "$reqdir/rc.tmp"   && mv "$reqdir/rc.tmp"   "$reqdir/rc"
  printf '%s\n' "$body" > "$reqdir/resp.tmp" && mv "$reqdir/resp.tmp" "$reqdir/resp"
}

# --- client side -------------------------------------------------------------------------

# broker_request VERB [args…] — submit one request from a client process and block for the
# response. Prints the response body on stdout and returns the broker's rc for that verb, or a
# transport error: 66 broker not running · 67 broker died mid-request · 68 timed out.
broker_request() {
  local verb=$1; shift 2>/dev/null || true
  broker_running || { echo "broker: not running — start it first: bin/broker start" >&2; return 66; }

  local d q stage id
  d="$(broker_dir)"; q="$(broker_queue)"; mkdir -p "$q"
  # Stage the request OUTSIDE the queue dir, then mv it in atomically, so the serve loop never
  # sees a half-written request (a partial req file the reader would mis-parse).
  stage="$(mktemp -d "$d/stage.XXXXXX")" || { echo "broker: cannot stage request" >&2; return 1; }
  { printf '%s\n' "$verb"; [ "$#" -gt 0 ] && printf '%s\n' "$@"; } > "$stage/req"
  id="req-$(date +%s)-$$-${RANDOM}"
  while [ -e "$q/$id" ]; do id="req-$(date +%s)-$$-${RANDOM}"; done
  mv "$stage" "$q/$id"

  local poll="${BROKER_CLIENT_POLL:-0.2}" timeout="${BROKER_CLIENT_TIMEOUT:-1800}" iters=0 maxiter
  maxiter="$(awk -v t="$timeout" -v p="$poll" 'BEGIN{ printf "%d", (t/p)+1 }')"
  while [ ! -f "$q/$id/resp" ]; do
    if ! broker_running; then rm -rf "$q/$id"; echo "broker: died while handling the request" >&2; return 67; fi
    sleep "$poll"
    iters=$((iters + 1))
    if [ "$iters" -gt "$maxiter" ]; then
      rm -rf "$q/$id"; echo "broker: timed out after ${timeout}s waiting for '$verb'" >&2; return 68
    fi
  done

  local rc; rc="$(cat "$q/$id/rc" 2>/dev/null)"; case "$rc" in ''|*[!0-9]*) rc=0 ;; esac
  cat "$q/$id/resp"
  rm -rf "$q/$id"
  return "$rc"
}

# broker_stop_cleanup — remove the queue + control files after the process is gone. Used by
# `bin/broker stop` (and a stop against an already-dead broker). Leaves broker.log behind on
# purpose, as a post-mortem of the run just stopped; the runtime state (pidfile/profile/queue/
# stage dirs) is cleared.
broker_stop_cleanup() {
  rm -rf "$(broker_queue)"
  rm -f "$(broker_pidfile)" "$(broker_profile_file)"
  rm -rf "$(broker_dir)"/stage.* 2>/dev/null || true
}
