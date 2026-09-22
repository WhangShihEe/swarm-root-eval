# 02: Physical acquisition provider (the wireless bridge)

**What to build:** A host-side acquisition provider — the emulator broker's brokerless sibling
— that turns the attached rooted phone into a ready, contract-described target over wireless
adb. Given the physical spec, running the provider brings the phone up reachable over WiFi with
frida talking and the target app freshly installed, and hands back a well-formed contract;
releasing it reverses the setup. Verifiable on its own, before any agent is wired in.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `physical_acquire(spec) -> Contract` and `physical_release(...)` exist and satisfy the same shape the launcher's `acquire`/`release` seam already expects.
- [ ] acquire detects the phone on USB (auto-detect when `attached: true`, else the named `device_id`), arms `adb tcpip 5555`, auto-detects the phone's WiFi IP, and `adb connect <ip>:5555` — after which USB may be unplugged.
- [ ] acquire pushes and starts the pinned frida-server (arm64, matching the client version) and confirms the two-sided handshake via `frida -D <id>`.
- [ ] acquire installs the target APK if absent and applies the between-runs reset — `pm clear <pkg>` + reinstall-if-missing + (re)start frida-server — so a run starts from a clean app state.
- [ ] acquire emits a physical `Contract` (`kind: physical`, `device_id`, `adb_endpoint`, no `console_port`) that `render_connect_script` turns into a working sandbox connect-script.
- [ ] release stops frida-server and `adb disconnect`s; it never raises (teardown must be total), matching the broker client's release contract.
- [ ] The provider is resilient to the observed device drop-offs: detect-and-retry with a bounded timeout, and a loud, actionable failure if the phone is absent, unauthorized, or not rooted/hidden.
- [ ] Verified end-to-end against the real Pixel 7: provider run leaves the phone reachable over WiFi, frida handshake clean, `rasp_dummy` freshly installed, contract emitted; release reverses it.
