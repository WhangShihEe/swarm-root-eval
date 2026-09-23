# shellcheck shell=bash
# Device-spec loader/validator. Sourced by bin/env-up and bin/env-down.
#
# A device-spec is the declarative YAML (configs/devices/<name>.yaml) that drives the device
# layer — the harness is spec-driven from the first line, nothing about the device is
# hardcoded in the scripts (CONTEXT.md: "Device-spec"). Parsed with mikefarah `yq` v4,
# the harness's pinned YAML dependency (doctor asserts it).
#
# spec_load validates a spec and exports SPEC_* for the caller; spec_name reads just the
# name (teardown must work even when the image is no longer installed, so it does NOT run
# full validation).

# Required top-level scalar keys, in report order.
_SPEC_KEYS="name device_profile system_image api ram_mb cores data_size_mb"

# spec_get FILE KEY — echo the scalar value, or empty for a missing/null key.
spec_get() { yq "(.${2}) // \"\"" "$1" 2>/dev/null; }

# spec_target_apk FILE — echo the spec's target_apk (empty for a missing/null key). NOT part
# of spec_load: the bring-up scripts (env-up and friends) no longer read the APK from the spec
# (ticket 01, apk-agnostic prefactor) — the APK is passed explicitly to the device layer. This
# getter is for a *caller* (the pool/broker provisioning path, bin/verify) that still sources
# the APK from the current spec and hands it to the device layer via --target-apk.
spec_target_apk() { spec_get "$1" target_apk; }

# spec_name FILE — echo just the .name (no full validation). Used by teardown.
spec_name() {
  [ -f "$1" ] || return 1
  local n; n=$(spec_get "$1" name)
  [ -n "$n" ] && printf '%s\n' "$n"
}

# spec_load FILE — validate and, on success, set:
#   SPEC_NAME SPEC_DEVICE_PROFILE SPEC_SYSTEM_IMAGE SPEC_API SPEC_RAM_MB SPEC_CORES SPEC_DATA_SIZE_MB
# Returns 0 on success; on any problem prints an actionable error to stderr and returns
# non-zero (2 = bad/missing spec, 3 = image not installed).
spec_load() {
  local f=$1 k v missing= var
  [ -n "$f" ] || { echo "spec: no spec file given (use --spec <file>)" >&2; return 2; }
  [ -f "$f" ] || { echo "spec: file not found: $f" >&2; return 2; }
  command -v yq >/dev/null 2>&1 \
    || { echo "spec: yq not on PATH — source bin/env.sh; brew install yq" >&2; return 2; }
  # Must parse as a YAML map, else every key would read empty and we'd blame the keys.
  if [ "$(yq 'type' "$f" 2>/dev/null)" != "!!map" ]; then
    echo "spec: $f is not a valid YAML mapping" >&2
    echo "      check it parses: yq . $f" >&2
    return 2
  fi

  for k in $_SPEC_KEYS; do
    v=$(spec_get "$f" "$k")
    if [ -z "$v" ]; then missing="$missing $k"; continue; fi
    var="SPEC_$(printf '%s' "$k" | tr '[:lower:]' '[:upper:]')"
    printf -v "$var" '%s' "$v"
  done
  if [ -n "$missing" ]; then
    echo "spec: $f is missing required key(s):$missing" >&2
    echo "      required keys: $_SPEC_KEYS" >&2
    return 2
  fi

  # Numeric fields must be positive integers (they land in config.ini / launch flags).
  for k in ram_mb cores data_size_mb; do
    var="SPEC_$(printf '%s' "$k" | tr '[:lower:]' '[:upper:]')"
    case "${!var}" in
      ''|*[!0-9]*) echo "spec: $k must be a positive integer, got '${!var}'" >&2; return 2 ;;
      0) echo "spec: $k must be > 0" >&2; return 2 ;;
    esac
  done
  # api is dotted-numeric (e.g. 35); it becomes the target=android-<api> assertion.
  case "$SPEC_API" in
    ''|*[!0-9.]*) echo "spec: api must be numeric (e.g. 35), got '$SPEC_API'" >&2; return 2 ;;
  esac

  # The system image must actually be installed, else the AVD create fails deep in
  # avdmanager with a less obvious error. The SDK stores it at <root>/<path-with-/>.
  local img_path="${SPEC_SYSTEM_IMAGE//;//}"
  if [ ! -f "$ANDROID_SDK_ROOT/$img_path/source.properties" ]; then
    echo "spec: system image not installed: $SPEC_SYSTEM_IMAGE" >&2
    echo "      install it: sdkmanager \"$SPEC_SYSTEM_IMAGE\"" >&2
    return 3
  fi

  # Optional ticket-04 provisioning toggles (absent in a bare ticket-03 spec, so they must
  # never be required). The toggles gate provisioning steps; all default on, an explicit value
  # in the spec wins.
  #
  # ticket 01 (apk-agnostic prefactor): the device-layer loader deliberately does NOT read the
  # APK. `target_apk` is no longer part of `spec_load` — the bring-up path (env-up) takes the APK
  # explicitly (--apk/--target-apk), and a *caller* that still sources the APK from the spec uses
  # the `spec_target_apk` getter below to resolve it and hand it over. This decouples "the
  # emulator" (provisioning scalars) from "the app under test" (the APK) in the bring-up scripts.
  SPEC_PROVISION=$(spec_bool "$f" provision true)
  SPEC_FRIDA=$(spec_bool "$f" frida true)
  SPEC_NORMALIZE_SETTINGS=$(spec_bool "$f" normalize_settings true)
  SPEC_HEADLESS=$(spec_bool "$f" headless true)   # false -> env-up boots with a window

  # ticket 07: the launch profile. writable_system is the full definition of how the device
  # comes up — absent means true (the writable-/system profile is the default); false selects
  # the Frida-only profile. Unlike the lenient provisioning toggles above, a present-but-
  # non-boolean value is a spec error (the launch profile must be unambiguous), rejected here.
  if ! SPEC_WRITABLE_SYSTEM=$(spec_bool_strict "$f" writable_system true); then
    echo "spec: writable_system must be a boolean (true/false), got '$(yq '.writable_system' "$f" 2>/dev/null)'" >&2
    return 2
  fi
  return 0
}

# spec_bool_strict FILE KEY DEFAULT — normalize a boolean-ish scalar, distinguishing
# "absent" from "invalid": an absent/null key echoes DEFAULT (rc 0); a recognized boolean
# echoes its normalized value (rc 0); a present-but-unrecognized value echoes nothing and
# returns 1, so the caller can reject the whole spec. Used for the launch-profile flag,
# which must not silently fall back to a default when someone typos it (ticket 07).
# Reads the key directly (NOT via spec_get): yq's `//` alternative operator treats a real
# boolean `false` as empty, which would conflate an explicit `false` with "absent".
# `yq '.key'` returns true/false/null verbatim.
spec_bool_strict() {
  local v; v=$(yq ".${2}" "$1" 2>/dev/null | tr '[:upper:]' '[:lower:]')
  case "$v" in
    null|'')        echo "$3"; return 0 ;;
    true|1|yes|on)  echo true;  return 0 ;;
    false|0|no|off) echo false; return 0 ;;
    *)              return 1 ;;
  esac
}

# spec_bool FILE KEY DEFAULT — the lenient variant: echo "true"/"false", with a missing/null
# OR unrecognized value all yielding DEFAULT (a bare spec keeps the documented defaults, and
# a typo'd provisioning toggle degrades to the default rather than aborting). Layered on the
# strict primitive: an invalid value trips its rc 1, and `|| echo "$3"` supplies the default.
spec_bool() { spec_bool_strict "$1" "$2" "$3" || echo "$3"; }
