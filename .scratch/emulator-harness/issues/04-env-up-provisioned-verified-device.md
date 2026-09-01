# 04: `env-up TARGET_APK=…` yields a provisioned, verified device

**What to build:** the first full end-to-end path — `env-up` boots **and** provisions the
device (root shell, frida-server running, target APK installed, settings normalized), and
`bin/verify` proves it. App-agnostic: package + launch activity are read from the APK, so any
APK works with no code change. APK-in is the permanent interface.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] The device spec gains `target_apk` + provisioning toggles; `env-up TARGET_APK=<path>` boots then provisions.
- [ ] Post-provision: `frida-ps -U` lists processes, the target package appears in `pm list packages`, and the three animation scales are 0.
- [ ] Package name + launchable activity are derived from the APK, never hardcoded (`apkanalyzer manifest`; `aapt dump badging <apk> | grep -E '^package:|launchable-activity:'` verified working this session).
- [ ] Install handles **both single and split APKs**: a lone `.apk` via `adb install -r`, a split set (a `base.apk` + `split_config.*.apk`, as HealthHub ships) via `adb install-multiple -r base.apk split1 …`. Detect the split case rather than assuming a single file.
- [ ] `bin/verify` exits 0 when the device is reachable + frida is up + the package is present; non-zero with a clear reason otherwise.
- [ ] Proven on the **RootBeer sample** and a **second arbitrary APK** with no code change.
