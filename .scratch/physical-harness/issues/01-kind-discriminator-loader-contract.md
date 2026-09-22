# 01: `kind` discriminator — spec loader + Contract

**What to build:** Device specs and the connection contract learn what *kind* of device they
describe, so the rest of the feature can branch on it — while every existing emulator run stays
byte-for-byte identical. This is the prefactor ("make the change easy") that opens the seam;
nothing physical runs yet. A physical spec (`devices/pixel7.yaml`) exists and parses, and the
contract can render a physical connect-script from a hand-built contract, but no provider
produces one yet.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Every device spec carries a `kind` field; specs without one default to `emulator`, so all existing specs and their runs are unchanged.
- [ ] The spec loader (`TargetConfig`) exposes `kind` and rejects an unknown kind loudly.
- [ ] `Contract` gains `kind`, `device_id`, and `adb_endpoint`; `console_port` becomes optional and is `None` for physical.
- [ ] `render_contract_line` / `parse_contract` round-trip a physical contract (with `device_id`/`adb_endpoint`, no `console_port`) as well as an emulator one.
- [ ] `render_connect_script` branches on `kind`: the emulator branch is unchanged (`adb connect host.docker.internal:<adb_port>`); the physical branch does `adb connect <ip>:5555` and addresses the device by id (`adb -s`, `frida -D <id>`), verifying the pinned frida version via `frida -D <id>` (not bare `-U`).
- [ ] `devices/pixel7.yaml` authored: `kind: physical`, `attached: true` (auto-detect the single USB phone) or an explicit `device_id`, `adb_tcpip_port: 5555`, reused `target_apk` + `app:` block + `frida` + `normalize_settings`; no AVD knobs, no `root:` key.
- [ ] Unit tests cover the physical connect-script render and both round-trips, with no device and no broker (the existing fake-injection idiom).
- [ ] Existing emulator contract/loader tests still pass unchanged.
