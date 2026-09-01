# 04: `env-up TARGET_APK=…` yields a provisioned, verified device

**What to build:** the first full end-to-end path — `env-up` boots **and** provisions the
device (root shell, frida-server running, target APK installed, settings normalized), and
`bin/verify` proves it. App-agnostic: package + launch activity are read from the APK, so any
APK works with no code change.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] The device spec gains `target_apk` + provisioning toggles; `env-up TARGET_APK=<path>` boots then provisions.
- [ ] Post-provision: `frida-ps -U` lists processes, the target package appears in `pm list packages`, and the three animation scales are 0.
- [ ] Package name + launchable activity are derived from the APK (`aapt dump badging` / `apkanalyzer`), never hardcoded.
- [ ] `bin/verify` exits 0 when the device is reachable + frida is up + the package is present; non-zero with a clear reason otherwise.
- [ ] Proven on the **RootBeer sample** and a **second arbitrary APK** with no code change.
