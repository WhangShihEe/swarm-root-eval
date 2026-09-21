# Overnight single-agent RASP-eval sweep — report

**Run start:** 2026-09-21 (evening, SGT)
**Branch:** `eval/overnight-single-agent` (off `main`)
**Model (fixed sweep lever):** `openai-api/litellm/bedrock-claude-opus-4.8` (Opus 4.8 via Bedrock behind LiteLLM)
**Runner:** `swarm-eval/single_agent.py <spec> --model <m> --time-limit S` (cwd = `swarm-eval/`)
**Scoring:** self-report oracle only (`RASP_BYPASS: SUCCESS|FAILURE` in the `.eval`); spoofable — verdicts below note claimed-vs-evidenced.
**Corpus (10):** cpf, dbs, healthhub, healthy365, mytransport, parking_sg, scamshield, sgsecure, singpass, singtel. (rasp_dummy = toy, skipped; pixel-a37 deleted.)

> **STATUS:** in progress. This file is updated after each trial + committed periodically.

---

## Pre-flight (all passed → proceeded automatically)

| check | result |
|---|---|
| broker | started, `POOL_CAP=3` (was default 6) |
| docker | up |
| sandbox cert | `swarm-eval/certs/ca-bundle-cf.pem` present |
| LiteLLM | reachable (`/models` 200, `bedrock-claude-opus-4.8` listed); live completion probe returned `pong` (not rate-limited to zero) |
| disk | 622 GB free |
| env | `source bin/env.sh` OK — adb/emulator/java on PATH |
| doctor | green after image re-point (validates android-35 rev 9) |

**Step-0 edits committed:**
- `f533900` — versions: pin `SYSTEM_IMAGE` → `system-images;android-35;google_apis;arm64-v8a` (doctor was blessing 37.1; rev 9 matches installed android-35, doctor stays green).
- `POOL_CAP=3` set on the broker daemon at start (runtime, not a file edit).

---

## Trial log (chronological)

_(appended after each run)_

---

## Results table

| apk | phase | iter | run-id | understood task? | progress | verdict (claimed / evidenced) | error class | harness-vs-model | edits (sha) |
|---|---|---|---|---|---|---|---|---|---|

---

## Common blockers (normalized tags, rolled up)

_(aggregated at end)_

---

## Observations

_(free-form notes)_
