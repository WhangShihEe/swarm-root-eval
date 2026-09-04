# 04: Dynamic-agent slice — broker device + adb/frida on RootBeer  [STUB — grill before building]

**Status:** stub (do not build — resume grilling first)

**Blocked by:** 03.

**Goal (settled):** a **worker becomes a dynamic agent** (CONTEXT term: static tools **plus** a
broker-granted emulator + frida). It acquires a device from the **broker** (already done),
reaches it over **adb**, and runs a real offensive loop against **RootBeer** — the first rung
of the target ladder. This is the slice that must cross the **sandbox → host → broker → adb**
boundary the harness deliberately deferred.

**Why a stub:** the broker-reach mechanism and the oracle both depend on choices made in the
orchestrator slice (isolation, who owns the device budget). Grill after 03.

## Open questions to grill (resume here)
1. **Broker reach from the sandbox** — `inspect_swe` **`bridged_tools`** (host-side Inspect
   tools exposed to the sandboxed agent over a generated stdio MCP server — wrap
   `bin/broker acquire/release`) **vs** `host.docker.internal` + adb port-forwarding into the
   container. The broker's file-backed **queue dir** is the seam a socket/tool shim wraps.
2. **Who calls acquire/release** — the Inspect **solver setup/teardown**, or the **agent** via
   a bridged tool? How the connection contract (`serial/console_port/adb_port/profile`) is
   handed to the worker.
3. **Cap vs N vs epochs** — broker cap (default 3, serial boots) vs swarm N vs Inspect sample
   concurrency/epochs, so the cap is never oversubscribed.
4. **Oracle evolution** — move from self-report to RootBeer's machine-checkable signal
   (logcat/state observed independently) — the real oracle per CONTEXT.
5. **Toolchain in the sandbox** — frida/objection/adb availability inside the CC sandbox image;
   whether the offensive loop needs provider-side `web_search`/`code_execution` (withheld by
   default on the sandbox bridge).
6. **Launch profile** — broker defaults to **frida-only** (`/system` untouched);
   `writable-system` is recognized but not wired (fails fast). Confirm frida-only is the
   dynamic-agent profile for this slice.

## Established context (so grilling can resume cold)
- Broker is **done**: standing host process, file-backed queue, `bin/broker`
  acquire/release/status/list/ping, grant = connection contract + profile, cap 3, serial.
  `host.docker.internal` reachability was left out of the harness on purpose. See
  `.scratch/emulator-harness/issues/06-broker-service.md`.
- First green here **unlocks the model sweep** (gated on a first green per CONTEXT) and the
  harder ladder rungs (RASP → real) as additional samples.
- See `spec.md` "Deferred decisions → Slice 3".
