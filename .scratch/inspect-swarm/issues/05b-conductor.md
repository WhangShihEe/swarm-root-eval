# 05b: Conductor — launcher + arbiter + termination + device-linking + log correlation

**What to build:** the external swarm layer that turns N ticket-04 agents + the 05a board into
one swarm run. A **Python launcher** in `swarm-eval/` starts N worker runs + 1 arbiter run as
separate `inspect eval` subprocesses, wires them to a per-swarm board and (for dynamic roles)
broker devices, ends the run, and collates everything under one swarm-id.

**Blocked by:** 04 (the agent unit), 05a (the board).

**Status:** stub-ready (grill settled; build after 04's live run + 05a)

## Acceptance
- [ ] **Launcher = Python CLI in `swarm-eval/`.** Per swarm run it: mints a `swarm-id`; creates
      the board dir (05a) at `BOARD_DIR/<swarm-id>/`; **pre-acquires one device per dynamic
      role** from `bin/broker` (≤ cap 3 — **fail-fast or queue** if over); launches **N worker**
      `inspect eval` subprocesses + **1 arbiter** subprocess.
- [ ] **Injection (env vars per run):** `BOARD_DIR`, `SWARM_ID`, `AGENT_ID`, `ROLE`,
      `DEVICE_CONTRACT` (path, dynamic roles only), `INSPECT_LOG_DIR=logs/<swarm-id>/`. Each
      run's task/solver reads these and wires the sandbox + bridged board tools.
- [ ] **Device budget owned by the launcher** (lifts 04's solver-acquire to the swarm level):
      guaranteed release of every device at teardown, even if a run crashes; the broker still
      enforces the hard cap.
- [ ] **Arbiter = its own bridged run + the swarm oracle.** Reads the board; posts a reserved
      `done`+verdict message: **success** on the first credible `success` claim (self-report
      MVP), **fail** when all workers post `giveup` or a max wall-clock/rounds budget elapses.
- [ ] **Termination, three layers:** (a) workers `list_messages` each step and **stop when
      `done` is posted** (cooperative, best-effort); (b) a **per-run Inspect time/message limit**
      (no run loops forever); (c) **launcher kills** any run alive after `done` + grace.
- [ ] **Log correlation + board saved:** all worker + arbiter `.eval` logs land in
      `logs/<swarm-id>/` (via `INSPECT_LOG_DIR`), each stamped with `swarm-id/agent-id/role` eval
      metadata; the launcher also **copies the messageboard dir into `logs/<swarm-id>/`** so the
      full swarm run (transcripts + the conversation) is one saved artifact.
- [ ] **N=1-is-single, uniform path:** N=1 = one worker + arbiter, a one-participant board — the
      same code path as N>1, not special-cased.
- [ ] **Ordering:** board up → devices acquired → worker+arbiter runs launched → wait for `done`
      → collate + save board → release all devices → teardown. A failure at any step still
      releases devices and saves what exists.
- [ ] Harness stays Inspect-free; broker + board used as clients.

## Notes / deferred
- Arbiter uses **self-report** now; the machine-checkable oracle is **ticket 06** (gates the
  model sweep). The arbiter is the seam where it swaps in — termination wiring stays.
- **Collaboration protocol** (subtask claiming / decomposition) is out of scope — agents
  self-coordinate in free text on the append-only board. Enrichment later.
- **Who acquires at N** = launcher pre-acquire (settled); agent-on-demand acquire via a bridged
  tool remains a later option.
- See ADR-0002 and `spec.md`.
