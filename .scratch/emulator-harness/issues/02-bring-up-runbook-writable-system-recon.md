# 02: Manual bring-up runbook + writable-`/system` recon

**What to build:** one full emulator bring-up done **by hand** and recorded, so the substrate
is understood before it's scripted — plus a written verdict on whether this image can give an
agent a writable `/system` (needed by later offensive sets, not by the harness itself).

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `RUNBOOK.md` committed with the exact working sequence: create AVD → cold boot (`-no-snapshot-load -wipe-data`) → `adb root` → push + run `frida-server` v17.17.0 (arm64) → `adb install` an APK → confirm `frida-ps -U` and `pm list packages`.
- [ ] Written verdict on writable-`/system`: does it work on this image, the precise launch recipe (`-writable-system` + `adb disable-verity` + reboot), and whether a Frida-only anti-root approach (root shell only) sidesteps it. Recorded as the input to the set-3/4 dynamic-agent launch profile.
