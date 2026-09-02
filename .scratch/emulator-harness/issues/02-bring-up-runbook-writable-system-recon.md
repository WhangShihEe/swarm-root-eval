# 02: Manual bring-up runbook + writable-`/system` / Frida-only recon

**What to build:** one full emulator bring-up done **by hand** and recorded, so the substrate
is understood before it's scripted — plus a written verdict on the one genuine unknown the
later offensive/broker work depends on: can this image give an agent a writable `/system`,
and does a **Frida-only** bypass (root shell only, no `/system`) suffice to clear RootBeer?

**Blocked by:** 01.

**Status:** done

- [x] `RUNBOOK.md` committed with the exact working sequence: create AVD → cold boot (`-no-snapshot-load -wipe-data`) → `adb root` → push + run `frida-server` v17.17.0 (arm64) → APK install → confirm `frida-ps -U` and `pm list packages`.
- [x] Written verdict on writable-`/system`: proven on this image, with the launch recipe (`-writable-system` + `adb disable-verity` + reboot + `adb remount`), and the Frida-only approach (root shell only, `/system` untouched) as the default. Recorded as the input to the broker's **dynamic-agent launch profile** (ticket 06).

## Comments

**Done (2026-09-01).** `RUNBOOK.md` at repo root; every step verified live on a real
from-scratch cold boot, provisioning driven against the live device.

- **Bring-up verified:** corrected AVD cold-boots in ~13 s; `adb root` → `uid=0`; frida-server
  17.17.0 pushed + running as root, `frida-ps -U` reaches the device; HealthHub (a **split**
  APK) installed via `install-multiple` → present in `pm list packages`.
- **Writable-`/system` verdict — PROVEN:** on a `-writable-system` boot, `adb disable-verity` →
  reboot → `adb remount` makes `/system` RW (as an **overlayfs** mount, upperdir on
  `/mnt/scratch`); write → read-back → delete of a throwaway file all succeeded. It's overlayfs,
  not a raw block edit — fine for build.prop overlay / system CA cert / system `su`, persists
  while verity stays off. **Frida-only** (root shell + frida-server, all in `/data`) sidesteps
  it and is the default dynamic-agent launch profile; `-writable-system` is the opt-in variant.
- **Root cause found (fed into tickets 01/03):** `avdmanager` from cmdline-tools **12.0** can't
  parse this image's SDK-XML v4, so it writes **`target=android-0`** → black-screen boot. Fix:
  use cmdline-tools **≥ 23.0** (now merged into `cmdline-tools/latest`). Not an HVF, host, or
  agent-harness problem.
- **Operational footgun (fed into tickets 03/05/06):** launching a second `emulator … -port
  5554` without killing the first leaves the loser on undiscoverable random ports (adb scans
  only 5554–5584). Always kill the prior instance before relaunching; keep the explicit `-port`.
