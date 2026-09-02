#!/usr/bin/env bash
# Hermetic tests for ticket 01 (toolchain bootstrap + doctor).
# No network, no real SDK: builds fake cmdline-tools trees in a temp dir and asserts
# the version-compare, env.sh's "prefer the newest cmdline-tools" pick, and doctor's
# loud floor failure on the target=android-0-producing 12.0 revision.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

# Build a fake ANDROID_SDK_ROOT with a stub cmdline-tools package at a given revision.
# args: sdk_root  package_name  revision
make_ct() {
  local sdk=$1 name=$2 rev=$3 d="$1/cmdline-tools/$2"
  mkdir -p "$d/bin"
  printf 'Pkg.Revision=%s\n' "$rev" > "$d/source.properties"
  printf '#!/bin/sh\necho stub-sdkmanager\n' > "$d/bin/sdkmanager"
  printf '#!/bin/sh\nexit 0\n' > "$d/bin/avdmanager"
  chmod +x "$d/bin/sdkmanager" "$d/bin/avdmanager"
}

echo "== _ver_ge (version compare) =="
# shellcheck source=/dev/null
. "$ROOT/bin/_lib.sh"
_ver_ge "23.0" "23.0"   && ok "23.0 >= 23.0"       || bad "23.0 >= 23.0"
_ver_ge "24.0" "23.0"   && ok "24.0 >= 23.0"       || bad "24.0 >= 23.0"
_ver_ge "23"   "23.0"   && ok "23 >= 23.0"         || bad "23 >= 23.0"
_ver_ge "4.53.6" "4.44.3" && ok "4.53.6 >= 4.44.3" || bad "4.53.6 >= 4.44.3"
if _ver_ge "12.0" "23.0"; then bad "12.0 !>= 23.0"; else ok "12.0 !>= 23.0"; fi
if _ver_ge "4.44.2" "4.44.3"; then bad "4.44.2 !>= 4.44.3"; else ok "4.44.2 !>= 4.44.3"; fi

echo "== env.sh prefers the NEWEST cmdline-tools revision =="
FAKE="$(mktemp -d)"; trap 'rm -rf "$FAKE"' EXIT
make_ct "$FAKE" latest   12.0    # old, buggy (writes target=android-0)
make_ct "$FAKE" latest-2 23.0    # new
picked="$(
  ANDROID_SDK_ROOT="$FAKE" bash -c '. "'"$ROOT"'/bin/env.sh" >/dev/null 2>&1; command -v sdkmanager'
)"
case "$picked" in
  "$FAKE"/cmdline-tools/latest-2/bin/sdkmanager) ok "picked latest-2 (23.0): $picked" ;;
  *) bad "picked '$picked' — expected the 23.0 latest-2 stub" ;;
esac

# Even when only the OLD name 'latest' holds the newer revision, revision wins over name.
FAKE2="$(mktemp -d)"
make_ct "$FAKE2" latest   23.0
make_ct "$FAKE2" latest-2 12.0
picked2="$(
  ANDROID_SDK_ROOT="$FAKE2" bash -c '. "'"$ROOT"'/bin/env.sh" >/dev/null 2>&1; command -v sdkmanager'
)"
case "$picked2" in
  "$FAKE2"/cmdline-tools/latest/bin/sdkmanager) ok "revision beats name: $picked2" ;;
  *) bad "picked '$picked2' — expected the 23.0 'latest' stub" ;;
esac
rm -rf "$FAKE2"

echo "== check_cmdline_tools floor (doctor) =="
# Passes at/above the floor, fails loudly below it. Run each in a clean subshell with
# only the fake cmdline-tools on PATH so command -v resolves to the stub under the SDK.
run_ct_check() {  # sdk_root -> prints "rc:<n> out:<FAILURES>"
  ANDROID_SDK_ROOT="$1" PATH="$1/cmdline-tools/latest/bin:$PATH" bash -c '
    . "'"$ROOT"'/bin/_lib.sh"
    check_cmdline_tools 23.0 >/dev/null 2>&1
    echo "$FAILURES"'
}
GOOD="$(mktemp -d)"; make_ct "$GOOD" latest 23.0
check "23.0 passes floor" "$(run_ct_check "$GOOD")" "0"
rm -rf "$GOOD"

OLD="$(mktemp -d)"; make_ct "$OLD" latest 12.0
check "12.0 fails floor"  "$(run_ct_check "$OLD")" "1"
# and the failure message names the black-screen consequence
msg="$(ANDROID_SDK_ROOT="$OLD" PATH="$OLD/cmdline-tools/latest/bin:$PATH" bash -c '
  . "'"$ROOT"'/bin/_lib.sh"; check_cmdline_tools 23.0 2>&1')"
case "$msg" in
  *target=android-0*black-screen*) ok "failure explains target=android-0 black-screen" ;;
  *) bad "failure message lacks the api-0 explanation: $msg" ;;
esac
rm -rf "$OLD"

echo "== check_yq (doctor) =="
run_yq_check() {  # $1 = dir holding a yq stub -> prints FAILURES count
  PATH="$1:$PATH" bash -c '. "'"$ROOT"'/bin/_lib.sh"; check_yq 4.44.3 >/dev/null 2>&1; echo "$FAILURES"'
}
YQDIR="$(mktemp -d)"
printf '#!/bin/sh\necho "yq (https://github.com/mikefarah/yq/) version v4.53.6"\n' > "$YQDIR/yq"; chmod +x "$YQDIR/yq"
check "mikefarah 4.53.6 passes floor" "$(run_yq_check "$YQDIR")" "0"
printf '#!/bin/sh\necho "yq (https://github.com/mikefarah/yq/) version v4.10.0"\n' > "$YQDIR/yq"
check "mikefarah 4.10.0 fails floor"  "$(run_yq_check "$YQDIR")" "1"
printf '#!/bin/sh\necho "yq 3.4.3"\n' > "$YQDIR/yq"   # kislyuk/yq (Python) — wrong tool
check "non-mikefarah yq rejected"     "$(run_yq_check "$YQDIR")" "1"
rm -rf "$YQDIR"

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
