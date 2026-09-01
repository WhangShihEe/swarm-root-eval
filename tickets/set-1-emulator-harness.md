# Ticket Set 1 — Emulator Harness (Inspect-free)

**Goal of the set:** a reusable, **APK-agnostic** harness that brings up an Android 37
Pixel emulator from a clean install, provisions it (root + frida-server + target APK +
normalized settings), and exposes the device(s) as an **addressable pool**. Zero Inspect
dependency. Per-trial reset and any agent/eval logic are explicitly **out of scope** (later
sets).

**Design invariants (hold across every ticket):**
- Target APK is a **parameter**, never baked in. Works for RootBeer sample *and* HealthHub
  *and* any arbitrary APK with no code change.
- Emulators are an **addressable pool** (serial/port registry). Build for size `N`, run
  `N=1` first. **No 1:1 agent↔emulator assumption anywhere.**
- **Reset = full scripted create-from-nothing.** No golden snapshot. Every bring-up (and
  later, every per-trial reset) rebuilds the device from scratch: create AVD → cold boot →
  provision. Simple and reproducible; the cost is boot+provision time (~minutes) per
  instance. Snapshot-based caching can be added later if that time becomes a bottleneck.
- Everything driven from a declarative **device-spec YAML** (the reproducible-env file for
  the device layer, parallel to Inspect's `compose.yaml` for the toolbox later).

**Environment facts (this host):** Apple Silicon M4 Max, 36 GB, 14 cores → ~3–5 concurrent
emulators comfortably. SDK at `~/Library/Android/sdk`. Images present:
`android-37.1/google_apis_ps16k/arm64-v8a` (rootable — use this) and the playstore variant
(not rootable — avoid). `adb`, `frida` (client **17.17.0**), `jadx` present.
`emulator`/`avdmanager`/`sdkmanager` exist in the SDK but are **not on PATH.**

---

## T1.0 — Manual bring-up runbook + writable-`/system` capability probe  ⚠️ do this first

**Why:** you want to learn the substrate before automating it. Do one full bring-up **by
hand** and record it. While you're there, answer the one genuine unknown that later
(offensive) sets depend on: **can this image give an agent a writable `/system`?** — needed
for build.prop spoofing, a system CA cert, or a system `su`. This is capability recon, not a
provisioning step; set-1 provisioning itself never touches `/system`.

**Steps (do each by hand, record exact commands + output):**
1. Put SDK tools on PATH; create an AVD from the `google_apis_ps16k` arm64 image, Pixel profile.
2. Cold-boot it (`-no-snapshot-load -wipe-data`). Wait for full boot by hand.
3. `adb root` — this gives a **root shell**, which is all set-1 provisioning needs (everything
   lives in `/data`).
4. Push a matching `frida-server` (arm64, **v17.17.0** to match the client) to
   `/data/local/tmp`, run it, confirm `frida-ps -U` lists processes.
5. `adb install` any APK; confirm it's in `pm list packages`.
6. **Writable-`/system` capability probe (recon only).** Relaunch with `-writable-system`;
   `adb root && adb disable-verity` (reboot if required) `&& adb remount`. Confirm you can
   write a throwaway file to `/system`, read it back, then delete it. Record: does this image
   support writable `/system` at all, and what exact sequence/flags it takes. This tells
   set-3/4 how a *dynamic* agent instance must be launched.

**Acceptance criteria:**
- `RUNBOOK.md` committed with the exact working command sequence for the from-scratch bring-up.
- A written **verdict on writable-`/system`**: does it work on this image, and what's the
  precise launch recipe (`-writable-system` + disable-verity + reboot)? Note if a **Frida-only**
  anti-root approach (runtime hooks, root shell only, no `/system`) sidesteps it for the demo
  tier. This verdict is a **pointer input to the set-3/4 dynamic-agent launch config.**

**Pointers:** `-writable-system`, `adb disable-verity` (needs reboot), `getprop
ro.build.version.sdk`. Frida-server must match client **17.17.0**.

---

## T1.1 — Toolchain bootstrap + `doctor`

**Goal:** make the harness's host dependencies explicit, pinned, and checkable.

**Steps:**
- Script that exports `ANDROID_HOME`/`ANDROID_SDK_ROOT` and puts
  `emulator`, `cmdline-tools/latest/bin` (avdmanager, sdkmanager), `platform-tools` on PATH.
- Pin versions in a checked-in `versions.txt` (emulator build, system-image package, frida).
- A `doctor` command that asserts every required binary + version is present and the
  `google_apis_ps16k;arm64-v8a;android-37.1` image is installed (offer `sdkmanager` install
  hint if missing).

**Acceptance:** `make doctor` (or `./bin/doctor`) exits 0 on this host, lists resolved paths
+ versions, and fails loudly with an actionable message if the rootable image is absent.

**Pointers:** `sdkmanager --list_installed`; frida-server download must match client **17.17.0**.

---

## T1.2 — Device-spec YAML schema + loader

**Goal:** the declarative reproducible-env file for the device layer.

**Steps:**
- Define schema: `name`, `device_profile` (pixel), `system_image`
  (`system-images;android-37.1;google_apis_ps16k;arm64-v8a`), `api`, `ram_mb`, `cores`,
  `data_size_mb`, `target_apk` (path), and `provisioning` toggles (root, frida, install_apk,
  normalize_settings, auto_launch).
- Loader + validator (fail on missing image / missing APK / bad profile).
- Commit a sample `devices/pixel-a37.yaml`.

**Acceptance:** loader validates the sample, produces a typed config object, and rejects a
spec pointing at a non-installed image or missing APK with a clear error. Schema documented
in the file header.

---

## T1.3 — AVD create-from-scratch (idempotent)

**Goal:** build the AVD from nothing, reproducibly, from a device spec.

**Steps:**
- Consume the T1.2 config; create the AVD via `avdmanager create avd` with the Pixel
  device (`-d pixel`) and the rootable image.
- Write `config.ini` values (RAM, cores, data partition) from the spec.
- Idempotent: `--force` recreate, or skip-if-exists behind a flag.

**Acceptance:** running twice is safe; `avdmanager list avd` shows the AVD; its `config.ini`
reflects spec values; hardware profile = Pixel, image = `google_apis_ps16k` arm64 37.1.

**Pointers:** `avdmanager create avd -n <name> -k "<image>" -d pixel`; AVD dir under `~/.android/avd`.

---

## T1.4 — Cold boot + robust readiness wait

**Goal:** launch an instance on a chosen port and return only when it's truly usable.

**Steps:**
- Launch headless (`-no-window`), clean (`-no-snapshot-load -wipe-data`), at an explicit
  even console port. (Dynamic-agent instances may additionally need `-writable-system` per
  T1.0 — that's a set-3/4 launch-profile concern, not baseline.)
- Readiness poll with timeout: `adb wait-for-device`, then `sys.boot_completed==1`,
  `init.svc.bootanim==stopped`, and package manager responsive (`pm path android`).

**Acceptance:** returns only on a fully-booted device; accepts `--port`; times out cleanly
with logs if boot stalls. Serial derived as `emulator-<console_port>`.

**Pointers:** console port even (5554), adb port odd (5555); `getprop sys.boot_completed`.

---

## T1.5 — Provisioning (root · frida-server · APK install · settings)

**Goal:** take a booted device to the t=0 state, APK-agnostically.

**Steps:**
- `adb root` (root shell only — set-1 provisioning writes to `/data`, never `/system`;
  writable-system is deferred to the offensive sets).
- Push arch-matched `frida-server` (arm64, pinned to client version) to `/data/local/tmp`,
  `chmod`, launch, confirm `frida-ps -U`.
- Derive package name + launchable activity **from the APK** (`aapt dump badging` or
  `apkanalyzer manifest`), so nothing is app-specific; `adb install -r <apk>`.
- Normalize settings: disable the 3 animation scales, `svc power stayon true`, set
  locale/timezone, dismiss setup wizard.
- Optional `auto_launch` of the derived main activity.

**Acceptance:** post-provision, `frida-ps -U` works, target package appears in
`pm list packages`, animations are 0; identical script succeeds for **RootBeer sample** and
an **arbitrary second APK** with no edits.

**Pointers:** `aapt dump badging <apk> | grep -E 'package|launchable-activity'`;
`settings put global window_animation_scale 0`.

---

## T1.6 — Emulator pool (addressable, size N)

**Goal:** run and track N instances as a shared, addressable resource — no scheduling logic
yet (that's set 4), just lifecycle + registry. Each instance is a full create→boot→provision
from scratch.

**Steps:**
- Launch N instances on distinct port pairs (5554/5555, 5556/5557, …), each with isolated
  writable data (per-instance AVD or `-datadir`).
- A registry (JSON/sqlite) mapping serial → console port → adb port → status
  (building/booting/ready/down).
- `acquire()` / `release()` stubs that just flip status (real allocation policy = set 4).

**Acceptance:** `pool up --n 2` yields 2 reachable, provisioned emulators with distinct
serials, all in the registry; `pool down` tears everything down; `--n 1` is the default and
is not a special case in the code.

**Pointers:** watch total RAM (~3–5 max here); from-scratch means N bring-ups pay N× the
boot+provision cost — parallelize the launches.

---

## T1.7 — One-command env up/down + smoke verify (set exit criteria)

**Goal:** the seam later sets consume — bring the whole thing up with one command.

**Steps:**
- `make env-up TARGET_APK=<path> [N=1] [SPEC=devices/pixel-a37.yaml]` →
  create → boot → provision → verify → print device handles (serials + ports).
- `make env-down` → clean teardown.
- `verify` smoke test: reachability + `frida-ps -U` + target package present, per handle.

**Acceptance (this is the set-1 done bar):** on this host, a single command builds from
scratch a verified, provisioned Pixel/Android-37 emulator with an **arbitrary** target APK
and prints its adb serial; `N=2` builds two; `env-down` cleans up; the whole thing has **no
Inspect import anywhere.**
