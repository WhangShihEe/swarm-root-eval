# shellcheck shell=bash
# Emulator lifecycle helpers, shared by bin/env-up and bin/env-down. Thin wrappers over
# adb/emulator that encode the readiness contract and the port-race footgun recorded in
# RUNBOOK.md. Everything here talks to a live device, so it is exercised by env-up/-down
# on a real boot rather than by the hermetic suite; the pure config.ini helpers (cfg_get/
# cfg_set) and avd_target are unit-tested.

# --- AVD config.ini get/set --------------------------------------------------------------

# cfg_get FILE KEY — echo the value of KEY=... (first match), or empty.
cfg_get() { sed -nE "s/^$(_cfg_esc "$2")=(.*)/\1/p" "$1" 2>/dev/null | head -1; }

# cfg_set FILE KEY VALUE — set KEY=VALUE, replacing an existing line or appending one.
cfg_set() {
  local f=$1 k=$2 v=$3
  if grep -q "^$(_cfg_esc "$k")=" "$f" 2>/dev/null; then
    sed -i.bak -E "s|^$(_cfg_esc "$k")=.*|$k=$v|" "$f" && rm -f "$f.bak"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}

# Escape a config key for use in a sed/grep BRE/ERE (its dots are literal here).
_cfg_esc() { printf '%s' "$1" | sed 's/[.[\*^$]/\\&/g'; }

# avd_target CONFIG_INI — echo the AVD's target= value (e.g. android-37.1). This is the
# api-0 black-screen guard from RUNBOOK / ticket 02: a target of android-0 never boots.
avd_target() { cfg_get "$1" target; }

# --- running-emulator lifecycle ----------------------------------------------------------

# emu_present SERIAL — 0 iff `adb devices` currently lists SERIAL (any state).
emu_present() { adb devices 2>/dev/null | awk -v s="$1" '$1==s{f=1} END{exit f?0:1}'; }

# emu_kill SERIAL — ask a running emulator on SERIAL to exit, then wait (bounded) for it
# to leave `adb devices`. Idempotent: a no-op if nothing is there. Returns 0 once gone.
emu_kill() {
  local serial=$1 i
  emu_present "$serial" || return 0
  adb -s "$serial" emu kill >/dev/null 2>&1 || true
  for i in $(seq 1 30); do
    emu_present "$serial" || return 0
    sleep 1
  done
  # Still there — report it; the caller decides whether that's fatal.
  emu_present "$serial" && return 1 || return 0
}

# emu_booted SERIAL — 0 iff the device is genuinely usable, not merely "device":
# boot_completed==1, bootanim stopped, and the package manager answers. (RUNBOOK step 2.)
emu_booted() {
  local serial=$1
  [ "$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] \
  && [ "$(adb -s "$serial" shell getprop init.svc.bootanim 2>/dev/null | tr -d '\r')" = stopped ] \
  && [ -n "$(adb -s "$serial" shell pm path android 2>/dev/null)" ]
}

# emu_wait_boot SERIAL TIMEOUT_S [PID] — block until emu_booted. Returns:
#   0 booted; 1 timed out after TIMEOUT_S; 2 the emulator PID (if given) exited first.
# We deliberately do NOT call `adb wait-for-device` here: it blocks indefinitely, so a
# launch that never registers a serial (dead emulator, bad flag) would hang past TIMEOUT.
# The poll loop below already tolerates an absent serial (emu_booted just reads empty),
# and the optional PID check fails fast when the emulator process dies at launch.
emu_wait_boot() {
  local serial=$1 timeout=$2 pid=${3:-} deadline
  deadline=$(( $(date +%s) + timeout ))
  until emu_booted "$serial"; do
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then return 2; fi
    if [ "$(date +%s)" -ge "$deadline" ]; then return 1; fi
    sleep 5
  done
  return 0
}
