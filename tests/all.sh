#!/usr/bin/env bash
# Run every hermetic test suite under tests/ (each tests/<name>.sh except this runner).
# No network, no real SDK/emulator. Exits non-zero if any suite fails.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fails=0
for suite in "$HERE"/*.sh; do
  case "$(basename "$suite")" in all.sh) continue ;; esac
  printf '\n### %s\n' "$(basename "$suite")"
  bash "$suite" || fails=$((fails + 1))
done

echo
if [ "$fails" -eq 0 ]; then
  echo "ALL SUITES PASSED"
else
  echo "$fails SUITE(S) FAILED"
fi
[ "$fails" -eq 0 ]
