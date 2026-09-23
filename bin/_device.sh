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

# --- configured egress CA on the device (env-hardening ticket 05) ------------------------
# Org-gated + INERT BY DEFAULT. On a host that supplies its own egress-proxy CA out-of-band
# (dropped into the gitignored CA dir), the writable-/system env-up path makes the emulator
# trust it, so proxy-fronted backends become reachable/interceptable (report.md §S2 — the
# precondition for any phase-3 finding on a network-backed target). On any host with NO cert
# supplied, every step here is a SILENT, CLEAN NO-OP: the feature ships to everyone inert and
# nothing org-specific is ever committed (the CA dir is gitignored — a clone builds and boots
# with the step doing nothing).
#
# This mirrors the existing sandbox-CA precedent (swarm-eval/Dockerfile trusts the out-of-band
# swarm-eval/certs/ca-bundle-cf.pem; `certs/` is gitignored via swarm-eval/.gitignore): the
# device reads the SAME gitignored certs location, so an operator provisions the CA once.
#
# DEVICE FACT (report.md §S2, device-confirmed on android-15 / SDK 35): the runtime trust
# store Conscrypt actually reads is the Conscrypt APEX cacerts (/apex/com.android.conscrypt/
# cacerts, a tmpfs), NOT the legacy /system/etc/security/cacerts (writable under the
# writable-/system profile but NOT honored at runtime on Android 14+). So the install below
# lands the CA in the APEX store, not just the legacy dir.
#
# FOLLOW-UPS (flagged, deliberately NOT built here — ticket 05 criterion 5):
#   * TLS certificate PINNING is a separate, per-app wall: an app that ships a programmatic
#     OkHttp CertificatePinner / SslPublicKeyPinningModule (e.g. singtel) will NOT be defeated
#     by a trusted CA alone — that needs per-app frida unpinning, not an env-up fix. scamshield
#     (no observed pinning) is the clean first CA-validation target for exactly this reason.
#   * INTERNAL-ONLY backend hosts need DNS stubbing: a trusted CA does nothing if the host
#     doesn't resolve from the device/sandbox (e.g. sgsecure's intranet BFF). A hosts-file /
#     DNS stub in provisioning pointing the internal host at the egress proxy is the follow-up.

# device_ca_dir — echo the out-of-band CA source dir (the gitignored certs location). Defaults
# to the SAME location the sandbox CA precedent uses (swarm-eval/certs); override with
# $DEVICE_CA_DIR. Nothing here is committed — the dir is gitignored (swarm-eval/.gitignore).
device_ca_dir() {
  printf '%s\n' "${DEVICE_CA_DIR:-${HARNESS_ROOT:-$PWD}/swarm-eval/certs}"
}

# device_ca_files [DIR] — echo the newline list of CA cert files present in DIR (default
# device_ca_dir): *.pem *.crt *.cer. EMPTY output iff none supplied — this is the no-op gate
# (empty ⇒ "no egress CA on this host ⇒ inert"). Never errors on a missing dir (an unmatched
# glob is skipped), so a clone with no CA simply yields nothing here.
device_ca_files() {
  local dir=${1:-$(device_ca_dir)} f
  [ -d "$dir" ] || return 0
  for f in "$dir"/*.pem "$dir"/*.crt "$dir"/*.cer; do
    [ -f "$f" ] && printf '%s\n' "$f"
  done
}

# device_ca_stage DIR OUTDIR — HOST-SIDE (no device). Split every cert file in DIR into
# individual PEM certificates (a file may be a bundle of many), hash each with
# `openssl x509 -subject_hash_old` — the filename Android's trust store keys on — and write it
# as OUTDIR/<hash>.<N> (bumping N on a hash collision). File content is the AOSP cacerts format:
# the PEM cert followed by its human-readable text dump. Echoes the count of certs staged.
device_ca_stage() {
  local dir=$1 out=$2 f cert hash suffix count=0 blockdir
  mkdir -p "$out" || return 1
  blockdir=$(mktemp -d) || return 1
  # Explode every supplied cert file into one file per PEM certificate block.
  for f in $(device_ca_files "$dir"); do
    awk -v d="$blockdir" '
      /-----BEGIN CERTIFICATE-----/ { n++; fn=sprintf("%s/blk-%06d.pem", d, n) }
      n>0 { print > fn }
      /-----END CERTIFICATE-----/  { if (fn!="") close(fn) }
    ' "$f"
  done
  for cert in "$blockdir"/blk-*.pem; do
    [ -f "$cert" ] || continue
    hash=$(openssl x509 -subject_hash_old -noout -in "$cert" 2>/dev/null) || continue
    [ -n "$hash" ] || continue
    suffix=0
    while [ -e "$out/$hash.$suffix" ]; do suffix=$((suffix+1)); done
    { openssl x509 -in "$cert" 2>/dev/null
      openssl x509 -in "$cert" -text -fingerprint -noout 2>/dev/null
    } > "$out/$hash.$suffix"
    count=$((count+1))
  done
  rm -rf "$blockdir"
  printf '%s\n' "$count"
}

# _DEVICE_CA_APEX_SCRIPT — the on-device (root) install, targeting the Conscrypt APEX store.
# Standard Android-14+ recipe: assemble the FULL trusted set (current APEX certs + our staged
# CA[s]) in a tmpfs and bind-mount it over BOTH the legacy dir (for tools that still read it)
# and — the one that matters at runtime — /apex/com.android.conscrypt/cacerts. Processes started
# AFTER the mount inherit it via zygote; already-running processes are re-bound best-effort in
# their own mount namespaces. Reads our staged <hash>.N files from /data/local/tmp/harness-cacerts.
_DEVICE_CA_APEX_SCRIPT='
set -u
SYS=/system/etc/security/cacerts
APEX=/apex/com.android.conscrypt/cacerts
STAGE=/data/local/tmp/harness-cacerts
WORK=/data/local/tmp/harness-cacerts-full
rm -rf "$WORK"; mkdir -p "$WORK" || exit 10
# Seed from the store the runtime actually reads, so we ADD to trust, never replace it.
cp -f "$APEX"/* "$WORK"/ 2>/dev/null || true
cp -f "$STAGE"/*.0 "$WORK"/ 2>/dev/null
cp -f "$STAGE"/*   "$WORK"/ 2>/dev/null
chown 0:0 "$WORK"/* 2>/dev/null || true
chmod 644 "$WORK"/* 2>/dev/null || true
chcon u:object_r:system_security_cacerts_file:s0 "$WORK"/* 2>/dev/null || true
# Legacy dir: tmpfs overlay holding the full set (covers tools that still read it).
mount -t tmpfs tmpfs "$SYS" 2>/dev/null || true
cp -f "$WORK"/* "$SYS"/ 2>/dev/null
chown 0:0 "$SYS"/* 2>/dev/null || true
chmod 644 "$SYS"/* 2>/dev/null || true
chcon u:object_r:system_security_cacerts_file:s0 "$SYS"/* 2>/dev/null || true
# APEX store (the runtime-honored one on Android 14+): bind our assembled set over it.
mount --bind "$SYS" "$APEX" || { echo "device-ca: bind-mount over $APEX failed" >&2; exit 11; }
# Re-bind into already-running processes mount namespaces (best-effort: apps started after
# this inherit the mount via zygote; nsenter may be absent on some toybox builds).
for pid in $(ls /proc 2>/dev/null | grep -E "^[0-9]+$"); do
  grep -q "$APEX" /proc/$pid/mounts 2>/dev/null && continue
  nsenter --mount=/proc/$pid/ns/mnt -- mount --bind "$SYS" "$APEX" 2>/dev/null || true
done
echo "device-ca: installed $(ls "$STAGE" 2>/dev/null | wc -l) CA file(s) into $APEX"
'

# device_ca_install SERIAL — writable-/system only. If the host supplied an egress CA in the
# gitignored CA dir (device_ca_dir), stage + install it into the Conscrypt APEX trust store on
# SERIAL and verify it landed. With NO cert supplied this returns 0 IMMEDIATELY without touching
# the device — the clean no-op. Returns non-zero ONLY when a CA is present and the install fails
# (env-up then dies loudly: an operator who supplied a CA must not get a device that ignores it).
device_ca_install() {
  local serial=$1 dir files n staged expect out
  dir=$(device_ca_dir)
  files=$(device_ca_files "$dir")
  if [ -z "$files" ]; then
    return 0                       # no out-of-band CA on this host — inert (the default)
  fi
  command -v openssl >/dev/null 2>&1 \
    || { echo "device_ca_install: an egress CA is present in $dir but openssl (needed to hash it) is not on PATH" >&2; return 1; }
  staged=$(mktemp -d) || return 1
  n=$(device_ca_stage "$dir" "$staged") || { rm -rf "$staged"; return 1; }
  if [ "${n:-0}" -lt 1 ]; then
    echo "device_ca_install: cert file(s) present in $dir but 0 usable CA certs extracted" >&2
    rm -rf "$staged"; return 1
  fi
  expect=$(ls "$staged" 2>/dev/null | head -1)   # a <hash>.N we can assert landed in the APEX store
  adb -s "$serial" root >/dev/null 2>&1 || true
  adb -s "$serial" wait-for-device >/dev/null 2>&1 || true
  adb -s "$serial" shell 'rm -rf /data/local/tmp/harness-cacerts && mkdir -p /data/local/tmp/harness-cacerts' >/dev/null 2>&1
  if ! adb -s "$serial" push "$staged"/. /data/local/tmp/harness-cacerts/ >/dev/null 2>&1; then
    echo "device_ca_install: failed to push staged CA(s) to $serial" >&2
    rm -rf "$staged"; return 1
  fi
  rm -rf "$staged"
  adb -s "$serial" shell "$_DEVICE_CA_APEX_SCRIPT" >&2 || { echo "device_ca_install: on-device APEX install failed on $serial" >&2; return 1; }
  # Verify our CA is now present in the store the runtime reads (the APEX cacerts).
  out=$(adb -s "$serial" shell "ls /apex/com.android.conscrypt/cacerts/$expect" 2>/dev/null | tr -d '\r')
  case "$out" in
    *"$expect"*) return 0 ;;
    *) echo "device_ca_install: CA '$expect' not found in /apex/com.android.conscrypt/cacerts after install on $serial" >&2; return 1 ;;
  esac
}
