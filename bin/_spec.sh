# shellcheck shell=bash
# Device-spec loader/validator. Sourced by bin/env-up and bin/env-down.
#
# A device-spec is the declarative YAML (devices/pixel-a37.yaml) that drives the device
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
  # api is dotted-numeric (e.g. 37.1); it becomes the target=android-<api> assertion.
  case "$SPEC_API" in
    ''|*[!0-9.]*) echo "spec: api must be numeric (e.g. 37.1), got '$SPEC_API'" >&2; return 2 ;;
  esac

  # The system image must actually be installed, else the AVD create fails deep in
  # avdmanager with a less obvious error. The SDK stores it at <root>/<path-with-/>.
  local img_path="${SPEC_SYSTEM_IMAGE//;//}"
  if [ ! -f "$ANDROID_SDK_ROOT/$img_path/source.properties" ]; then
    echo "spec: system image not installed: $SPEC_SYSTEM_IMAGE" >&2
    echo "      install it: sdkmanager \"$SPEC_SYSTEM_IMAGE\"" >&2
    return 3
  fi

  # Optional ticket-04 provisioning fields (absent in a bare ticket-03 spec, so they must
  # never be required). target_apk names the APK to install; the toggles gate provisioning
  # steps. All default on; an explicit value in the spec wins, and env-up may override
  # target_apk from --target-apk / TARGET_APK.
  SPEC_TARGET_APK=$(spec_get "$f" target_apk)
  SPEC_PROVISION=$(spec_bool "$f" provision true)
  SPEC_FRIDA=$(spec_bool "$f" frida true)
  SPEC_NORMALIZE_SETTINGS=$(spec_bool "$f" normalize_settings true)
  return 0
}

# spec_bool FILE KEY DEFAULT — echo "true"/"false" for a boolean-ish scalar. A missing/null
# or unrecognized value yields DEFAULT, so a bare spec keeps the documented defaults.
# Reads the key directly (NOT via spec_get): yq's `//` alternative operator treats a real
# boolean `false` as empty, which would silently turn an explicit `provision: false` into
# the default. `yq '.key'` returns true/false/null verbatim.
spec_bool() {
  local v; v=$(yq ".${2}" "$1" 2>/dev/null | tr '[:upper:]' '[:lower:]')
  case "$v" in
    true|1|yes|on)  echo true ;;
    false|0|no|off) echo false ;;
    *)              echo "$3" ;;
  esac
}
