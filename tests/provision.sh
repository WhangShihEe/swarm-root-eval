#!/usr/bin/env bash
# Hermetic tests for ticket 04 (provision + verify).
# No network, no real emulator/adb: exercises the *pure* provisioning helpers in
# bin/_provision.sh (APK split-detection, badging parse, frida-server/aapt resolution)
# and the new optional device-spec fields in bin/_spec.sh (target_apk + toggles).
# The device-touching parts (root/frida/install/settings) are covered by running
# env-up + bin/verify against a real boot.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

# shellcheck source=/dev/null
. "$ROOT/bin/_provision.sh"
# shellcheck source=/dev/null
. "$ROOT/bin/_spec.sh"

command -v yq >/dev/null 2>&1 || { echo "yq required for these tests (brew install yq)"; exit 2; }

# --- apk_install_set: single vs split detection ------------------------------------------
echo "== apk_install_set: lone base.apk -> single install =="
D1="$(mktemp -d)"; : > "$D1/base.apk"
out="$(apk_install_set "$D1/base.apk")"
check "single: one line"       "$(printf '%s\n' "$out" | grep -c .)" "1"
check "single: is the apk"     "$out" "$D1/base.apk"
rm -rf "$D1"

echo "== apk_install_set: base.apk + split_config.* -> multi, base first =="
D2="$(mktemp -d)"; : > "$D2/base.apk"
: > "$D2/split_config.arm64_v8a.apk"; : > "$D2/split_config.en.apk"; : > "$D2/split_config.xxhdpi.apk"
out="$(apk_install_set "$D2/base.apk")"
check "split: four lines"      "$(printf '%s\n' "$out" | grep -c .)" "4"
check "split: base is first"   "$(printf '%s\n' "$out" | head -1)" "$D2/base.apk"
check "split: has arm64 split" "$(printf '%s\n' "$out" | grep -c 'split_config.arm64_v8a.apk')" "1"
check "split: no dup base"     "$(printf '%s\n' "$out" | grep -c '/base.apk$')" "1"

echo "== apk_install_set: a directory resolves to base + splits too =="
out="$(apk_install_set "$D2")"
check "dir: four lines"        "$(printf '%s\n' "$out" | grep -c .)" "4"
check "dir: base first"        "$(printf '%s\n' "$out" | head -1)" "$D2/base.apk"
rm -rf "$D2"

echo "== apk_install_set: a non-'base' lone apk installs as itself =="
D3="$(mktemp -d)"; : > "$D3/rootbeer.apk"
out="$(apk_install_set "$D3/rootbeer.apk")"
check "lone: one line"         "$(printf '%s\n' "$out" | grep -c .)" "1"
check "lone: is the apk"       "$out" "$D3/rootbeer.apk"
rm -rf "$D3"

echo "== apk_resolve_path: ~/ expansion, absolute passthrough, relative->CWD =="
FH0="$(mktemp -d)"; : > "$FH0/app.apk"
check "absolute passes through" "$(apk_resolve_path /a/b/c.apk)" "/a/b/c.apk"
check "~/ expands to HOME"      "$(HOME=/fake/home apk_resolve_path '~/x/y.apk')" "/fake/home/x/y.apk"
# a relative path to an existing file resolves to an absolute one under its dir
got="$(cd "$FH0" && apk_resolve_path app.apk)"
check "relative existing -> abs" "$got" "$FH0/app.apk"
rm -rf "$FH0"

echo "== apk_is_split reports the split-ness =="
DS="$(mktemp -d)"; : > "$DS/base.apk"
apk_is_split "$DS/base.apk"; check "lone base -> not split (rc1)" "$?" "1"
: > "$DS/split_config.en.apk"
apk_is_split "$DS/base.apk"; check "base+split -> split (rc0)"    "$?" "0"
rm -rf "$DS"

# --- badging parse: package + launchable activity ----------------------------------------
echo "== badging parse: package + launchable-activity =="
BADGING="package: name='sg.gov.hpb.healthhub' versionCode='223' versionName='6.0.11' compileSdkVersion='35'
launchable-activity: name='sg.gov.hpb.healthhub.LauncherActivity'  label='HealthHub' icon=''
uses-permission: name='android.permission.INTERNET'"
check "package parsed"  "$(printf '%s\n' "$BADGING" | _badging_package)"  "sg.gov.hpb.healthhub"
check "activity parsed" "$(printf '%s\n' "$BADGING" | _badging_activity)" "sg.gov.hpb.healthhub.LauncherActivity"

# --- frida_server_bin resolution ---------------------------------------------------------
echo "== frida_server_bin: resolves from FRIDA_VERSION/ARCH under HOME =="
FH="$(mktemp -d)"; : > "$FH/frida-server-17.17.0-android-arm64"
got="$(HOME="$FH" FRIDA_VERSION=17.17.0 FRIDA_SERVER_ARCH=android-arm64 FRIDA_SERVER= frida_server_bin)"
check "default location" "$got" "$FH/frida-server-17.17.0-android-arm64"
got="$(FRIDA_SERVER=/custom/fs frida_server_bin)"
check "FRIDA_SERVER override wins" "$got" "/custom/fs"
rm -rf "$FH"

# --- new optional spec fields: target_apk + toggles --------------------------------------
IMG="system-images;android-37.1;google_apis_ps16k;arm64-v8a"
FAKE_SDK="$(mktemp -d)"; mkdir -p "$FAKE_SDK/${IMG//;//}"
printf 'Pkg.Revision=9\n' > "$FAKE_SDK/${IMG//;//}/source.properties"
base_spec() {  # write the 7 required keys to $1
  cat > "$1" <<YAML
name: pixel-a37
device_profile: pixel
system_image: "$IMG"
api: "37.1"
ram_mb: 4096
cores: 4
data_size_mb: 8192
YAML
}

echo "== spec: no new keys -> loads, toggles default true, target_apk empty =="
S1="$(mktemp)"; base_spec "$S1"
out="$(ANDROID_SDK_ROOT="$FAKE_SDK" bash -c '
  . "'"$ROOT"'/bin/_spec.sh"; spec_load "'"$S1"'" || exit 9
  printf "%s|%s|%s|%s|%s\n" "${SPEC_TARGET_APK-<UNSET>}" "$SPEC_PROVISION" "$SPEC_FRIDA" "$SPEC_NORMALIZE_SETTINGS" "$SPEC_HEADLESS"')"
check "defaults (headless true too)" "$out" "|true|true|true|true"
rm -f "$S1"

echo "== spec: target_apk + provision:false + headless:false honored =="
S2="$(mktemp)"; base_spec "$S2"
printf 'target_apk: "/apks/rootbeer.apk"\nprovision: false\nfrida: true\nnormalize_settings: false\nheadless: false\n' >> "$S2"
out="$(ANDROID_SDK_ROOT="$FAKE_SDK" bash -c '
  . "'"$ROOT"'/bin/_spec.sh"; spec_load "'"$S2"'" || exit 9
  printf "%s|%s|%s|%s|%s\n" "$SPEC_TARGET_APK" "$SPEC_PROVISION" "$SPEC_FRIDA" "$SPEC_NORMALIZE_SETTINGS" "$SPEC_HEADLESS"')"
check "explicit values" "$out" "/apks/rootbeer.apk|false|true|false|false"
rm -f "$S2"
rm -rf "$FAKE_SDK"

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
