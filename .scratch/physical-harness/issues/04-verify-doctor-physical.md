# 04: Physical paths for `bin/verify` + `bin/doctor`

**What to build:** The preflight/verification tools understand physical specs, so an operator
can confirm in one run that the phone is ready (or get an actionable reason why not) — the
physical counterpart to the emulator checks these tools already do. Emulator behavior is
unchanged.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `bin/verify --spec devices/pixel7.yaml` confirms: the device is present and authorized over adb, frida-server is running with a version matching the pinned client, the target APK is installed, and root is present **and hidden** (Magisk DenyList — the app's `root` check must not trivially fire).
- [ ] `bin/doctor` gains a physical preflight: adb sees the device, the pinned frida client is present in the sandbox image, and the phone is reachable over the wireless endpoint.
- [ ] Both tools branch on the spec's `kind`; an emulator spec runs the existing checks unchanged.
- [ ] Any failed check exits non-zero with a specific fix hint (e.g. "enable USB debugging / accept the RSA prompt", "frida-server not running", "root visible — enable DenyList for the package").
- [ ] Verified against the provisioned Pixel 7: `bin/verify` and the `bin/doctor` physical preflight both pass, and fail loudly when a precondition is removed.
