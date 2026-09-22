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

# avd_target CONFIG_INI — echo the AVD's target= value (e.g. android-35). This is the
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

# --- writable-/system launch profile (ticket 07) -----------------------------------------
# The proven recipe from ticket 02 / RUNBOOK: on a userdebug+verity image a plain `adb root`
# cannot write /system, so the device must be cold-booted with `-writable-system` (env-up
# adds the flag) and then have verity disabled + a reboot + a remount applied. These talk to
# a live device, so they are exercised by a real env-up bring-up, not the hermetic suite.

# emu_system_writable SERIAL — 0 iff /system is *genuinely* writable: write a throwaway file,
# read it back, delete it. The definitive check — getprop veritymode still prints "enforcing"
# after a successful remount (it's the static boot flag), so only a real write proves it.
emu_system_writable() {
  local serial=$1 probe="/system/harness-probe-$$" out
  out=$(adb -s "$serial" shell "echo probe > $probe && cat $probe && rm -f $probe" 2>/dev/null | tr -d '\r')
  [ "$out" = probe ]
}

# emu_make_system_writable SERIAL TIMEOUT_S [PID] — run the proven recipe end to end against
# a device already cold-booted with `-writable-system`: adb root, disable-verity, reboot,
# re-wait for the device to come back genuinely booted, adb root again, remount → /system RW
# (overlayfs). Returns 0 iff /system ends genuinely writable (probed), non-zero otherwise —
# the caller MUST fail loudly and never hand back a device without the writable /system it
# asked for. The final probe is the authority; the intermediate steps are best-effort.
emu_make_system_writable() {
  local serial=$1 timeout=$2 pid=${3:-}
  adb -s "$serial" root >/dev/null 2>&1 || true
  adb -s "$serial" wait-for-device >/dev/null 2>&1 || true
  adb -s "$serial" disable-verity >/dev/null 2>&1 || true   # only takes effect after a reboot
  adb -s "$serial" reboot >/dev/null 2>&1 || true
  _emu_wait_reboot "$serial" "$timeout" "$pid" || return 1
  adb -s "$serial" root >/dev/null 2>&1 || true
  adb -s "$serial" wait-for-device >/dev/null 2>&1 || true
  adb -s "$serial" remount >/dev/null 2>&1 || true          # /system now mounted rw
  emu_system_writable "$serial"
}

# _emu_wait_reboot SERIAL TIMEOUT_S [PID] — after an `adb reboot`, wait for the reboot to
# actually take (boot_completed stops reading 1) before re-checking full readiness. Without
# this bound the still-up pre-reboot state could read as "booted" and we'd remount too early.
# Returns like emu_wait_boot (0 booted, 1 timeout, 2 emulator PID died first).
_emu_wait_reboot() {
  local serial=$1 timeout=$2 pid=${3:-} i
  for i in $(seq 1 30); do
    [ "$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] || break
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then return 2; fi
    sleep 1
  done
  emu_wait_boot "$serial" "$timeout" "$pid"
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
