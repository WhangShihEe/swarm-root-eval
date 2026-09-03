# 06: Broker service — standing process grants scoped device access on request

**What to build:** wrap the ticket-05 pool engine as a **long-running host process started
before any Inspect eval**. A client asks the broker to secure a device; the broker enforces
the pool cap, launches + provisions on grant, and returns a connection contract the client
uses to drive that device over **adb** (frida / objection / adb shell — brokered-adb access,
not a gesture API). The broker is the gate that makes emulators a scarce, shared resource.

**Blocked by:** 05.

**Status:** done

- [x] The broker runs as a standalone host process, launched before the eval, that persists across requests and owns the pool (outside any Inspect sample lifecycle).
- [x] A client `acquire` request returns a connection contract on grant, or a clean refusal when the pool (cap default **3**) is full — the broker enforces the cap, not the caller.
- [x] On grant the broker launches + provisions via ticket 05; the client can then reach the device over adb (frida-server up, adb shell usable) to run the offensive toolchain itself.
- [x] A `release` request tears the device down and rebuilds from scratch, freeing the slot.
- [x] Reachable from a separate process on the host now; reachable from a sandbox over `host.docker.internal` is a later concern, not required here.
- [x] The dynamic-agent launch profile (writable-`/system` vs Frida-only, per ticket 02's verdict) is a broker launch option, defaulting to the Frida-only recipe.
- [x] No Inspect import anywhere in the harness.

## Comments

**Done (2026-09-03).** The broker landed as a bash library + CLI wrapping the ticket-05 pool
engine verbatim (it drives `pool_acquire`/`pool_release`, no re-implementation). It is the
single standing owner of the pool: clients never touch the pool engine directly, they submit
requests to the broker, so the cap is always enforced against one consistent registry.

What landed:
- `bin/_broker.sh` — the broker engine. Transport is a **file-backed request/response queue**
  (not a socket): each client request is a dir under `BROKER_DIR/queue/<id>/` with a `req`
  file (verb on line 1, one arg per line); the serving process answers by writing `rc` then
  `resp` (atomic temp+mv) and the client polls for `resp`. Bash-native — **no `nc`/`socat`** —
  works across separate host processes, and makes the broker the single serializer of pool
  access. `broker_serve` is the standing loop; `broker_handle` dispatches
  `acquire`/`release`/`status`/`list`/`ping`/`shutdown`; `broker_request` is the client side.
  On grant the response is the pool contract **plus the launch profile**:
  `serial=… console_port=… adb_port=… profile=frida-only`. On the broker's exit it reclaims
  every device (`pool_teardown_all`), so no emulator outlives the broker.
- `bin/broker` — the CLI: `start [--profile …] [--foreground]` / `stop` / `acquire` /
  `release` / `status` / `list` / `ping` / `demo`. `start` daemonizes (re-execs a hidden
  `__serve`, which writes its own pidfile) and waits for liveness; `stop` signals the daemon,
  waits out any in-flight boot so the daemon's own teardown runs, then clears runtime state
  (keeps `broker.log`). `demo` is the live acceptance path: start, grant 2, release both, stop.
- `tests/broker.sh` — **54 hermetic assertions**. The pool engine's bring-up/teardown are
  **injected as fakes** (`POOL_ENV_UP`/`POOL_ENV_DOWN`), so dispatch, the cap-relay (broker,
  not caller, refuses the N+1th with rc 3), the launch-profile gate, bring-up-failure
  reclamation, and the **full start→acquire→release→stop lifecycle against a real background
  broker process** are all covered with no real emulator. Added a no-Inspect-import guard over
  `bin/`. Full suite: 54 + 48 + 21 + 14 + 14 = **151 green**.
- `.gitignore` — ignores the runtime `/.broker/` state dir (override with `BROKER_DIR`).

Design notes / decisions:
- **Serial by design.** One request is handled to completion before the next, so an in-flight
  `acquire` blocks the queue while its emulator cold-boots (minutes). This keeps the owner
  single-threaded and the cap trivially correct; a concurrency layer is a later optimization,
  not needed for a cap-3 pool where N=1 is the default path.
- **Launch profile.** `--profile` is a broker-level option defaulting to **frida-only** (the
  wired recipe — provisioning writes only to `/data`). `writable-system` is a *recognized*
  profile but is not yet wired into env-up (it stays opt-in, RUNBOOK), so starting under it
  **fails fast** with a pointer to ticket 02's verdict rather than silently delivering
  frida-only. A single `broker_profile_gate` is the source of truth for both the daemon and
  the CLI.
- **Brokered-adb, not a gesture API.** The grant is a connection contract; the client runs
  frida / objection / adb-shell itself. `host.docker.internal` reachability from a sandbox is
  explicitly out of scope here — the queue dir is the seam a socket shim would later wrap.
- No Inspect import anywhere (asserted by the suite).

**Code review (two-axis) fixes folded in:**
- **bash 3.2 `shift 2` hang** — a value-taking flag given no value (`broker acquire --spec`
  with nothing after it) looped forever, because on macOS's default bash `shift 2` with one
  positional left is a silent no-op. Switched every flag parse to the repo's safe idiom
  `shift $(( $# > 1 ? 2 : 1 ))` (as in env-up/env-down); three watchdog tests prove it errors
  (rc 2) instead of hanging.
- **Client-timeout device leak** — a client that gave up mid-acquire removed its request dir,
  but the daemon went on to boot + register the device, leaking a scarce slot until the next
  `stop`. The daemon now detects the abandoned request when it finishes and **auto-releases**
  the just-granted device; the default client wait was also raised (600→**1800s**) so a client
  queued behind another's boot out-waits both. Covered by a slow-fake-boot integration test.
- **Concurrent-`start` TOCTOU** — two racing `start`s could spawn two daemons clobbering one
  pidfile (one untracked, leaking on shutdown). `broker_serve` now **claims the pidfile
  atomically** (noclobber create; a dead pidfile is reclaimed as stale, a live one is
  refused). Tested by a second serve against a live pidfile refusing with rc 1.
- **`stop` mid-boot orphan** — force-killing the daemon after 30s would orphan a still-booting
  emulator (bash defers the TERM trap until the foreground env-up returns; macOS has no
  `setsid` for process-group kills). `stop` now waits `BROKER_STOP_GRACE` (default **600s**)
  so the daemon out-lives the boot and runs its own teardown; the residual (a boot outlasting
  the grace) is logged, not hidden.
- **demo masked a failed query** — `broker_request list | grep -c .` printed `0` on empty
  input even when the query itself failed, so demo could report "pool clean — OK" without
  verifying. It now captures the listing and treats a failed query as an error.
- **DRY** — the launch-profile validation + its long messages were duplicated in the daemon
  and the CLI; unified into `broker_profile_gate`.
- Abandoned answered-request dirs (a client that crashed *after* being answered) are skipped
  cheaply but not GC'd mid-run — `stop` wipes the queue and a per-eval broker's lifetime bounds
  accumulation; a reaper is noted as out-of-scope for a long-lived broker.
