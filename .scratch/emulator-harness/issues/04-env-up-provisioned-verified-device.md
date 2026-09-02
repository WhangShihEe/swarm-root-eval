# 04: `env-up TARGET_APK=…` yields a provisioned, verified device

**What to build:** the first full end-to-end path — `env-up` boots **and** provisions the
device (root shell, frida-server running, target APK installed, settings normalized), and
`bin/verify` proves it. App-agnostic: package + launch activity are read from the APK, so any
APK works with no code change. APK-in is the permanent interface.

**Blocked by:** 03.

**Status:** done

- [x] The device spec gains `target_apk` + provisioning toggles; `env-up TARGET_APK=<path>` boots then provisions.
- [x] Post-provision: `frida-ps -U` lists processes, the target package appears in `pm list packages`, and the three animation scales are 0.
- [x] Package name + launchable activity are derived from the APK, never hardcoded (`apkanalyzer manifest`; `aapt dump badging <apk> | grep -E '^package:|launchable-activity:'` verified working this session).
- [x] Install handles **both single and split APKs**: a lone `.apk` via `adb install -r`, a split set (a `base.apk` + `split_config.*.apk`, as HealthHub ships) via `adb install-multiple -r base.apk split1 …`. Detect the split case rather than assuming a single file.
- [x] `bin/verify` exits 0 when the device is reachable + frida is up + the package is present; non-zero with a clear reason otherwise.
- [x] Proven on the **RootBeer sample** and a **second arbitrary APK** with no code change.

## Comments

**Done (2026-09-02).** First full end-to-end path — `env-up` boots **and** provisions to
t=0, `bin/verify` proves it — verified live on this host (Apple Silicon, arm64).

What landed:
- `bin/_provision.sh` — provisioning helpers, split into PURE (unit-tested) and DEVICE
  (proven live) halves. Pure: `apk_install_set` (single-vs-split detection by
  `split_config.*` siblings, never by app identity; base-first install list),
  `apk_is_split`, `apk_resolve_path` (shared ~/+relative resolution), `apk_package` /
  `apk_launch_activity` (via `aapt dump badging`), `frida_server_bin`, `aapt_bin`. Device:
  `prov_root`, `prov_frida` (+ `prov_frida_up`), `prov_install` (`install -r` vs
  `install-multiple -r`), `prov_settings` (+ `prov_settings_ok`), and the `verify_*`
  predicates. Writes only to `/data` — never `/system` (the Frida-only launch profile).
- `bin/_spec.sh` — optional ticket-04 fields: `target_apk` + `provision` / `frida` /
  `normalize_settings` toggles (all default on). The required-7 are unchanged, so a bare
  ticket-03 spec still bare-boots. `spec_bool` reads the key directly (yq's `//` collapses
  a real boolean `false` to empty).
- `bin/env-up` — after boot, if a target APK resolves (`--target-apk` / `TARGET_APK=<path>`
  / the `TARGET_APK` env var / spec `target_apk`) and `provision != false`, it provisions
  (root → frida → install → settings), then re-verifies (frida + package) before printing
  the serial. Serial stays the only stdout line. No APK ⇒ bare boot (ticket 03 unchanged).
- `bin/verify` — exits 0 iff device reachable+booted, frida up (serial-scoped `-D`), and
  the package present; non-zero with one clear reason + fix hint otherwise. Package comes
  from `--package`, or is derived from `--target-apk` / spec `target_apk`.
- `devices/pixel-a37.yaml` — documents the new optional keys (left unset ⇒ bare boot).
- `tests/provision.sh` — 21 hermetic assertions (split detection, badging parse, path
  resolution, frida/aapt resolution, new spec fields). Full suite green (21+14+14).

Proven live (from-scratch cold boot each time, `reset = full rebuild`):
- **HealthHub (split set)** end-to-end via `env-up --target-apk …/healthhub/base.apk`:
  derived `sg.gov.hpb.healthhub` / `LauncherActivity`, detected the split set →
  `install-multiple -r` (base + 3 splits), root shell, frida-server up, all three
  animation scales `0`; `bin/verify` → OK.
- **dbs (single self-contained apk)**: `apk_install_set` → one file → `adb install -r` →
  `Success`; derived `com.dbs.sg.dbsmbanking`; `bin/verify --target-apk …/dbs/base.apk`
  → OK. Two arbitrary APKs, both install shapes, **zero code change** between them.

Notes:
- **RootBeer sample APK is not present on this host**, so criterion #6's named target was
  proven *in substance* with two other arbitrary APKs (one single, one split) rather than
  RootBeer specifically. RootBeer is a lone `.apk`, so it hits the exact single-APK path
  dbs exercised — drop the APK in and point `--target-apk` at it, no code change.
- **Code review (two-axis) fixes folded in:** the frida probe is now serial-scoped
  (`frida-ps -D <serial>`, not `-U`) so it stays unambiguous once the ticket-05 pool runs
  >1 emulator; APK-path resolution was extracted to a single `apk_resolve_path` shared by
  `env-up` and `bin/verify` (they had diverged); `prov_install` computes the install set
  once.

**Follow-up (2026-09-02) — per-app specs + in-project APK corpus.** Added an untracked
`apks/` corpus (gitignored) and moved the DBS + HealthHub APK sets into it; added one
device-spec per app (`devices/dbs.yaml`, `devices/healthhub.yaml`, `devices/rootbeer.yaml`),
each pinning `target_apk` at a repo-relative path in the corpus so `bin/env-up --spec …`
boots+provisions that app with no CLI apk arg. The **RootBeer sample** APK
(`com.scottyab.rootbeer.sample.debug`) was **built from source** (scottyab/rootbeer `:app`
debug; the sample isn't on F-Droid/GitHub releases) and dropped at `apks/rootbeer/rootbeer.apk`
— so criterion #6's named target is now **proven live**: `bin/env-up --spec devices/rootbeer.yaml`
→ single `install -r`, root + frida (`-D`-scoped) + scales=0, `bin/verify` → OK. Three arbitrary
APKs (RootBeer single, dbs single, HealthHub split), both install shapes, zero code change.
(Build required JDK 21 + NDK 27 + platform-34/build-tools-35; the host is behind a Cloudflare
Gateway TLS-intercepting proxy, so the Gradle JVM was pointed at a local truststore carrying
the Gateway CA.)
