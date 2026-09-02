# 01: Toolchain bootstrap + `doctor`

**What to build:** `source bin/env.sh` puts the pinned Android SDK tools (and a JDK the
cmdline-tools can run under) on PATH, and `bin/doctor` tells you in one run whether this
machine can build the harness — every pinned binary present at the right version, `yq`
available (the harness's YAML dependency), and the rootable system image installed.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `source bin/env.sh` puts `emulator`, `avdmanager`, `sdkmanager`, `adb` on PATH resolved from `versions.txt`, and points `JAVA_HOME` at a JDK >= 17.
- [x] The `cmdline-tools` (avdmanager/sdkmanager) on PATH is a revision that **parses the image's SDK-XML v4** — pin **≥ 23.0** in `versions.txt`, **not 12.0**. A 12.0 `avdmanager` silently writes `target=android-0` into the AVD config → black-screen boot (see ticket 02 / RUNBOOK). If the SDK has both `cmdline-tools/latest` (old) and `latest-2` (new), env.sh must prefer the newest.
- [x] `bin/doctor` checks each pinned tool + `yq` + the `google_apis_ps16k;arm64-v8a;android-37.1` image and exits 0 on this host.
- [x] `bin/doctor` fails loudly if the `cmdline-tools` on PATH is too old to parse the v4 image XML (the revision that produces `target=android-0` AVDs).
- [x] A missing tool, version mismatch, or missing rootable image → non-zero exit with an actionable fix hint (e.g. the `sdkmanager` install line, `brew install yq`).
- [x] `yq` is pinned in `versions.txt` alongside the SDK/frida versions, not assumed ambient.

## Comments

**Re-implemented after requirements changed (2026-09-02).** The first pass pinned
`CMDLINE_TOOLS_REVISION=12.0` and hardcoded `cmdline-tools/latest/bin` on PATH — the
revision that writes `target=android-0` AVDs (black-screen boot). doctor was passing
by asserting that wrong pin. Delta applied:

- `versions.txt`: `CMDLINE_TOOLS_REVISION` → `CMDLINE_TOOLS_MIN_REVISION=23.0` (now a **minimum floor**, not an
  exact pin); added `YQ_VERSION=4.44.3`.
- `bin/env.sh`: selects the **newest** installed cmdline-tools by `Pkg.Revision`
  (not by directory name), so `latest-2` (23.0) wins over the stale `latest` (12.0).
- `bin/_lib.sh`: added `_ver_ge` (dotted-numeric compare) and `check_cmdline_tools`
  (floor check that **fails loudly** below the floor, naming the `target=android-0`
  black-screen consequence, reading the revision from the resolved sdkmanager's own
  cmdline-tools dir so a stale `latest` can't mask it).
- `bin/doctor`: replaced the exact sdkmanager revision check with the floor check;
  added a `yq` check (present + mikefarah v4 + `>= YQ_VERSION`).
- `tests/run.sh`: hermetic suite (fake SDK trees) covering `_ver_ge`, the
  prefer-newest pick, and the floor pass/fail + message. 11/11 pass.

Verified on this host (Apple Silicon, arm64): `bin/doctor` exits 0 with
cmdline-tools 23.0 and yq 4.53.6 (installed via `brew install yq`).
