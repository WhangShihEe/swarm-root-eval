# 05: Pool engine — launch, track, and reclaim N provisioned devices

**What to build:** an in-process engine that brings up N provisioned devices at once on
distinct ports (reusing ticket 04's provisioning), tracks them in a registry, and hands out
**addressable device handles**. `acquire()` returns a connection contract a caller can reach
the device with; `release()` reclaims by full teardown + rebuild. No standing service yet —
this is the engine the broker (ticket 06) wraps.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] Bring up N provisioned devices on distinct console/adb port pairs (5554/5555, 5556/5557, …), each with isolated writable data.
- [ ] A registry maps serial → console port → adb port → status (building/booting/ready/down).
- [ ] `acquire()` returns a connection contract `{serial, console_port, adb_port}` and flips status to in-use; `release()` tears the instance down and rebuilds from scratch. No scheduling policy yet.
- [ ] Pool size is capped at a single config value (default **3**), not baked into the code; `N=1` is the default path and is not special-cased.
- [ ] Demoable via a script: acquire 2 devices, print their adb serials, release both — registry ends clean.
