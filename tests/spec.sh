#!/usr/bin/env bash
# Hermetic tests for ticket 03 (env-up/env-down from a device-spec).
# No network, no real emulator: exercises the spec loader/validator (bin/_spec.sh) against
# fake specs + a fake SDK tree, and the pure config.ini helpers (bin/_device.sh). The parts
# that need a live device (boot/kill) are covered by running env-up/env-down for real.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

# shellcheck source=/dev/null
. "$ROOT/bin/_spec.sh"
# shellcheck source=/dev/null
. "$ROOT/bin/_device.sh"

command -v yq >/dev/null 2>&1 || { echo "yq required for these tests (brew install yq)"; exit 2; }

IMG="system-images;android-37.1;google_apis_ps16k;arm64-v8a"

# A fake SDK root with the image "installed" (just its source.properties marker).
FAKE_SDK="$(mktemp -d)"; trap 'rm -rf "$FAKE_SDK"' EXIT
mkdir -p "$FAKE_SDK/${IMG//;//}"
printf 'Pkg.Revision=9\n' > "$FAKE_SDK/${IMG//;//}/source.properties"

write_spec() {  # file, [omit-key]
  local f=$1 omit=${2:-}
  {
    [ "$omit" = name ]           || echo "name: pixel-a37"
    [ "$omit" = device_profile ] || echo "device_profile: pixel"
    [ "$omit" = system_image ]   || echo "system_image: \"$IMG\""
    [ "$omit" = api ]            || echo "api: \"37.1\""
    [ "$omit" = ram_mb ]         || echo "ram_mb: 4096"
    [ "$omit" = cores ]          || echo "cores: 4"
    [ "$omit" = data_size_mb ]   || echo "data_size_mb: 8192"
  } > "$f"
}

echo "== spec_load: happy path sets SPEC_* =="
GOOD="$(mktemp)"; write_spec "$GOOD"
out="$(ANDROID_SDK_ROOT="$FAKE_SDK" bash -c '
  . "'"$ROOT"'/bin/_spec.sh"
  spec_load "'"$GOOD"'" || { echo "LOAD_FAILED rc=$?"; exit 1; }
  printf "%s|%s|%s|%s|%s|%s|%s\n" "$SPEC_NAME" "$SPEC_DEVICE_PROFILE" "$SPEC_SYSTEM_IMAGE" \
         "$SPEC_API" "$SPEC_RAM_MB" "$SPEC_CORES" "$SPEC_DATA_SIZE_MB"')"
check "all SPEC_* exported" "$out" "pixel-a37|pixel|$IMG|37.1|4096|4|8192"

echo "== spec_load: rejects a missing file =="
ANDROID_SDK_ROOT="$FAKE_SDK" spec_load "$FAKE_SDK/nope.yaml" >/dev/null 2>&1
check "missing file -> rc 2" "$?" "2"

echo "== spec_load: rejects non-YAML-map input =="
NOTMAP="$(mktemp)"; printf -- '- just\n- a\n- list\n' > "$NOTMAP"
ANDROID_SDK_ROOT="$FAKE_SDK" spec_load "$NOTMAP" >/dev/null 2>&1
check "list (not map) -> rc 2" "$?" "2"
rm -f "$NOTMAP"

echo "== spec_load: missing key is named =="
MISS="$(mktemp)"; write_spec "$MISS" ram_mb
msg="$(ANDROID_SDK_ROOT="$FAKE_SDK" spec_load "$MISS" 2>&1)"; rc=$?
check "missing key -> rc 2" "$rc" "2"
case "$msg" in *"missing required key"*"ram_mb"*) ok "message names the missing key" ;;
  *) bad "message did not name ram_mb: $msg" ;; esac
rm -f "$MISS"

echo "== spec_load: non-numeric numeric field rejected =="
BADNUM="$(mktemp)"; write_spec "$BADNUM"; printf 'ram_mb: lots\n' >> "$BADNUM"
# (the appended key overrides the earlier one in yq's last-wins map merge)
ANDROID_SDK_ROOT="$FAKE_SDK" spec_load "$BADNUM" >/dev/null 2>&1
check "ram_mb=lots -> rc 2" "$?" "2"
rm -f "$BADNUM"

echo "== spec_load: uninstalled image -> rc 3 with sdkmanager hint =="
EMPTY_SDK="$(mktemp -d)"
msg="$(ANDROID_SDK_ROOT="$EMPTY_SDK" spec_load "$GOOD" 2>&1)"; rc=$?
check "uninstalled image -> rc 3" "$rc" "3"
case "$msg" in *"sdkmanager"*"$IMG"*) ok "hint tells you to sdkmanager the image" ;;
  *) bad "hint missing sdkmanager+image: $msg" ;; esac
rm -rf "$EMPTY_SDK"

echo "== spec_name: reads name WITHOUT validating the image =="
# Teardown must work even when the image is gone, so spec_name must not require it.
n="$(ANDROID_SDK_ROOT="$(mktemp -d)" spec_name "$GOOD")"
check "spec_name -> pixel-a37" "$n" "pixel-a37"
rm -f "$GOOD"

echo "== cfg_get / cfg_set (config.ini helpers) =="
CFG="$(mktemp)"
printf 'target=android-37.1\nhw.ramSize=2048\n' > "$CFG"
check "cfg_get existing"   "$(cfg_get "$CFG" hw.ramSize)" "2048"
check "avd_target"         "$(avd_target "$CFG")"         "android-37.1"
cfg_set "$CFG" hw.ramSize 4096            # override existing
check "cfg_set overrides"  "$(cfg_get "$CFG" hw.ramSize)" "4096"
cfg_set "$CFG" hw.cpu.ncore 4            # append new
check "cfg_set appends"    "$(cfg_get "$CFG" hw.cpu.ncore)" "4"
# a dotted key must not accidentally match a different line
check "target untouched"   "$(avd_target "$CFG")"         "android-37.1"
rm -f "$CFG"

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
