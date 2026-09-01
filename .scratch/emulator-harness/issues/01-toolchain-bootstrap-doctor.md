# 01: Toolchain bootstrap + `doctor`

**What to build:** `source bin/env.sh` puts the pinned Android SDK tools on PATH, and
`bin/doctor` tells you in one run whether this machine can build the harness — every pinned
binary present at the right version and the rootable system image installed.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `source bin/env.sh` puts `emulator`, `avdmanager`, `sdkmanager`, `adb` on PATH, resolved from `versions.txt`.
- [x] `bin/doctor` checks each pinned tool + the `google_apis_ps16k;arm64-v8a;android-37.1` image and exits 0 on this host.
- [x] A missing tool, version mismatch, or missing rootable image → non-zero exit with an actionable fix hint (e.g. the `sdkmanager` install line).

## Comments

**Implemented (2026-09-01).** Files: `versions.txt`, `bin/env.sh`, `bin/_lib.sh`, `bin/doctor`.
`bin/doctor` prints 7 checks (java, emulator, adb, sdkmanager, avdmanager, frida, system-image)
and exits 0 here; a fake `ANDROID_SDK_ROOT` and a forced version mismatch both give non-zero
with per-check `→` hints.

Notable findings while building against the live host — worth carrying into later tickets:

- **`versions.txt` was stale on 3 pins.** Corrected to the revisions actually installed
  (read from each package's `source.properties` `Pkg.Revision`): emulator `36.1.9 → 37.1.11`,
  platform-tools `36.0.0 → 37.0.1`, cmdline-tools `19.0 → 12.0`.
- **cmdline-tools need JDK ≥ 17.** The host default `java` is Temurin 11, under which
  `sdkmanager`/`avdmanager` throw `UnsupportedClassVersionError` (class 61 vs 55). `env.sh`
  now discovers a JDK ≥ 17 (Android Studio's bundled JBR = 25 here) and exports `JAVA_HOME`
  so the SDK tools run. **T1.3 (avdmanager create) depends on this** — it will hit the same
  Java wall without a sourced `env.sh`.
- **`sdkmanager --version` output is unreliable** — it prints `12.0` to a terminal or a pipe
  to `cat`, but *nothing* when redirected to a file or piped to `tail`. Doctor reads the
  cmdline-tools revision from `source.properties` instead, and uses `avdmanager list target`
  (rc 0 under JDK 17+, rc 1 under JDK 11) as the JDK-compat canary.
- **The user's zsh has a `chpwd`/auto-`ls` hook** that leaks a dir listing into any
  `$(cd … && pwd)`. `env.sh` resolves `HARNESS_ROOT` without `cd` to stay clean when sourced
  interactively. (Also: `cp`/`rm` are aliased to `-i` in that shell.)
- The image repo is XML v4 but cmdline-tools 12.0 only understands v3, so SDK commands emit
  harmless `Warning:` lines to stderr — doctor discards stderr on its checks.

**Reviewed & hardened (2026-09-01).** `/code-review` (Standards + Spec axes) run; fixes folded in:
- `bin/doctor` now ties presence to version via `check_sdk_tool` — a system/Homebrew binary
  shadowing the pinned SDK is caught (was a false green before).
- Enforces `SYSTEM_IMAGE_REVISION` (was displayed but unchecked); reuses `sdk_pkg_rev`.
- Prints the resolved path for every tool (acceptance: "lists resolved paths").
- Install hints per tool (were all a no-op "source env.sh").
- Guards: JDK check no longer captures the exec error into `$jver` when `JAVA_HOME` is unset;
  `env.sh` guards a missing `versions.txt`.
- `summary()` moved into `bin/_lib.sh` (doctor no longer reaches into its private color vars).

Declined: renaming `versions.txt` (spec names it); repointing `CLAUDE.md`/removing `tickets/`
(the horizontal set-1 reference is intentional per BACKLOG, not a duplicate).
