# shellcheck shell=bash
# Source into your shell:  source bin/env.sh
# Puts the pinned Android SDK tools on PATH and points JAVA_HOME at a JDK the
# cmdline-tools (sdkmanager/avdmanager) can actually run under. Works in bash and zsh.

: "${ANDROID_SDK_ROOT:=$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT
export ANDROID_HOME="$ANDROID_SDK_ROOT"

# --- resolve this file's directory (bash + zsh; zsh syntax hidden from bash via eval) ---
if [ -n "${BASH_VERSION:-}" ]; then
  _env_self="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  eval '_env_self="${(%):-%x}"'
else
  _env_self="$0"
fi
# Resolve without `cd`: a chpwd/auto-ls hook in the user's shell would otherwise
# leak its output into the command substitution.
_env_dir="$(dirname "$_env_self")"
case "$_env_dir" in
  /*) ;;
  *) _env_dir="$PWD/$_env_dir" ;;
esac
HARNESS_ROOT="$(dirname "$_env_dir")"
export HARNESS_ROOT
unset _env_self _env_dir

# --- pinned versions ---
if [ -f "$HARNESS_ROOT/versions.txt" ]; then
  . "$HARNESS_ROOT/versions.txt"
else
  echo "env.sh: cannot find $HARNESS_ROOT/versions.txt — is HARNESS_ROOT correct?" >&2
fi

# --- SDK tools on PATH (prepend once) ---
for _d in emulator cmdline-tools/latest/bin platform-tools; do
  case ":$PATH:" in
    *":$ANDROID_SDK_ROOT/$_d:"*) ;;
    *) PATH="$ANDROID_SDK_ROOT/$_d:$PATH" ;;
  esac
done
export PATH
unset _d

# --- JAVA_HOME for cmdline-tools: they need JDK >= 17; the host default may be older ---
_harness_java_major() {  # $1 = candidate JAVA_HOME; echoes the major version or nothing
  [ -n "${1:-}" ] && [ -x "$1/bin/java" ] || return 1
  "$1/bin/java" -version 2>&1 | head -1 | sed -E 's/.*version "([0-9]+).*/\1/'
}
if [ "$(_harness_java_major "${JAVA_HOME:-}" 2>/dev/null || echo 0)" -lt 17 ] 2>/dev/null; then
  for _cand in \
    "/Applications/Android Studio.app/Contents/jbr/Contents/Home" \
    "$(/usr/libexec/java_home -v 17+ 2>/dev/null)" \
    "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"; do
    if [ "$(_harness_java_major "$_cand" 2>/dev/null || echo 0)" -ge 17 ] 2>/dev/null; then
      export JAVA_HOME="$_cand"
      break
    fi
  done
  unset _cand
fi
unset -f _harness_java_major 2>/dev/null || true
