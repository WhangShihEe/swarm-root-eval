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

# Dotted-numeric version compare. Returns 0 (true) iff version $1 >= version $2.
# Missing trailing components count as 0, so "23" >= "23.0" and "4.53.6" >= "4.44.3".
# NOTE: bin/env.sh keeps a private one-line copy of this (it is sourced into the shell
# before _lib.sh exists, then unsets it) — keep the two in sync.
_ver_ge() {
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,x,"."); nb=split(b,y,".");
    m=(na>nb)?na:nb;
    for(i=1;i<=m;i++){ ai=(i<=na)?x[i]+0:0; bi=(i<=nb)?y[i]+0:0;
      if(ai>bi) exit 0; if(ai<bi) exit 1 }
    exit 0 }'
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

# cmdline-tools (sdkmanager/avdmanager) must be new enough to parse the image's
# SDK-XML v4. Unlike the other tools this is a *floor*, not an exact pin: revision
# 12.0 silently writes target=android-0 into the AVD -> black-screen boot (RUNBOOK /
# ticket 02), so anything below the floor must fail loudly. Reads the revision from
# the cmdline-tools directory the resolved sdkmanager actually lives in — so it can't
# be fooled by a stale cmdline-tools/latest sitting beside a newer latest-2.
# args: min-revision-floor
check_cmdline_tools() {
  local want=$1 path dir rev
  path=$(command -v sdkmanager 2>/dev/null) \
    || { fail cmdline-tools "sdkmanager not on PATH" \
              "install 'Android SDK Command-line Tools' (>= $want) via SDK Manager, then: source bin/env.sh"; return; }
  case "$path" in
    "$ANDROID_SDK_ROOT"/*) ;;
    *) fail cmdline-tools "sdkmanager resolves to $path, not the pinned SDK" \
            "ensure $ANDROID_SDK_ROOT tools precede it on PATH (source bin/env.sh)"; return ;;
  esac
  dir=$(dirname "$(dirname "$path")")   # .../cmdline-tools/<name>
  rev=$(sed -nE 's/^Pkg\.Revision=(.*)/\1/p' "$dir/source.properties" 2>/dev/null)
  if [ -z "$rev" ]; then
    fail cmdline-tools "cannot read revision at $dir" \
         "reinstall cmdline-tools (>= $want) via SDK Manager"; return
  fi
  if _ver_ge "$rev" "$want"; then
    pass cmdline-tools "$rev  ($path)"
  else
    fail cmdline-tools "revision $rev is too old to parse the v4 image XML — it writes target=android-0 -> black-screen boot" \
         "install/update cmdline-tools to >= $want via the SDK Manager; env.sh prefers the newest, so re-run: source bin/env.sh"
  fi
}

# yq — the harness's YAML dependency (mikefarah yq, v4 API). Ambient dev tool, not an
# SDK package; pinned as a floor in versions.txt. Asserts it is actually *mikefarah* yq
# (kislyuk/yq is a different Python tool with an incompatible CLI) and at/above the floor.
# args: min-version-floor
check_yq() {
  local want=$1 path vline ver
  path=$(command -v yq 2>/dev/null) \
    || { fail yq "not found (the harness parses YAML with yq)" \
              "brew install yq   # mikefarah yq >= $want"; return; }
  vline=$(yq --version 2>/dev/null)
  case "$vline" in
    *mikefarah*) ;;
    *) fail yq "'$path' is not mikefarah yq (got: ${vline:-no version output})" \
            "the harness needs mikefarah yq, not the Python kislyuk/yq: brew install yq"; return ;;
  esac
  ver=$(printf '%s\n' "$vline" | sed -nE 's/.*version v?([0-9]+\.[0-9]+(\.[0-9]+)?).*/\1/p')
  if [ -z "$ver" ]; then
    fail yq "found at $path but could not read its version" \
         "install mikefarah yq >= $want: brew install yq"
  elif _ver_ge "$ver" "$want"; then
    pass yq "$ver  ($path)"
  else
    fail yq "version $ver < required $want" "upgrade mikefarah yq: brew upgrade yq"
  fi
}
