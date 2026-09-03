# 05: Pool engine — launch, track, and reclaim N provisioned devices

**What to build:** an in-process engine that brings up N provisioned devices at once on
distinct ports (reusing ticket 04's provisioning), tracks them in a registry, and hands out
**addressable device handles**. `acquire()` returns a connection contract a caller can reach
the device with; `release()` reclaims by full teardown + rebuild. No standing service yet —
this is the engine the broker (ticket 06) wraps.

**Blocked by:** 04.

**Status:** done

- [x] Bring up N provisioned devices on distinct console/adb port pairs (5554/5555, 5556/5557, …), each with isolated writable data.
- [x] A registry maps serial → console port → adb port → status (building/booting/ready/down).
- [x] `acquire()` returns a connection contract `{serial, console_port, adb_port}` and flips status to in-use; `release()` tears the instance down and rebuilds from scratch. No scheduling policy yet.
- [x] Pool size is capped at a single config value (default **3**), not baked into the code; `N=1` is the default path and is not special-cased.
- [x] Demoable via a script: acquire 2 devices, print their adb serials, release both — registry ends clean.

## Comments

**Done (2026-09-03).** In-process pool engine landed as a bash library + CLI, reusing
ticket 04's `env-up`/`env-down` verbatim for bring-up and teardown (no re-implementation of
t=0). Hermetic tests green (42 assertions); the live bring-up path is `bin/pool demo`.

What landed:
- `bin/_pool.sh` — the engine. A **file-backed registry** (one `key=value` file per slot
  under `POOL_DIR/slots/<console_port>`: serial / console_port / adb_port / status / spec /
  avd_home) so a standing broker (ticket 06) survives across requests and a demo can inspect
  it between calls. `pool_acquire SPEC [env-up args…]` enforces the cap, picks the lowest
  free even console port in **5554–5584** (adb = console+1), gives the slot **its own
  `ANDROID_AVD_HOME`** (isolated AVD + writable userdata even when N slots share one spec),
  then runs `env-up --spec … --port …` and prints the connection contract
  `serial=… console_port=… adb_port=…`. `pool_release PORT|serial` tears down via
  `env-down` (kill + delete AVD on the slot's own AVD home) and deregisters; the freed port
  is reused by the next acquire ("reset = full rebuild", no snapshot). `pool_status`,
  `pool_list`, `pool_teardown_all` round it out. Statuses: building (env-up in progress) →
  in-use; down is transient during release. building spans create+boot+provision because the
  engine reuses env-up as one atomic bring-up.
- `bin/pool` — thin CLI: `acquire` / `release` / `status` / `list` / `down-all` / `demo`.
  Trailing acquire args (e.g. `--target-apk`) pass through to env-up. The `demo` subcommand
  is the acceptance script: acquire 2, print both adb serials, release both, assert the
  registry ends clean.
- `tests/pool.sh` — 42 hermetic assertions. The bring-up/teardown commands are **injected**
  (`POOL_ENV_UP`/`POOL_ENV_DOWN`) as fakes, so port allocation, registry CRUD, cap
  enforcement (`N+1`th acquire refused, rc 3), status transitions (slot is `building` while
  env-up runs), distinct-port + isolated-avd-home allocation, arg pass-through, release by
  port **and** by serial, port reuse after release, and bring-up-failure slot reclamation
  are all covered with **no real emulator**. Full suite green (42+21+14+14).
- `.gitignore` — ignores the runtime `/.pool/` state dir (override with `POOL_DIR`).

Design notes:
- **N=1 is not special-cased** — one acquire is the same code path as N; the cap
  (`POOL_CAP`, default 3) is a single config value, not baked in.
- **Isolation via per-slot `ANDROID_AVD_HOME`** rather than per-slot AVD names: `env-up`
  already honors `ANDROID_AVD_HOME` + `--port`, so the same spec name in distinct AVD homes
  yields distinct emulator locks + writable userdata. This is the one piece proven by design
  (SDK honors `ANDROID_AVD_HOME` for both `avdmanager create` and `emulator -avd`) rather
  than by the hermetic suite — `bin/pool demo --spec devices/rootbeer.yaml` exercises it live.
- No scheduling policy, no standing service, no Inspect import — those are ticket 06.

**Code review (two-axis) fixes folded in:**
- **Port ownership** — a caller-supplied `--port`/`--spec` in acquire's passthrough would let
  env-up honor the *last* `--port` and desync the registry (slot named X, emulator on Y). The
  engine now rejects those flags (rc 2); everything else (e.g. `--target-apk`, `--window`)
  still forwards.
- **Atomic port reservation** — port claim was a read-then-write (`_pool_free_port` picked;
  the slot file was written ~18 lines later), so two concurrent acquires could pick the same
  port. Reservation is now an atomic `mkdir` of the slot dir (fails if it exists), so a
  back-to-back broker can't collide. `_pool_free_port` stays as a read-only query.
- **Registry robustness** — `pool_slot_set` no longer feeds values to `sed`; it filters the
  old key with `grep -v` and appends the new value via `printf` (temp + `mv`), so a value
  with sed metacharacters (`| & / \`) can't corrupt the slot file.
- **Status doc = code** — the header no longer lists a `ready` state the code never sets;
  acquire is atomic (building → in-use), and that is what's documented.
- **Demo teardown** — the demo releases *both* devices unconditionally (was `&&`, which would
  leak the second on a first-release error).
- Two hermetic assertions added for the reserved-flag rejection and the sed-metacharacter
  round-trip. Suite: 48 pool + 21 + 14 + 14 = **97 green**.
