# Agent prompt — reconcile API references to 35 (was 37)

> Hand this to a clean-context Claude Code agent running in the swarm-root-eval repo.
> Iterate on this file; it is the source of the brief.

---

You are working in the **swarm-root-eval** repo (read `CLAUDE.md` first). We have standardized the
emulator on **API 35** — image `system-images;android-35;google_apis;arm64-v8a` (rev 9, the
rootable `google_apis` variant). The old **API 37 / `android-37.1` / `google_apis_ps16k`** setup
**failed** and is gone (`SYSTEM_IMAGE` was already migrated to android-35 in commit `f533900`;
see `.scratch/single-agent-sweep/report.md`). Stray "37" references are now stale and confusing.

Your job: **make API 35 the single, consistent story across config, docs, and tests** — but this
is NOT a blind find-and-replace. Several `37`s are legitimately not the Android API. Classify every
occurrence, change the ones that denote the target image/API, and **leave the landmines** (below),
flagging anything ambiguous for a human instead of guessing.

## The oracle: keep `bin/doctor` green
`bin/doctor` asserts the live toolchain matches `versions.txt`. After any edit to `versions.txt`,
run `source bin/env.sh && bin/doctor` — it must still exit 0. If changing a value turns doctor red,
that value was load-bearing for a real installed package (not a free-floating API label): **revert
it and report it** rather than forcing it.

## CHANGE (these denote the target image / API → make them 35 + the `google_apis` variant)
- Any `system-images;android-37.1;google_apis_ps16k;arm64-v8a` → `system-images;android-35;google_apis;arm64-v8a`.
  Note the variant also changes: `google_apis_ps16k` → `google_apis`.
- `api: "37.1"` spec values and `target=android-37.1` **assertions that describe the current
  image** → `35` / `android-35`. Example-only mentions in code comments (e.g. `bin/_spec.sh`,
  `bin/_device.sh` say "e.g. 37.1") → update the example to `35` for consistency.
- Prose in **active** docs that describes the image we run now: `RUNBOOK.md` (the rootable-image
  line, the `config.ini` `target=` guidance, the "API-37 rootable image" evidence headings),
  `docs/adr/0001-*` ("API-37 rootable image"). Reconcile these to API 35.
- Test fixtures that assert the current image string: `tests/spec.sh`, `tests/provision.sh`
  (`IMG=...`, `api "37.1"`, and the `check` expected-strings). Update to the android-35 string and
  `35`, then run them (below) — they must pass.

## DO NOT CHANGE (landmines — leave as-is, list them in your report)
- **Tool package revisions in `versions.txt`:** `EMULATOR_REVISION=37.1.11` and
  `PLATFORM_TOOLS_REVISION=37.0.1`. These are emulator / platform-tools package versions that
  happen to be numbered 37.x — NOT the Android API. Changing them breaks the toolchain.
- **`SDK_PLATFORM_API=37.1`** — INVESTIGATE, don't assume. Determine whether it names the target
  image/API (then → 35) or a separately installed SDK "platforms;android-37" package used for
  build/compile (then leave). Let `bin/doctor` decide: if setting 35 turns doctor red, it was a
  real installed platform — leave it and report.
- **The `pixel-a37` identifier** (AVD name / dir `~/.android/avd/pixel-a37.avd` / the deleted
  `devices/pixel-a37.yaml`). This is a baked-in name, not an API label; renaming it means
  recreating AVDs and touching paths. Do NOT rename it here — flag it as a separate decision.
- **Historical records of the old environment** — leave as factual history, do not rewrite:
  `docs/findings/healthhub-rasp-teardown.md` ("Android 17 (SDK 37)" — describes where that
  teardown ran), and completed tickets under `.scratch/emulator-harness/issues/*` and
  `.scratch/single-agent-sweep/` (checked-off `[x]` items documenting past state). If any actively
  mislead about the *current* setup, note them for a human rather than editing.

## Method
1. `grep -rniE '\b37\b|android-37|api.?37|37\.[0-9]|google_apis_ps16k|pixel-a37' --include='*.md'
   --include='*.txt' --include='*.yaml' --include='*.sh' --include='*.py' .` (exclude `.venv`,
   `.git`, `logs`, `apks`). Build a table: file:line → classification (CHANGE / LEAVE-landmine /
   FLAG-ambiguous).
2. Apply the CHANGE edits.
3. Verify: `source bin/env.sh && bin/doctor` (green), and `bash tests/spec.sh` + `bash
   tests/provision.sh` (or however the repo runs them) pass. Also `swarm-eval/.venv/bin/python -m
   pytest -q` for the Python side.
4. If a change turns doctor/tests red, revert that one and move it to the FLAG list.

## Deliverable
- The clear-cut edits applied, with doctor + tests green.
- A short list in your final message (or `.scratch/env-hardening/api-35-cleanup-notes.md`) of every
  LEAVE-landmine and FLAG-ambiguous occurrence with a one-line reason — especially `SDK_PLATFORM_API`,
  `pixel-a37`, and any historical record you judged should stay. These are the human's to decide.
