# 03: `env-up` boots a bare emulator from a device-spec YAML

**What to build:** `bin/env-up` reads a validated device-spec YAML and brings a bare
Pixel/Android-37 emulator to full readiness, printing its adb serial; `bin/env-down` tears it
down. Spec-driven from the first line via `yq` — no hardcoded device config. No provisioning yet.

**Blocked by:** 02.

**Status:** done

- [x] `devices/pixel-a37.yaml` exists (name, device_profile, system_image, api, ram_mb, cores, data_size_mb); a `yq`-based loader validates it and rejects a missing/uninstalled image with a clear error.
- [x] `bin/env-up --spec devices/pixel-a37.yaml` creates the AVD (idempotent re-run) and returns only when fully booted (`sys.boot_completed==1`, bootanim stopped, `pm path android` responsive); prints serial `emulator-<console_port>`.
- [x] The created AVD's `config.ini` shows **`target=android-37.1`** (not `target=android-0`) — assert this after create; an api-0 AVD boots to a black screen (needs the ticket-01 cmdline-tools ≥ 23.0 fix).
- [x] Kill any prior instance on the target port before launching, and pass an explicit `-port` — a lost port race silently lands the loser on undiscoverable ports (adb only scans 5554–5584).
- [x] `adb devices` then shows a booted Pixel/Android-37 device.
- [x] `bin/env-down` removes the instance and cleans up.

## Comments

**Done (2026-09-02).** Spec-driven `env-up`/`env-down`, verified live on this host (Apple
Silicon, arm64) end-to-end.

What landed:
- `devices/pixel-a37.yaml` — the device-spec (name, device_profile, system_image, api,
  ram_mb, cores, data_size_mb).
- `bin/_spec.sh` — `yq`-based loader/validator. Exports `SPEC_*`; validates required keys,
  numeric fields, and that the system image is actually installed (rc 3 + `sdkmanager` hint
  otherwise). `spec_name` reads just `.name` so teardown works even if the image is gone.
- `bin/_device.sh` — emulator-lifecycle helpers: `emu_kill` (idempotent port clear + bounded
  wait), `emu_booted`/`emu_wait_boot` (the RUNBOOK readiness contract), and the pure
  `cfg_get`/`cfg_set`/`avd_target` config.ini helpers.
- `bin/env-up` / `bin/env-down` — thin orchestrators. env-up: validate spec → create AVD
  (idempotent, reuse if present) → assert `target=android-<api>` → apply ram/cores/data to
  `config.ini` → **kill any prior instance on the port** → cold boot headless on explicit
  `-port` → wait for genuine readiness → print `emulator-<port>` on stdout (progress on
  stderr). env-down: kill the instance + delete the AVD (`--keep-avd` to only kill).
- `tests/spec.sh` (14 hermetic assertions) + `tests/all.sh` runner. Full suite green.

Verified live: fresh **create** path and idempotent **reuse** path both cold-boot to
`boot_completed=1` / bootanim `stopped` / pm responsive; `config.ini` shows
`target=android-37.1`, `hw.ramSize=4096`, `hw.cpu.ncore=4`, `disk.dataPartition.size=8192M`;
`adb devices` lists `emulator-5554` (`ro.build.version.sdk=37`); `env-down` leaves no device
and no AVD dir.

- **Footgun fixed during bring-up:** `avdmanager create` prints its progress to **stdout**,
  which contaminated the captured serial on the create path (the reuse path never hit it).
  Fixed by routing create output to stderr (`1>&2`) so stdout is exactly the serial line.
- Data/ram/cores are written into `config.ini` (single source of truth = the YAML) rather
  than passed as launch flags, so the AVD is self-describing.
- Console port defaults to 5554 with `--port` override; a per-device port assignment is the
  pool engine's job (ticket 05).
