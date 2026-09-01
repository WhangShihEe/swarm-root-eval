# 02: Manual bring-up runbook + writable-`/system` recon

**What to build:** one full emulator bring-up done **by hand** and recorded, so the substrate
is understood before it's scripted — plus a written verdict on whether this image can give an
agent a writable `/system` (needed by later offensive sets, not by the harness itself).

**Blocked by:** 01.

**Status:** done (2 live-confirmations deferred to a real terminal — see Comments)

- [x] `RUNBOOK.md` committed with the exact working sequence: create AVD → cold boot (`-no-snapshot-load -wipe-data`) → `adb root` → push + run `frida-server` v17.17.0 (arm64) → `adb install` an APK → confirm `frida-ps -U` and `pm list packages`.
- [x] Written verdict on writable-`/system`: does it work on this image, the precise launch recipe (`-writable-system` + `adb disable-verity` + reboot), and whether a Frida-only anti-root approach (root shell only) sidesteps it. Recorded as the input to the set-3/4 dynamic-agent launch profile.

## Comments

**Implemented (2026-09-01).** File: `RUNBOOK.md` at repo root. The exact from-scratch sequence
(create AVD → cold boot → `adb root` → frida-server 17.17.0 → APK install → confirm) plus the
writable-`/system` verdict.

**Environmental blocker found — the emulator can't be booted from inside the agent harness.**
The Android emulator needs Hypervisor.framework. Launched from within the Claude Code Bash tool
(sandboxed *and* with the sandbox disabled, `-gpu swiftshader_indirect` *and* `-gpu off`) the
guest never executes: log shows repeated `qemu_mprotect__osdep: mprotect failed: Permission
denied` then `WARNING | hvf is not enabled on this aarch64 host`, qemu pinned at ~0 s CPU. The
emulator binary is correctly entitled (`allow-jit` + `hypervisor`) and `emulator -accel-check`
reports HVF available — the block is the harness process context denying the JIT/hypervisor
memory mapping, not the SDK. **Emulators must be launched from a real terminal / Android
Studio** (which is how the pre-existing `frida16k` instance was running). Worth carrying into
issues 03–05: the agent can *script* create/boot/provision, but a human (or a non-harness
runner) has to *execute* the boot on this host.

**What was verified live vs. deferred.** Verified against the SDK and the running API-37
rootable image (same image family): AVD create (`pixel-a37` created, then deleted for a clean
slate); `adb root` → `uid=0`; frida client 17.17.0 pinned + `frida-ps -U` lists device
processes; APK-agnostic derivation via `aapt dump badging` → `sg.gov.hpb.healthhub` /
`LauncherActivity`; target present in `pm list packages`; HealthHub is a **split** APK so
`install-multiple` (not `install`) is required — recorded in the runbook. **Deferred to a real
terminal** (both flagged ⏸️ in `RUNBOOK.md`): (1) driving the from-scratch cold boot to full
readiness end-to-end, and (2) the live `/system` write/read-back/delete under `-writable-system`.

**Writable-`/system` verdict.** Image is `userdebug` + `ro.debuggable=1` + `ro.secure=1` +
`ro.boot.veritymode=enforcing` (observed live). So `adb root` gives a root shell but `/system`
stays read-only under enforcing dm-verity; writing it needs the `-writable-system` launch
profile + `adb disable-verity` + reboot + `adb remount`. **Frida-only sidesteps it:** the
anti-root tasks need only a root shell + frida-server (all in `/data`), never `/system`. Verdict
for set-3/4: dynamic-agent profile = **Frida-only by default**, `-writable-system` an opt-in
variant reserved for system-CA-cert / persistent-`su` cases. The final live write-test is the
only thing needed to stamp ✅/❌ — recipe is in the runbook.

**Note for the user:** to run the recon, `frida16k` was taken down (with approval) — but since
the boot can't run under the harness, it wasn't replaced. Relaunch it yourself when needed:
`source bin/env.sh && emulator -avd frida16k -snapshot golden` (its original launch flags).
