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

> ⚠️ **GOTCHA (root-caused 2026-09-01): use the right `cmdline-tools` or the AVD boots to a
> black screen.** A from-scratch cold boot of an AVD created by **cmdline-tools 12.0** stalls:
> `WARNING | hvf is not enabled on this aarch64 host`, then repeated
> `qemu_mprotect__osdep: mprotect failed: Permission denied`, qemu at ~0 s CPU. The cause is
> **not** HVF, the host, or the agent harness — it's a **broken AVD config**: cmdline-tools
> 12.0 can't parse this image's SDK-XML **v4** `package.xml` (the `unexpected element abis …
> Expected api-level` warnings), so `avdmanager create` writes **`target=android-0`** into
> `config.ini` instead of `android-37.1`. That api-0 AVD can't boot (black screen), which is
> exactly what Android Studio's Device Manager showed ("API 0") until the API level was set by
> hand.
>
> **Fix (verified — the created `config.ini` then reads `target=android-37.1` and
> `tag.ids=google_apis,page_size_16kb`):** create the AVD with **cmdline-tools 23.0**, which is
> already installed here at `cmdline-tools/latest-2` (12.0 is at `latest`, and that's what
> `env.sh` currently puts on PATH). This is really an **issue-01/03 fix** — `env.sh`/`doctor`
> should prefer the newest `cmdline-tools` and `doctor` should reject `target=android-0`. Step 1
> below uses the 23.0 binary explicitly until that lands.
>
> **Confirmed (2026-09-01):** a corrected AVD (23.0 tools, `target=android-37.1`) cold-boots
> cleanly in a real terminal — `Boot completed in 13077 ms`, no `hvf is not enabled`. So the
> only failure mode is the api-0 AVD; a correctly-created AVD boots fine.
>
> One operational footgun seen while confirming: launching a second `emulator … -port 5554`
> without killing the first leaves the loser on **undiscoverable random ports** (adb only scans
> 5554–5584), so it looks "stuck." **Always kill the prior instance before relaunching**, and
> keep the explicit `-port`.

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
: "${SYSTEM_IMAGE:?run 'source bin/env.sh' first — it loads versions.txt}"   # fail loud if env not sourced
# Use cmdline-tools 23.0 (NOT the 12.0 on PATH): 12.0 mis-parses the v4 image XML and
# writes target=android-0 -> black screen. See the GOTCHA box above.
AVDM="$ANDROID_SDK_ROOT/cmdline-tools/latest-2/bin/avdmanager"
"$AVDM" delete avd -n pixel-a37 2>/dev/null || true             # start from nothing
echo "no" | "$AVDM" create avd -n pixel-a37 -k "$SYSTEM_IMAGE" -d pixel
grep -E '^target=|^tag.ids=' ~/.android/avd/pixel-a37.avd/config.ini   # MUST show target=android-37.1
```

> If you see `Error: Package path is not valid` here, `$SYSTEM_IMAGE` is empty — you skipped
> `source bin/env.sh` (step 0). The guard line above turns that into a clear message instead.
> If `target=` comes out `android-0`, you used the 12.0 `avdmanager` — recreate with the 23.0
> one as above (or patch `config.ini`).

- `-d pixel` = Pixel hardware profile. `echo "no"` declines the "custom hardware profile?"
  prompt. `Auto-selecting single ABI arm64-v8a` in the output is expected.
- AVD lands in `~/.android/avd/pixel-a37.avd`. The `target=android-37.1` check is the guard
  against the api-0 black-screen boot.

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

The full path was verified live on a genuine from-scratch cold boot (2026-09-01), once the AVD
was created with the 23.0 tools. The only step not run here is the `/system` write-test, which
needs a separate `-writable-system` launch (see the verdict below):

| Step | Command | Status |
|------|---------|--------|
| 1 | `avdmanager create … -d pixel` | ⚠️ tool-sensitive — 23.0 tools give `target=android-37.1` (verified); 12.0 give `target=android-0` (broken). Fixed in step 1. |
| 2 | cold boot + readiness | ✅ live — corrected AVD, `Boot completed in 13077 ms`, `boot_completed=1`, `bootanim=stopped`, pm responsive |
| 3 | `adb root` / `id` | ✅ live — `restarting adbd as root`, `uid=0(root) … context=…:su` |
| 4 | frida-server + `frida-ps -U` | ✅ live — pushed 53 MB, running as root (pid 4619); client 17.17.0; `frida-ps -U` listed device processes |
| 5 | aapt derivation + `install-multiple` | ✅ live — derived `sg.gov.hpb.healthhub` / `LauncherActivity`; split install → `Success`; package present in `pm list packages` |
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

> ⏸️ The live write/read-back/delete on `/system` was **not** executed during this recon — it
> depends on a booted (corrected) AVD, and the cold boot was blocked by the api-0 AVD bug plus
> RAM limits. Run the block above in a real terminal to stamp the final ✅/❌ on this image. The
> evidence (`userdebug` + `veritymode=enforcing`) makes the `-writable-system` + `disable-verity`
> + reboot recipe the expected requirement; confirm and record the exact result here.

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
