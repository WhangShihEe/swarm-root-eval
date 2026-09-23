#!/usr/bin/env bash
# Hermetic tests for env-hardening ticket 05 (configured egress CA on the device).
# No network, no real emulator/adb: exercises the *host-side* CA helpers in bin/_device.sh
# (device_ca_dir / device_ca_files / device_ca_stage) and PROVES the no-cert path is a clean
# no-op that never touches the device. The on-device APEX install itself (bind-mounting over
# /apex/com.android.conscrypt/cacerts) is validated by the orchestrator against a real boot.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

# shellcheck source=/dev/null
. "$ROOT/bin/_device.sh"

command -v openssl >/dev/null 2>&1 || { echo "openssl required for these tests"; exit 2; }

# --- device_ca_dir: default location + override ------------------------------------------
echo "== device_ca_dir: gitignored certs location, overridable =="
check "default is swarm-eval/certs" "$(HARNESS_ROOT=/x DEVICE_CA_DIR= device_ca_dir)" "/x/swarm-eval/certs"
check "DEVICE_CA_DIR overrides"      "$(DEVICE_CA_DIR=/tmp/mycerts device_ca_dir)"      "/tmp/mycerts"

# --- device_ca_files: empty when no cert (the no-op gate) ---------------------------------
echo "== device_ca_files: empty ⇒ no CA on this host (no-op gate) =="
EMPTY="$(mktemp -d)"
check "missing dir ⇒ empty"  "$(device_ca_files "$EMPTY/nope" | grep -c .)" "0"
check "empty dir ⇒ empty"    "$(device_ca_files "$EMPTY"      | grep -c .)" "0"
rm -rf "$EMPTY"

# --- device_ca_files + device_ca_stage: a supplied CA is found and hashed -----------------
echo "== a supplied CA is discovered and staged as <hash>.N =="
CERTS="$(mktemp -d)"
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$CERTS/egress-ca.pem" \
  -subj "/CN=Test Egress CA/O=harness" -days 2 >/dev/null 2>&1
check "one cert file discovered" "$(device_ca_files "$CERTS" | grep -c .)" "1"
STAGE="$(mktemp -d)"
n="$(device_ca_stage "$CERTS" "$STAGE")"
check "staged exactly one cert"  "$n" "1"
staged_name="$(ls "$STAGE")"
case "$staged_name" in
  [0-9a-f]*.0) ok "staged filename is <subject_hash_old>.0: $staged_name" ;;
  *) bad "staged filename not <hash>.0: $staged_name" ;;
esac
# The staged file carries the PEM cert (AOSP cacerts format = cert + text dump).
check "staged file holds the PEM cert" \
  "$(grep -c 'BEGIN CERTIFICATE' "$STAGE/$staged_name")" "1"
# The hash in the filename matches openssl's subject_hash_old for that cert.
want_hash="$(openssl x509 -subject_hash_old -noout -in "$CERTS/egress-ca.pem")"
check "filename hash matches openssl" "$staged_name" "$want_hash.0"
rm -rf "$CERTS" "$STAGE"

# --- device_ca_stage: a bundle of many certs is split into many staged files --------------
echo "== a bundle (many PEM blocks) stages one file per cert =="
BDIR="$(mktemp -d)"
for cn in AlphaCA BetaCA GammaCA; do
  openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null \
    -subj "/CN=$cn" -days 2 >> "$BDIR/ca-bundle.pem" 2>/dev/null
done
BSTAGE="$(mktemp -d)"
bn="$(device_ca_stage "$BDIR" "$BSTAGE")"
check "3-cert bundle stages 3 files" "$bn" "3"
check "3 files on disk"              "$(ls "$BSTAGE" | grep -c .)" "3"
rm -rf "$BDIR" "$BSTAGE"

# --- THE NO-OP PROOF: device_ca_install with no cert returns 0 and never calls adb --------
echo "== device_ca_install: NO cert ⇒ clean no-op, device untouched (exit 0, no adb) =="
NOCERT="$(mktemp -d)"          # an empty CA dir ⇒ no cert supplied
STUBBIN="$(mktemp -d)"
# A stub `adb` that records the fact it was invoked. If the no-op path is clean it is NEVER run.
cat > "$STUBBIN/adb" <<'EOF'
#!/bin/sh
echo "adb-was-called $*" >> "$ADB_CALL_LOG"
exit 0
EOF
chmod +x "$STUBBIN/adb"
ADB_CALL_LOG="$STUBBIN/calls.log"; : > "$ADB_CALL_LOG"
(
  export PATH="$STUBBIN:$PATH" DEVICE_CA_DIR="$NOCERT" ADB_CALL_LOG
  # shellcheck source=/dev/null
  . "$ROOT/bin/_device.sh"
  device_ca_install emulator-5554
)
rc=$?
check "no-cert install exits 0"      "$rc" "0"
check "no-cert install never ran adb" "$(wc -l < "$ADB_CALL_LOG" | tr -d ' ')" "0"
rm -rf "$NOCERT" "$STUBBIN"

# --- APEX targeting: the install targets the Conscrypt APEX store, not just legacy --------
echo "== install targets the Conscrypt APEX store (not legacy cacerts alone) =="
if printf '%s' "$_DEVICE_CA_APEX_SCRIPT" | grep -q '/apex/com.android.conscrypt/cacerts'; then
  ok "code references the Conscrypt APEX cacerts path"
else
  bad "code does not reference the APEX cacerts path"
fi
if printf '%s' "$_DEVICE_CA_APEX_SCRIPT" | grep -q 'mount --bind .*APEX'; then
  ok "bind-mounts the assembled set over the APEX store"
else
  bad "does not bind-mount over the APEX store"
fi

echo
printf 'tests: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
