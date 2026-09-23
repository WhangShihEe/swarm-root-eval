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

**Status:** ready-for-agent

- [ ] An eval config mixing roles (e.g. `[{role: dynamic, count: 2}, {role: static, count: 1}, {role: coordinator, count: 1}]`) launches; only the `dynamic` workers lease a device.
- [ ] The `static` worker runs its static-analysis mission against the staged APK with no device and posts findings to the board.
- [ ] The `coordinator` reads the board + agent statuses and directs workers via board posts and DMs; it is denied `done`.
- [ ] The verdict is still decided by the host-side arbiter, not the coordinator.
- [ ] `configs/workers/static.yaml` and `configs/workers/coordinator.yaml` exist; role is selected by filename (no `kind` field).
