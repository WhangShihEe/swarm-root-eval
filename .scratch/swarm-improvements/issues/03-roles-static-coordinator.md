# 03: Roles — `static` and `coordinator`

**What to build:** Add two device-less worker roles alongside `dynamic`. A **`static`** worker gets no
device lease — only the sandbox with the APK staged — and runs a static-analysis-oriented mission (deep
decompilation/inspection/tests), sharing what it finds on the board. A **`coordinator`** worker gets no
device either; it observes the board (and the agents' statuses), spots which workstreams look promising,
and **directs** the other workers via board posts and DMs — a "middle manager". The coordinator is still
denied `done` (it cannot fake termination) and does **not** own the verdict: the host-side arbiter keeps
that (ADR-0002). The conductor leases a broker device **only for `dynamic`** workers. Ship
`configs/workers/static.yaml` and `configs/workers/coordinator.yaml`.

**Blocked by:** 01.

**Status:** implemented (hermetic; 254 tests pass; code-reviewed) — live multi-worker smoke on the
emulator broker pending (needs hardware; not runnable in this env).

- [x] An eval config mixing roles (e.g. `[{role: dynamic, count: 2}, {role: static, count: 1}, {role: coordinator, count: 1}]`) launches; only the `dynamic` workers lease a device.
- [x] The `static` worker runs its static-analysis mission against the staged APK with no device and posts findings to the board.
- [x] The `coordinator` reads the board + agent statuses and directs workers via board posts and DMs; it is denied `done`.
- [x] The verdict is still decided by the host-side arbiter, not the coordinator.
- [x] `configs/workers/static.yaml` and `configs/workers/coordinator.yaml` exist; role is selected by filename (no `kind` field).

## Comments

**Implementation (2026-09-23):** Roster threads through `swarm.py::build_config` → `SwarmConfig.roster`
→ `Conductor.run` (which flattens it to `worker-<i>`:role, source of truth for N). `_acquire_and_plan`
leases a device only for `DEVICE_ROLES` (`dynamic`); `static`/`coordinator` get a `RunSpec` with no
`DEVICE_CONTRACT`. The worker (`dynamic_agent.py`) dispatches on the injected `ROLE`: `static`/
`coordinator` get a device-less mission (`mission.build_static_mission` / `build_coordinator_mission`)
and **no** `inject_device` setup, so nothing fails fast on the absent contract; the coordinator's
peer directory rides in `SWARM_ROSTER`. Verdict quorum (`evaluate_board`) is restricted to the
`dynamic` deciders — a non-decider `success` is ignored and support-role silence never gates the run,
so the coordinator cannot own the verdict. Per-role mission notes via `load_target(spec, role=)`.
Shipped `configs/workers/{static,coordinator}.yaml` + demonstrator `configs/evals/rasp_dummy_swarm.yaml`.
Deferred: the live multi-worker smoke (broker/emulator) — hermetic coverage only in this env.
