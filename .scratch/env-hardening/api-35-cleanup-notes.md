# API-35 cleanup — notes (2026-09-22)

Reconciled stray API-37 references to the standardized emulator image
`system-images;android-35;google_apis;arm64-v8a` (rev 9). `bin/doctor` stays green (exit 0);
`tests/spec.sh` (19 passed), `tests/provision.sh` (21 passed), and `swarm-eval` pytest (149
passed, run from `swarm-eval/`) all pass.

## CHANGED (clear-cut)
- `bin/_spec.sh` — comment + error-message example `e.g. 37.1` → `e.g. 35` (×2).
- `bin/_device.sh` — comment example `e.g. android-37.1` → `e.g. android-35`.
- `tests/provision.sh` — `IMG=` image string → android-35;google_apis; `api: "37.1"` → `"35"`.
- `tests/spec.sh` — `IMG=` string; `api: "37.1"` → `"35"`; SPEC_* expected `|37.1|` → `|35|`;
  `target=android-37.1` fixture + two `avd_target` assertions → `android-35`.
- `RUNBOOK.md` — rootable-image line (image string, variant `google_apis_ps16k`→`google_apis`);
  L29 correct-target guidance; L70 `MUST show target=` guard comment; L80 guard prose;
  L193 evidence heading "API-37 rootable image" → "API-35".
- `docs/adr/0001-*` — "API-37 rootable image" → "API-35".

## LEAVE — landmines (NOT the Android API)
- `versions.txt:9  EMULATOR_REVISION=37.1.11` — emulator package rev; matches installed, doctor-checked.
- `versions.txt:10 PLATFORM_TOOLS_REVISION=37.0.1` — platform-tools (adb) package rev; installed, doctor-checked.
- `pixel-a37` (AVD name / `~/.android/avd/pixel-a37.avd` / `devices/pixel-a37.yaml`) — baked-in
  identifier, not an API label. Occurs in RUNBOOK, CONTEXT.md:52, bin/_spec.sh:4, tests/spec.sh
  (31,48,109), tests/provision.sh:92. Renaming means recreating AVDs + path edits — a separate
  human decision.

## LEAVE — historical records (factual history of the old env)
- `docs/findings/healthhub-rasp-teardown.md:13,116` — "Android 17 (SDK 37)"; records where that
  teardown actually ran. Explicitly preserve.
- `.scratch/emulator-harness/issues/*` and `.scratch/single-agent-sweep/*` — checked-off `[x]`
  tickets + sweep report documenting past state (incl. `f533900` note that doctor once blessed 37.1).

## FLAG — ambiguous, human's call
- **`versions.txt:6  SDK_PLATFORM_API=37.1`** — LEFT AS-IS. `bin/doctor` does NOT read this var
  (it checks only EMULATOR_REVISION, PLATFORM_TOOLS_REVISION, SYSTEM_IMAGE), so the oracle cannot
  adjudicate it — setting 35 would NOT turn doctor red, but that greenness is meaningless here.
  Evidence it is a *build/compile SDK platform*, not the emulator image: installed SDK platforms
  are `android-26/27/34/37.0` with **no android-35 platform**; the emulator image is tracked
  separately by `SYSTEM_IMAGE` (android-35). Note the value `37.1` doesn't even match the
  installed `platforms;android-37.0`. Recommend: decide whether this names a real installed
  platform package (leave, ideally correct to the installed `37.0` or drop if unused since nothing
  reads it) vs. a stale image label (→ 35). Do not blind-set to 35 (no android-35 platform is installed).

- **RUNBOOK.md:33, :40, :178** — LEFT AS-IS. Dated/"verified"/"Confirmed (2026-09-01)"
  observations captured on the *old 37.1 image*: L33 the created config's `target=android-37.1`
  **and `tag.ids=google_apis,page_size_16kb`** (the `page_size_16kb` tag is the retired ps16k
  variant); L40 `target=android-37.1` alongside the `Boot completed in 13077 ms` measurement;
  L178 table cell `target=android-37.1 (verified)`. Rewriting these to android-35 would fabricate
  measurements never taken on android-35. This leaves RUNBOOK internally inconsistent (L20/L193
  now say android-35; the GOTCHA block + table still say 37.1). Recommend: re-verify the AVD
  create/boot on android-35 (expected `target=android-35`, `tag.ids=google_apis`, no
  `page_size_16kb`) and then update these lines with the real android-35 numbers.

- **`.scratch/physical-harness/spec.md:18`** — LEFT AS-IS. "Google Pixel 7 (panther), Android 17
  / SDK 37" describes a *physical device* target for a separate (untracked) physical-harness
  effort, not the emulator image. Different context; confirm intent before touching.
