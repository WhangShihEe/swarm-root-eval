# `bin/` — the emulator broker and device harness

The device layer that must be running before any eval. It turns a device-spec YAML into a
booted, rooted, provisioned Android emulator at **t=0** and hands it out under a cap. Everything
here is Inspect-free shell; the swarm/Inspect layer lives in [`../swarm-eval/`](../swarm-eval/).

The stack is four layers, top to bottom:

```
broker      standing service — owns the pool, enforces the cap, grants/reclaims devices
  └ pool    in-process engine — launches, tracks (a registry), releases on distinct ports
      └ env-up / env-down   one device: cold-boot from a spec, provision to t=0, tear down
          └ verify · doctor   prove one device is at t=0 · prove the host can build at all
```

Start the **broker once** before an eval; it persists across requests. Clients are separate
`bin/broker <verb>` invocations that reach the running daemon over a file-backed queue.

## `bin/broker` — the standing device broker

```
bin/broker start [--profile frida-only|writable-system] [--foreground]
bin/broker acquire --spec configs/devices/<name>.yaml [--target-apk <apk>] [env-up args…]
bin/broker release (--serial emulator-5554 | --port 5554)
bin/broker status
bin/broker list
bin/broker ping
bin/broker stop
bin/broker demo    --spec configs/devices/<name>.yaml
```

| Verb | What it does |
|------|--------------|
| `start` | Launch the daemon (backgrounded; `--foreground`/`--fg` to keep it attached). It owns the pool and enforces the cap (`POOL_CAP`, default 6). Idempotent: a second `start` reports the running pid and exits 0. |
| `acquire` | Grant one device for a spec and print its **connection contract** (below). Extra args after `--spec` (e.g. `--target-apk <apk>`) forward verbatim to `env-up` through the pool engine. Fails if the cap is reached. |
| `release` | Release one device by `--serial` or `--port`, freeing its slot. |
| `status` | Print the pool registry via the running broker (raw registry without a broker: `bin/pool status`). |
| `list` | Print the in-use console ports, one per line (the machine-readable form `status` is built on). |
| `ping` | Liveness check; also prints which profile the broker is serving. |
| `stop` | Stop the daemon, reclaiming every device (see the stop grace below). |
| `demo` | The live smoke path: start, grant 2, assert the grant honored the spec's profile and `verify` the first device is at t=0, release both, confirm the pool is clean, stop. Refuses to run if a broker is already up. |

### The launch profile — per-spec by default, overridable

A device comes up under a **launch profile**: `writable-system` (root shell + writable `/system`
via `disable-verity`, for a system CA cert or persistent `su`) or `frida-only` (root shell +
frida-server, no `/system` write). See `docs/adr/0001-writable-system-default-launch-profile.md`.

- The broker owns **no default**. Each grant **honors the spec** — a spec with no
  `writable_system:` key resolves to `writable-system` (ADR-0001).
- `start --profile <p>` is an optional **override forced across every grant**, for a run that
  wants one profile regardless of spec. Omitting `--profile` means "per-spec"; a present but
  empty `--profile` is rejected as a typo.

### The connection contract (the `acquire` stdout shape)

`acquire` prints exactly one line on stdout — the contract the client drives over adb. It carries
the **real** profile the device came up under (spec-resolved, or the start override):

```
serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system
```

`serial` is the broker's adb label for the device; a sandboxed client instead reaches it as
`host.docker.internal:<adb_port>` over the host loopback. Nothing else goes to stdout, so a
caller can capture this line directly; all progress is on stderr.

### The stop grace

`stop` sends `SIGTERM`, then waits up to `BROKER_STOP_GRACE` (default **600 s**) for the
daemon's EXIT trap to reclaim the pool. The grace is long on purpose: bash defers the trap until
any in-flight foreground `env-up` (a multi-minute cold boot) returns, and only then runs
`pool_teardown_all`. Out-waiting the boot lets the daemon clean up its own device; a boot that
outlasts the grace is escalated to `SIGKILL`, and the broker reclaims the pool itself so a
still-booting emulator is not orphaned.

### State and knobs

- `BROKER_DIR` — the daemon's file-backed request queue + pidfile + `broker.log`.
- `POOL_DIR` — the pool registry (default `<repo>/.pool`).
- `POOL_CAP` — max concurrent devices (default 6).
- `BROKER_STOP_GRACE` — stop grace in seconds (default 600).

## The lower layers

These do the real work; the broker and pool orchestrate them. Each script's own header comment
is the authoritative reference for its flags — this file does not duplicate them.

- **`bin/pool`** (over `bin/_pool.sh`) — the pool engine as a CLI: one-shot
  `acquire`/`release`/`status`/`down-all`/`demo` against the file-backed registry, no standing
  service. The broker wraps this engine; use `bin/pool` directly to drive the pool without a
  daemon.
- **`bin/env-up`** — boot one emulator from a device-spec YAML on an explicit port and, if an
  APK is given (`--apk <path>`, an explicit input — the device layer does not read it from the
  spec) and the spec's `provision` toggle isn't false, provision it to t=0 (root shell,
  frida-server, APK installed, settings normalized) and verify before printing the serial.
  Bare-boots with no APK. The pool/broker resolves the spec's `target_apk` and passes it here.
- **`bin/env-down`** — tear down what `env-up` created (kill the instance; delete the AVD unless
  `--keep-avd`). Symmetric with `env-up`: the harness invariant is "reset = full rebuild, no
  golden snapshot."
- **`bin/verify`** — exit 0 iff a device is at t=0: booted, frida-server reachable at the pinned
  version, and the target package installed. One clear reason on failure.
- **`bin/doctor`** — assert the host can build the harness at all: every tool pinned in
  `../versions.txt` plus the rootable system image, each problem printed with a `→` fix hint.

Internal helpers (`_broker.sh`, `_pool.sh`, `_provision.sh`, `_spec.sh`, `_device.sh`, `_lib.sh`,
`env.sh`) are sourced by the above and carry their own header comments.

## Typical bring-up

```bash
source bin/env.sh                       # PATH + versions.txt; see ../RUNBOOK.md step 0
bin/doctor                              # must exit 0
bin/broker start                        # once, per-spec profile
bin/broker acquire --spec configs/devices/rasp_dummy.yaml
#   → serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system
bin/broker status
bin/broker release --serial emulator-5554
bin/broker stop
```

For the full manual, from-nothing bring-up (and the writable-`/system` recon it records), see
[`../RUNBOOK.md`](../RUNBOOK.md).
