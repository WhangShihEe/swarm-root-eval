# shellcheck shell=bash
# Sourced by bin/doctor. Tiny check-result library.

FAILURES=0

# Color only on a terminal.
if [ -t 1 ]; then _G=$'\033[32m'; _R=$'\033[31m'; _Z=$'\033[0m'; else _G=; _R=; _Z=; fi

pass() {  # label, detail
  printf '  %s✓%s %-14s %s\n' "$_G" "$_Z" "$1" "${2:-}"
}

fail() {  # label, reason, fix-hint
  printf '  %s✗%s %-14s %s\n' "$_R" "$_Z" "$1" "${2:-}"
  [ -n "${3:-}" ] && printf '       → %s\n' "$3"
  FAILURES=$((FAILURES + 1))
}

summary() {  # print the final verdict; return 0 iff every check passed
  echo
  if [ "$FAILURES" -eq 0 ]; then
    printf '%s✓ ready%s — all checks passed\n' "$_G" "$_Z"
    return 0
  fi
  printf '%s✗ %d check(s) failed%s — fix the → hints above\n' "$_R" "$FAILURES" "$_Z"
  return 1
}

sdk_pkg_rev() {  # $1 = package path under ANDROID_SDK_ROOT; echoes its Pkg.Revision
  local sp="$ANDROID_SDK_ROOT/$1/source.properties"
  [ -f "$sp" ] || return 1
  sed -nE 's/^Pkg\.Revision=(.*)/\1/p' "$sp"
}

# Assert a tool resolves *from the pinned SDK* and its package revision matches.
# Ties presence (PATH) and version (source.properties) to the same install, so a
# system/Homebrew binary shadowing the SDK is caught instead of silently passing.
# args: label, binary-name, package-path-under-SDK, expected-revision, install-hint
check_sdk_tool() {
  local label=$1 bin=$2 pkg=$3 want=$4 hint=$5 path rev
  path=$(command -v "$bin" 2>/dev/null) || { fail "$label" "not on PATH" "$hint"; return; }
  case "$path" in
    "$ANDROID_SDK_ROOT"/*) ;;
    *) fail "$label" "resolves to $path, not the pinned SDK" \
            "ensure $ANDROID_SDK_ROOT tools precede it on PATH (source bin/env.sh)"; return ;;
  esac
  rev=$(sdk_pkg_rev "$pkg")
  if [ "$rev" = "$want" ]; then
    pass "$label" "$rev  ($path)"
  else
    fail "$label" "revision '$rev', expected $want" "$hint"
  fi
}
