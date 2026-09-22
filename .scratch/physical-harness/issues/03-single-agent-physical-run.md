# 03: `single_agent devices/pixel7.yaml` runs end-to-end on the phone

**What to build:** The plumbing derisk itself — one command leases the real phone and runs the
existing agent against it. `single_agent` picks the acquisition provider from the spec's
`kind`, injects the physical contract, and the sandboxed `dynamic_agent` connects to the phone
(adb + `frida -D`) and attacks `rasp_dummy`. Whether or not the agent cracks it, the full
emulator-parity path is demonstrated on real hardware, and the device is always released.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `single_agent` reads the spec's `kind` and binds the acquisition provider accordingly: `emulator` → broker client, `physical` → the physical provider. Emulator runs are unaffected.
- [ ] `python single_agent.py devices/pixel7.yaml` leases the phone, writes the injected physical contract into the run's log dir, and launches the agent subprocess exactly as the emulator path does (same budget/time-limit knobs).
- [ ] Inside the sandbox, the injected connect-script succeeds against the phone: `adb connect <ip>:5555`, device visible, `frida -D <id>` handshake OK.
- [ ] `dynamic_agent` runs in single mode (no board) against `rasp_dummy` on the phone with the correct per-kind mission hint (real hardware: `emulator` check won't fire; introducing frida trips the `frida` check, which must be defeated).
- [ ] The phone is released in a `finally` — a failed or timed-out run still stops frida-server and disconnects.
- [ ] Demonstrated: a real run against the Pixel 7 completes, with the contract and the agent transcript in the run log.
