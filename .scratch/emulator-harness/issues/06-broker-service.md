# 06: Broker service — standing process grants scoped device access on request

**What to build:** wrap the ticket-05 pool engine as a **long-running host process started
before any Inspect eval**. A client asks the broker to secure a device; the broker enforces
the pool cap, launches + provisions on grant, and returns a connection contract the client
uses to drive that device over **adb** (frida / objection / adb shell — brokered-adb access,
not a gesture API). The broker is the gate that makes emulators a scarce, shared resource.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] The broker runs as a standalone host process, launched before the eval, that persists across requests and owns the pool (outside any Inspect sample lifecycle).
- [ ] A client `acquire` request returns a connection contract on grant, or a clean refusal when the pool (cap default **3**) is full — the broker enforces the cap, not the caller.
- [ ] On grant the broker launches + provisions via ticket 05; the client can then reach the device over adb (frida-server up, adb shell usable) to run the offensive toolchain itself.
- [ ] A `release` request tears the device down and rebuilds from scratch, freeing the slot.
- [ ] Reachable from a separate process on the host now; reachable from a sandbox over `host.docker.internal` is a later concern, not required here.
- [ ] The dynamic-agent launch profile (writable-`/system` vs Frida-only, per ticket 02's verdict) is a broker launch option, defaulting to the Frida-only recipe.
- [ ] No Inspect import anywhere in the harness.
