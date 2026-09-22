# Physical-device harness

Run the swarm-root-eval agent against a **real rooted Android phone** over wireless adb,
as a first-class *kind* of device alongside the emulator — a pipeline **option**, not a
replacement. Near-term this is a **plumbing derisk** on a single phone; it is structured so
it grows into the multi-role swarm (emulator + physical + apk-only workers on a board) later.

## Why

The emulator baseline trips RASP checks that a real phone would simply pass (`emulator`
detector, emulator-only artifacts). The project's ultimate question — *can models compromise
real apps?* — wants the realistic attacker platform: a **rooted device with root hidden**,
running frida, defeating anti-tamper. This feature makes that platform reachable by the same
agent that already drives the emulator.

## Target device (this iteration)

Google Pixel 7 (`panther`), Android 17 / SDK 37, arm64. `rasp_dummy`
(`com.example.rasptarget`) installed; on real hardware only the `debuggable` check fires at
rest (`emulator` won't fire; `frida` fires once the agent introduces frida — which it must
then defeat).

## Decisions (from the grilling session)

- **Always rooted (no unrooted option).** The phone is assumed rooted with **Magisk +
  DenyList** (root hidden). This collapses the injection problem: frida-server works exactly
  as on the emulator — no frida-gadget / JDWP path. Rooting the phone (unlock + Magisk +
  DenyList) is a **manual one-time prereq, not ticketed**.
- **Wireless adb transport.** A USB phone exposes no per-device TCP port on the host (only the
  host adb server on :5037 bridges USB). Rather than route through the host adb server, we make
  the phone a TCP adb device with `adb tcpip 5555` and `adb connect <phone_ip>:5555`. It then
  behaves *identically* to the emulator (a TCP adb device), so `adb` and `frida -U/-D` work
  unchanged; only the address in the contract differs. Bonus: USB can be unplugged after
  arming (robust against the cable drop-offs observed), and it scales to N phones.
- **`kind` lives in the contract, not the agent.** `dynamic_agent` stays device-agnostic and
  consumes an injected contract; it never knows whether it is on a phone or an emulator. The
  only kind-aware code is the `Contract` (which renders the right connect-script) and the
  acquisition provider.
- **Three layers preserved.** (1) agent consumes a contract; (2) launcher/orchestrator
  (`single_agent`, `conductor`) owns the acquire→run→release lifecycle via the injectable
  `acquire`/`release` seam; (3) an **acquisition provider** actually provisions the device and
  returns a contract — the broker for emulators, a new **physical provider** for the phone.
  Provisioning never leaks into the launcher body or the agent.
- **One launcher, dispatch by `kind`.** `single_agent` reads the spec yaml and binds
  `broker_acquire` for `kind: emulator`, the physical provider for `kind: physical`. No second
  CLI, no forked agent. The future mixed swarm just reads each participant's `kind`.
- **Brokerless for now.** Single phone, exploratory. The physical provider is a plain
  host-side function, not a daemon. "Broker adopts physical" (a pool of leased phones) is
  deliberate later work that reuses the same seam.
- **Multi-device-ready contract.** The contract carries a `device_id` and everything is
  id-addressed (`adb -s <id>`, `frida -D <id>`) even for the single phone, so a second phone is
  zero-rework (bare `frida -U` would break the moment a second device appears).
- **State reset = per-app, not per-device.** A phone can't be `-wipe-data` rebuilt like an
  emulator slot. Between runs: `pm clear <pkg>` + reinstall-if-missing + restart frida-server.
  Resets the *target app*, not the device.

## Connection contract shape

`kind` (`emulator` | `physical`) · `device_id` (adb id; `ip:5555` for wireless) ·
`adb_endpoint` (`ip:port`) · `console_port` optional (`None` for physical) · `profile`.
`render_connect_script` branches on `kind`: emulator keeps `adb connect
host.docker.internal:<adb_port>`; physical does `adb connect <ip>:5555` then addresses the
device by id. frida client stays pinned (17.17.0) and handshakes via `frida -D <id>`.

## Physical device spec (yaml)

Same file shape as emulator specs, discriminated by `kind: physical`. Carries `device_id`
(or `attached: true` = "the one phone on USB", auto-detect then arm tcpip), `adb_tcpip_port`
(5555), and reuses `target_apk`, the whole `app:` block, `frida`, `normalize_settings`. Drops
the AVD-only knobs (`system_image`, `device_profile`, `ram_mb`, `cores`, `data_size_mb`,
`headless`). No `root:` key — root is assumed.

## Host-side bridge steps (the physical provider)

acquire: detect USB device → `adb tcpip 5555` → auto-detect WiFi IP → `adb connect ip:5555`
→ push + start pinned frida-server (arm64) → install target APK → reset (`pm clear` +
reinstall) → `frida -D <id>` handshake → emit contract. release: stop frida-server, adb
disconnect. Robust to device drop-offs (detect + retry).

## Manual one-time prereq (NOT ticketed)

Unlock the Pixel bootloader (wipes device), install Magisk, enable **DenyList** to hide root,
enable USB debugging. Confirm Magisk works on the Android 17 build.

## Out of scope (this iteration)

Broker adoption of physical devices; multi-device pools; the message board / multi-role swarm
integration; the model sweep. All are enabled by, but not built in, this feature.

## Tickets

01 kind discriminator (loader + Contract) · 02 physical acquisition provider · 03 single_agent
physical run · 04 verify/doctor physical paths · 05 smoke + RUNBOOK. Edges: 03 and 04 both
depend on 02 and run in parallel; 05 joins them.
