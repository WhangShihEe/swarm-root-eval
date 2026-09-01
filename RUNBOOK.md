# Emulator Bring-Up Runbook (manual, from scratch)

Issue: `.scratch/emulator-harness/issues/02-bring-up-runbook-writable-system-recon.md`

One full **from-nothing** bring-up of the harness's target device, done by hand and recorded
here so the substrate is understood before issues 03–05 script it. Also records the
**writable-`/system` verdict** that the offensive sets (3/4) depend on.

- **Target APK is a parameter** — nothing below is app-specific. Package name and launchable
  activity are *derived from the APK*. The worked example uses HealthHub
  (`sg.gov.hpb.healthhub`), but any APK works with no edits.
- **From scratch, no snapshot.** Every bring-up is create-AVD → cold-boot (`-wipe-data`) →
  provision. No golden snapshot (the design invariant).

## Environment (this host)

Apple Silicon M4 Max, macOS 26.5, SDK at `~/Library/Android/sdk`. Pinned tool versions live in
`versions.txt`; `bin/doctor` asserts them. Rootable image:
`system-images;android-37.1;google_apis_ps16k;arm64-v8a` (the playstore variant is **not**
rootable — avoid it).

> ⚠️ **Run the emulator from a real terminal, not from inside an agent/CI harness.** The
> Android emulator needs Hypervisor.framework (HVF). Launched from within the Claude Code tool
> harness the guest never executes — the log shows repeated
> `qemu_mprotect__osdep: mprotect failed: Permission denied` and then
> `WARNING | hvf is not enabled on this aarch64 host`, and qemu sits at ~0 s CPU forever. The
> emulator binary *is* correctly entitled (`com.apple.security.cs.allow-jit`,
> `com.apple.security.hypervisor`) and `emulator -accel-check` reports HVF available — the
> block is the harness process context denying the JIT/hypervisor memory mapping, not the SDK.
> **Steps 1–6 below are the exact working commands; run them in your own shell (or Android
> Studio's terminal).**

---

## 0. Prerequisites

```bash
cd ~/swarm-root-eval
source bin/env.sh      # ANDROID_SDK_ROOT + emulator/avdmanager/sdkmanager/adb on PATH, JAVA_HOME->JDK25
bin/doctor             # must exit 0
```

`source bin/env.sh` also loads `versions.txt`, so `$SYSTEM_IMAGE` and `$FRIDA_VERSION` are set
in the commands below.

## 1. Create the AVD from scratch (idempotent)

```bash
avdmanager delete avd -n pixel-a37 2>/dev/null || true          # start from nothing
echo "no" | avdmanager create avd -n pixel-a37 -k "$SYSTEM_IMAGE" -d pixel
avdmanager list avd | grep -A2 'Name: pixel-a37'                # confirm
```

- `-d pixel` = Pixel hardware profile. `echo "no"` declines the "custom hardware profile?"
  prompt. `Auto-selecting single ABI arm64-v8a` in the output is expected.
- AVD lands in `~/.android/avd/pixel-a37.avd`.

## 2. Cold boot from nothing (headless), on an explicit port

```bash
emulator -avd pixel-a37 -no-window -no-snapshot-load -wipe-data \
         -port 5554 -no-audio -gpu swiftshader_indirect &
```

- `-no-snapshot-load -wipe-data` = true from-scratch boot, no snapshot. `-port 5554` →
  serial `emulator-5554` (console port even, adb port 5555 odd).
- First cold boot with `-wipe-data` takes a few minutes.

**Readiness wait** — return only when the device is genuinely usable (not just "device"):

```bash
adb wait-for-device
until [ "$(adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] \
   && [ "$(adb -s emulator-5554 shell getprop init.svc.bootanim 2>/dev/null | tr -d '\r')" = stopped ] \
   && [ -n "$(adb -s emulator-5554 shell pm path android 2>/dev/null)" ]; do
  sleep 5
done
echo "device ready"
```

## 3. Root shell

```bash
adb -s emulator-5554 root      # -> "restarting adbd as root"
adb -s emulator-5554 shell id  # -> uid=0(root)
```

This image grants a root shell directly. **That is all set-1 provisioning needs** —
frida-server, the APK, and settings all live under `/data`, never `/system`.

## 4. frida-server (must match the client version)

Client is frida **17.17.0** (`bin/doctor` asserts it). Use the matching arm64 server binary
(present on this host at `~/frida-server-17.17.0-android-arm64`; otherwise download
`frida-server-$FRIDA_VERSION-android-arm64` from the frida releases).

```bash
adb -s emulator-5554 push ~/frida-server-17.17.0-android-arm64 /data/local/tmp/frida-server
adb -s emulator-5554 shell chmod 755 /data/local/tmp/frida-server
adb -s emulator-5554 shell "nohup /data/local/tmp/frida-server >/dev/null 2>&1 &"
frida-ps -U | head           # lists device processes => server reachable
```

## 5. Install the target APK (APK-agnostic)

Derive the package + launchable activity from the APK itself — nothing app-specific:

```bash
AAPT=$(ls "$ANDROID_SDK_ROOT"/build-tools/*/aapt | sort -V | tail -1)
APK=~/Downloads/for_cyber_stuffs/healthhub/base.apk
"$AAPT" dump badging "$APK" | grep -E '^package:|launchable-activity:'
# package: name='sg.gov.hpb.healthhub' ...
# launchable-activity: name='sg.gov.hpb.healthhub.LauncherActivity' ...
```

Install. A single self-contained APK uses `install -r`; a **split** app (a `base.apk` plus
`split_config.*.apk`, as HealthHub ships) uses `install-multiple -r`:

```bash
# single APK:
adb -s emulator-5554 install -r "$APK"

# split APK set (HealthHub): install base + all splits together
adb -s emulator-5554 install-multiple -r \
  ~/Downloads/for_cyber_stuffs/healthhub/base.apk \
  ~/Downloads/for_cyber_stuffs/healthhub/split_config.arm64_v8a.apk \
  ~/Downloads/for_cyber_stuffs/healthhub/split_config.en.apk \
  ~/Downloads/for_cyber_stuffs/healthhub/split_config.xxhdpi.apk
```

## 6. Confirm the t=0 state

```bash
frida-ps -U | head                                        # frida reachable
adb -s emulator-5554 shell pm list packages | grep sg.gov.hpb.healthhub   # target present
```

## Teardown

```bash
adb -s emulator-5554 emu kill        # or: adb emu kill
```

---

## Verification status (recon, 2026-09-01)

The from-scratch **boot** could not be driven to completion from inside the agent harness (HVF
blocked — see the ⚠️ box). Everything that does **not** require the agent to run an HVF guest
was verified live against the API-37 rootable image (the user's running `frida16k` instance,
same image family) and against the SDK on this host:

| Step | Command | Status |
|------|---------|--------|
| 1 | `avdmanager create avd … -d pixel` | ✅ ran — `pixel-a37` created (then deleted to leave a clean slate) |
| 2 | cold boot + readiness poll | ⏸️ **run in your terminal** — HVF unavailable to the harness |
| 3 | `adb root` / `id` | ✅ live — `restarting adbd as root`, `uid=0` |
| 4 | frida-server + `frida-ps -U` | ✅ live — client 17.17.0 pinned; `frida-ps -U` listed device processes |
| 5 | aapt derivation + install | ✅ derivation live (`sg.gov.hpb.healthhub` / `LauncherActivity`); package present in `pm list packages` |
| 6 | confirm frida + package | ✅ live |

---

## Writable-`/system` verdict (input to set-3/4 dynamic-agent launch profile)

**Question:** can this image give an agent a writable `/system` (for build.prop spoofing, a
system CA cert, or a system `su`)?

**Evidence observed on the running API-37 rootable image:**

```
ro.build.type      = userdebug
ro.debuggable      = 1
ro.secure          = 1
ro.boot.veritymode = enforcing
```

`userdebug` + `ro.debuggable=1` means `adb root` is available (confirmed, step 3). But
`/system` is mounted read-only and dm-verity is **enforcing**, so a plain `adb root` root shell
**cannot** write `/system` — verity would reject the modified block and remounting rw fails.

**Recipe to make `/system` writable** (userdebug + verity image → this is the standard path;
the launch flag is the key difference from baseline):

```bash
# 1. launch with the writable-system flag (a DISTINCT launch profile from baseline step 2)
emulator -avd pixel-a37 -no-window -no-snapshot-load -wipe-data \
         -port 5554 -no-audio -gpu swiftshader_indirect -writable-system &
# ... wait for boot ...
adb -s emulator-5554 root
adb -s emulator-5554 disable-verity     # -> reports verity disabled; asks for a reboot
adb -s emulator-5554 reboot             # verity change only takes effect after reboot
# ... wait for boot ...
adb -s emulator-5554 root
adb -s emulator-5554 remount            # /system now mounted rw
# write / read-back / delete a throwaway file to prove it:
adb -s emulator-5554 shell 'echo probe > /system/harness_probe.txt && cat /system/harness_probe.txt && rm /system/harness_probe.txt'
```

> ⏸️ The live write/read-back/delete on `/system` was **not** executed during this recon — the
> from-scratch boot it depends on can't run under the agent harness (HVF). Run the block above
> in a real terminal to stamp the final ✅/❌ on this image. The evidence
> (`userdebug` + `veritymode=enforcing`) makes the `-writable-system` + `disable-verity` +
> reboot recipe the expected requirement; confirm and record the exact result here.

**Frida-only sidestep (recommended for the demo tier).** The anti-root / root-detection tasks
do **not** need a writable `/system` at all. A **root shell + frida-server** (steps 3–4, no
`/system` write) is enough: frida hooks the target at runtime to defeat root checks. So the
baseline harness (set 1) never touches `/system`, and the *dynamic* offensive profile can
default to **Frida-only**. Reserve the `-writable-system` launch profile for the narrower cases
that genuinely need an on-disk `/system` change (a system CA cert for transparent TLS
interception, or a persistent system `su`).

**Verdict for set-3/4:** the dynamic-agent launch profile should be **Frida-only by default**
(root shell + frida-server, no `/system`), with `-writable-system` + `disable-verity` + reboot
as an **opt-in** launch variant for the CA-cert / persistent-`su` cases. Baseline set-1
provisioning stays entirely in `/data`.
