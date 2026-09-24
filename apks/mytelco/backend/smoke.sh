#!/usr/bin/env bash
#
# smoke.sh — start the backend, run a full login -> OTP -> /me/account flow,
# prove missing-token is rejected, then stop the server.
#
# Usage: ./smoke.sh   (run from the backend/ directory; needs `npm install` first)

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8090}"
BASE="http://127.0.0.1:${PORT}"
LOGIN_ID="weiming.tan@gmail.com"
PASSWORD="Passw0rd!"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required" >&2; exit 1; }; }
need node
need curl

# jq is optional (nicer output); fall back to raw if absent.
if command -v jq >/dev/null 2>&1; then PP="jq ."; else PP="cat"; fi

echo "==> Starting server on port ${PORT}..."
PORT="$PORT" node server.js &
SERVER_PID=$!
trap 'echo "==> Stopping server (pid ${SERVER_PID})"; kill "$SERVER_PID" 2>/dev/null || true' EXIT

# Wait for the server to accept connections.
for i in $(seq 1 30); do
  if curl -sf "${BASE}/health" >/dev/null 2>&1; then break; fi
  sleep 0.2
  if [ "$i" -eq 30 ]; then echo "ERROR: server did not start" >&2; exit 1; fi
done
echo "    server is up."

echo
echo "==> 1) POST /login"
LOGIN_RESP="$(curl -s -X POST "${BASE}/login" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"${LOGIN_ID}\",\"password\":\"${PASSWORD}\"}")"
echo "$LOGIN_RESP" | eval "$PP"
PRE_TOKEN="$(echo "$LOGIN_RESP" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).token))')"

echo
echo "==> 2) POST /login/verify-otp (cosmetic OTP 123456)"
OTP_RESP="$(curl -s -X POST "${BASE}/login/verify-otp" \
  -H 'Content-Type: application/json' \
  -d "{\"token\":\"${PRE_TOKEN}\",\"otp\":\"123456\"}")"
echo "$OTP_RESP" | eval "$PP"
TOKEN="$(echo "$OTP_RESP" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).token))')"

echo
echo "==> 3) GET /me/account WITH token (should return Tan Wei Ming's data)"
curl -s "${BASE}/me/account" -H "Authorization: Bearer ${TOKEN}" | eval "$PP"

echo
echo "==> 4) GET /me/account WITHOUT token (should be 401)"
curl -s -o /dev/null -w "    HTTP status: %{http_code}\n" "${BASE}/me/account"

echo
echo "==> Smoke test complete."
