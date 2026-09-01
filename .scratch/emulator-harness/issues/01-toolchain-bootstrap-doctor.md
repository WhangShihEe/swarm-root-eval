# 01: Toolchain bootstrap + `doctor`

**What to build:** `source bin/env.sh` puts the pinned Android SDK tools (and a JDK the
cmdline-tools can run under) on PATH, and `bin/doctor` tells you in one run whether this
machine can build the harness — every pinned binary present at the right version, `yq`
available (the harness's YAML dependency), and the rootable system image installed.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `source bin/env.sh` puts `emulator`, `avdmanager`, `sdkmanager`, `adb` on PATH resolved from `versions.txt`, and points `JAVA_HOME` at a JDK >= 17.
- [ ] The `cmdline-tools` (avdmanager/sdkmanager) on PATH is a revision that **parses the image's SDK-XML v4** — pin **≥ 23.0** in `versions.txt`, **not 12.0**. A 12.0 `avdmanager` silently writes `target=android-0` into the AVD config → black-screen boot (see ticket 02 / RUNBOOK). If the SDK has both `cmdline-tools/latest` (old) and `latest-2` (new), env.sh must prefer the newest.
- [ ] `bin/doctor` checks each pinned tool + `yq` + the `google_apis_ps16k;arm64-v8a;android-37.1` image and exits 0 on this host.
- [ ] `bin/doctor` fails loudly if the `cmdline-tools` on PATH is too old to parse the v4 image XML (the revision that produces `target=android-0` AVDs).
- [ ] A missing tool, version mismatch, or missing rootable image → non-zero exit with an actionable fix hint (e.g. the `sdkmanager` install line, `brew install yq`).
- [ ] `yq` is pinned in `versions.txt` alongside the SDK/frida versions, not assumed ambient.
