# 03: One command boots a bare emulator from a device-spec YAML

**What to build:** `bin/env-up` reads a validated device-spec YAML and brings a bare
Pixel/Android-37 emulator to full readiness, printing its adb serial; `bin/env-down` tears it
down. Spec-driven from the first line — no hardcoded device config. No provisioning yet.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `devices/pixel-a37.yaml` exists (name, device_profile, system_image, api, ram_mb, cores, data_size_mb); a loader validates it and rejects a missing/uninstalled image with a clear error.
- [ ] `bin/env-up --spec devices/pixel-a37.yaml` creates the AVD (idempotent re-run) and returns only when fully booted (`sys.boot_completed==1`, bootanim stopped, `pm path android` responsive); prints serial `emulator-<console_port>`.
- [ ] `adb devices` then shows a booted Pixel/Android-37 device.
- [ ] `bin/env-down` removes the instance and cleans up.
