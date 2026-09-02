# shellcheck shell=bash
# Provisioning helpers — take a *booted* device to t=0: root shell, frida-server, target
# APK installed, settings normalized (CONTEXT.md "Provisioning"). Sourced by bin/env-up
# and bin/verify. Writes only to /data — never /system (the Frida-only launch profile;
# the writable-/system recipe stays opt-in, see RUNBOOK).
#
# Split into PURE helpers (APK split-detection, badging parse, tool resolution — unit
# tested in tests/provision.sh) and DEVICE helpers (root/frida/install/settings/verify —
# exercised live by running env-up + bin/verify against a real boot).

# --- pure: APK resolution (single vs split) ----------------------------------------------

# apk_install_set PATH — echo the newline-separated list of .apk files to install, base
# first then any split_config.*.apk. Handles both the APK-in interface shapes we ship:
#   - a lone self-contained .apk (dbs)        -> just that file
#   - a base.apk beside split_config.*.apk    -> base + splits (HealthHub, Singtel)
#   - a directory holding the above           -> resolved the same way
# Detection is by the presence of split_config.* siblings, never by app identity.
apk_install_set() {
  local p=$1 dir base s
  if [ -d "$p" ]; then
    dir=$p
    base=""; [ -f "$dir/base.apk" ] && base="$dir/base.apk"
  else
    dir=$(dirname "$p"); base=$p
  fi
  if [ -n "$base" ]; then
    printf '%s\n' "$base"
    for s in "$dir"/split_config.*.apk; do
      [ -f "$s" ] || continue          # no splits -> glob stays literal, skipped
      [ "$s" = "$base" ] && continue
      printf '%s\n' "$s"
    done
  else
    # A directory with no base.apk: install every .apk in it.
    for s in "$dir"/*.apk; do [ -f "$s" ] && printf '%s\n' "$s"; done
  fi
}

# apk_is_split PATH — 0 iff apk_install_set yields more than one file (a split set).
apk_is_split() { [ "$(apk_install_set "$1" | grep -c .)" -gt 1 ]; }

# apk_resolve_path PATH — normalize a target-APK path the way env-up and bin/verify both
# need it (kept here so the two agree): expand a leading ~/ (a spec value is not shell-
# expanded), and resolve a relative path against CWD, then $HARNESS_ROOT. Echoes the
# resolved path unchanged if already absolute or if nothing matches.
apk_resolve_path() {
  local p=$1
  case "$p" in "~/"*) p="$HOME/${p#\~/}" ;; esac
  case "$p" in
    /*) ;;
    *) if [ -e "$p" ]; then p="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
       elif [ -n "${HARNESS_ROOT:-}" ] && [ -e "$HARNESS_ROOT/$p" ]; then p="$HARNESS_ROOT/$p"; fi ;;
  esac
  printf '%s\n' "$p"
}

# --- pure: manifest derivation (package + launchable activity) ---------------------------
# Package name and launch activity come from the APK itself (aapt dump badging, verified
# working this session) — never hardcoded, so any APK works with no code change.

# aapt_bin — echo the newest build-tools aapt (or $AAPT override). rc1 if none found.
aapt_bin() {
  if [ -n "${AAPT:-}" ]; then printf '%s\n' "$AAPT"; return 0; fi
  local a; a=$(ls "${ANDROID_SDK_ROOT:-}"/build-tools/*/aapt 2>/dev/null | sort -V | tail -1)
  [ -n "$a" ] || return 1
  printf '%s\n' "$a"
}

# _badging_package / _badging_activity — parse aapt badging text from stdin.
_badging_package()  { sed -nE "s/^package: name='([^']+)'.*/\1/p"; }
_badging_activity() { sed -nE "s/^launchable-activity: name='([^']+)'.*/\1/p"; }

# apk_package APK — echo the package name derived from the APK's manifest.
apk_package() {
  local aapt; aapt=$(aapt_bin) || { echo "provision: no aapt in \$ANDROID_SDK_ROOT/build-tools (source bin/env.sh)" >&2; return 1; }
  "$aapt" dump badging "$1" 2>/dev/null | _badging_package | head -1
}

# apk_launch_activity APK — echo the launchable-activity name (may be empty for a library).
apk_launch_activity() {
  local aapt; aapt=$(aapt_bin) || return 1
  "$aapt" dump badging "$1" 2>/dev/null | _badging_activity | head -1
}

# --- pure: frida-server binary resolution ------------------------------------------------

# frida_server_bin — echo the host path to the frida-server binary to push. $FRIDA_SERVER
# overrides; else ~/frida-server-<FRIDA_VERSION>-<FRIDA_SERVER_ARCH> (versions.txt). The
# client (frida-ps -U) and server MUST be the same version — doctor asserts the client.
frida_server_bin() {
  if [ -n "${FRIDA_SERVER:-}" ]; then printf '%s\n' "$FRIDA_SERVER"; return 0; fi
  printf '%s\n' "$HOME/frida-server-${FRIDA_VERSION:-}-${FRIDA_SERVER_ARCH:-android-arm64}"
}

# --- device: root shell ------------------------------------------------------------------

# prov_root SERIAL — restart adbd as root and confirm uid=0. This image grants root
# directly (RUNBOOK step 3); that is all set-1 provisioning needs (everything under /data).
prov_root() {
  local serial=$1 id
  adb -s "$serial" root >/dev/null 2>&1 || true   # "restarting adbd as root" (or already root)
  adb -s "$serial" wait-for-device >/dev/null 2>&1 || true
  id=$(adb -s "$serial" shell id 2>/dev/null | tr -d '\r')
  case "$id" in *uid=0* ) return 0 ;; esac
  echo "provision: root shell not granted on $serial (id: ${id:-<none>})" >&2
  return 1
}

# --- device: frida-server ----------------------------------------------------------------

# prov_frida SERIAL — push the pinned frida-server to /data/local/tmp, start it, and
# confirm the host client reaches it. Idempotent: a re-push over a running server is fine.
prov_frida() {
  local serial=$1 fs; fs=$(frida_server_bin)
  [ -f "$fs" ] || { echo "provision: frida-server binary not found: $fs
      download frida-server-${FRIDA_VERSION}-${FRIDA_SERVER_ARCH} from the frida releases, or set \$FRIDA_SERVER" >&2; return 1; }
  adb -s "$serial" push "$fs" /data/local/tmp/frida-server >/dev/null 2>&1 \
    || { echo "provision: failed to push frida-server to $serial" >&2; return 1; }
  adb -s "$serial" shell chmod 755 /data/local/tmp/frida-server >/dev/null 2>&1
  # Start detached; a second start is harmless (the new one exits if the port is taken).
  adb -s "$serial" shell "nohup /data/local/tmp/frida-server >/dev/null 2>&1 &" >/dev/null 2>&1
  prov_frida_up "$serial"   # poll for reachability
}

# prov_frida_up SERIAL — 0 iff the host frida client lists device processes (server
# reachable). Polls briefly: frida-server takes a moment to open its port after launch.
# Scopes to SERIAL with -D (not -U) so it is unambiguous once the pool runs >1 emulator.
prov_frida_up() {
  local serial=$1 i out
  for i in $(seq 1 10); do
    out=$(frida-ps -D "$serial" 2>/dev/null)
    [ -n "$out" ] && return 0
    sleep 1
  done
  return 1
}

# --- device: APK install (single or split) -----------------------------------------------

# prov_install SERIAL APKPATH — install the target, auto-detecting single vs split.
prov_install() {
  local serial=$1 path=$2 set n
  set=$(apk_install_set "$path")
  n=$(printf '%s\n' "$set" | grep -c .)
  [ "$n" -ge 1 ] || { echo "provision: no .apk found at $path" >&2; return 1; }
  if [ "$n" -eq 1 ]; then
    adb -s "$serial" install -r "$set" >/dev/null 2>&1 \
      || { echo "provision: 'adb install -r $set' failed on $serial" >&2; return 1; }
  else
    # install-multiple wants base + all splits as one atomic set (word-split intentional).
    # shellcheck disable=SC2086
    adb -s "$serial" install-multiple -r $set >/dev/null 2>&1 \
      || { echo "provision: 'adb install-multiple -r' (split set) failed on $serial" >&2; return 1; }
  fi
}

# --- device: settings normalization ------------------------------------------------------

_ANIM_SCALES="window_animation_scale transition_animation_scale animator_duration_scale"

# prov_settings SERIAL — zero the three animation scales (a stable, fast UI for the agent).
prov_settings() {
  local serial=$1 k
  for k in $_ANIM_SCALES; do
    adb -s "$serial" shell settings put global "$k" 0 >/dev/null 2>&1
  done
  prov_settings_ok "$serial"
}

# prov_settings_ok SERIAL — 0 iff all three animation scales read back as 0.
prov_settings_ok() {
  local serial=$1 k v
  for k in $_ANIM_SCALES; do
    v=$(adb -s "$serial" shell settings get global "$k" 2>/dev/null | tr -d '\r')
    case "$v" in 0|0.0|0.00) ;; *) echo "provision: $k is '$v', expected 0 on $serial" >&2; return 1 ;; esac
  done
  return 0
}

# --- device: verify predicates (used by bin/verify) --------------------------------------

# verify_frida SERIAL — 0 iff the frida client reaches SERIAL (server up). One-shot,
# serial-scoped with -D like every other device predicate here (emu_present/emu_booted/
# verify_package all take SERIAL) — so it stays unambiguous with >1 emulator (ticket 05).
verify_frida() { [ -n "$(frida-ps -D "$1" 2>/dev/null)" ]; }

# verify_package SERIAL PKG — 0 iff PKG appears in `pm list packages`.
verify_package() {
  local serial=$1 pkg=$2
  adb -s "$serial" shell pm list packages 2>/dev/null | tr -d '\r' \
    | grep -qx "package:$pkg"
}
