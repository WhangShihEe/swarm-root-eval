# 01: Device layer runs from a device-only file + `--apk`

**What to build:** The bash device bring-up layer boots an emulator from a device spec that carries
**only provisioning** — no app, no APK path baked in. The APK becomes a separate, optional input:
pass `--apk <path>` to install it, or omit it and the device **boots bare** (an emulator with no app,
for atomically testing the device layer on its own). The broker / harness, which drives provisioning,
is rewired to hand the APK to the device layer explicitly rather than expecting the bring-up scripts to
read it out of the spec. This is a prefactor: it decouples "the emulator" from "the app under test"
without yet moving any app fields into their own file (the APK is still sourced from the current spec by
the caller for now).

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `bin/env-up --spec <device.yaml> --apk <path>` boots and installs the given APK.
- [ ] `bin/env-up --spec <device.yaml>` with **no** `--apk` boots a bare emulator (no app install), and does not error on a missing app/APK.
- [ ] The bash bring-up scripts no longer read `app:` or `target_apk` from the spec; they read only provisioning scalars.
- [ ] The broker / harness path that provisions a device passes the APK to the device layer explicitly (behavior for existing specs is unchanged end-to-end).
- [ ] `bin/verify --spec <device.yaml>` still passes for the rasp_dummy reference.
- [ ] Both integration commands still run and pass (verified in the output `.eval`): `single_agent.py devices/rasp_dummy.yaml --model openai-api/litellm/bedrock-claude-opus-4.8` and `swarm.py devices/rasp_dummy.yaml --workers 3 --model …`.
