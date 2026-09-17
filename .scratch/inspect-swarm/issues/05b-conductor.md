# 05b: Conductor — launcher + arbiter + termination + device-linking + log correlation

**What to build:** the external swarm layer that turns N ticket-04 agents + the 05a board into
one swarm run. A **Python launcher** in `swarm-eval/` starts N worker runs + 1 arbiter run as
separate `inspect eval` subprocesses, wires them to a per-swarm board and (for dynamic roles)
broker devices, ends the run, and collates everything under one swarm-id.

**Blocked by:** 04 (the agent unit), 05a (the board).

**Status:** built (hermetic; awaits a hand-run live swarm like 04/05a). Implemented on the
`ticket-05b-conductor` worktree.

## Acceptance
- [x] **Launcher = Python CLI in `swarm-eval/`** (`swarm.py` + `swarm_eval.conductor`). Per swarm
      run it: mints a `swarm-id`; creates the board dir (05a) at `BOARD_DIR/<swarm-id>/`;
      **pre-acquires one device per worker** (the dynamic role) from `bin/broker` (≤ cap 3 —
      **fail-fast** if over, see deviation ①); launches **N worker** `inspect eval` subprocesses
      (the arbiter is host-side, deviation ②).
- [x] **Injection (env vars per run):** `BOARD_DIR`, `SWARM_ID`, `AGENT_ID`, `ROLE`,
      `DEVICE_CONTRACT` (path, dynamic roles only), `SWARM_WORKER_IDS` (the roster),
      `INSPECT_LOG_DIR=logs/<swarm-id>/`. `dynamic_agent.py` reads these (dual-mode) and wires
      the sandbox + bridged board tools.
- [x] **Device budget owned by the launcher** (lifts 04's solver-acquire to the swarm level):
      `_release_all` in a `finally` frees every acquired device at teardown, even mid-acquire or
      on a crash; the worker skips its own release in swarm mode (`device_owner=launcher`) so no
      double-free; the broker still enforces the hard cap.
- [x] **Arbiter = the swarm oracle** (host-side rubric, deviation ②). `evaluate_board`/`arbitrate`
      read the board and post a reserved `done`+verdict: **success** on the first credible
      `success` claim (self-report MVP), **fail** when all workers post `giveup` or the launcher
      wall-clock budget elapses.
- [x] **Termination, three layers:** (a) workers poll the board and **stop when `done` is posted**
      (in the collaboration prompt); (b) a **per-run Inspect `--time-limit`/`--message-limit`**
      passed by the launcher; (c) launcher `_terminate` kills any run alive after `done` + grace.
- [x] **Log correlation + board saved:** worker `.eval` logs land in `logs/<swarm-id>/` (via
      `INSPECT_LOG_DIR`); each run stamps `{swarm_id, agent_id, role}` into the task metadata; the
      launcher copies the board into `logs/<swarm-id>/messageboard/` so the run (transcripts + the
      conversation + the `.device` contracts) is one saved artifact.
- [x] **N=1-is-single, uniform path:** N=1 = one worker + the host-side arbiter over a
      one-participant board — the same `run()` path as N>1 (test proves the board ends with just
      `worker-1` + the arbiter's `done`).
- [x] **Ordering:** board up → devices acquired (all, before any launch) → worker runs launched →
      arbitrate → post `done` → `finally`: terminate + save board + release all. A failure at any
      step still releases devices and saves what exists.
- [x] Harness stays Inspect-free; broker (`broker_client`) + board (05a) used as clients.

## Notes / deferred
- Arbiter uses **self-report** now; the machine-checkable oracle is **ticket 06** (gates the
  model sweep). `evaluate_board` is the exact seam where it swaps in — the launch/termination/
  collation wiring around it is unchanged.
- **Collaboration protocol** (subtask claiming / decomposition) is out of scope — agents
  self-coordinate in free text on the append-only board. Enrichment later.
- **Who acquires at N** = launcher pre-acquire (settled); agent-on-demand acquire via a bridged
  tool remains a later option.
- See ADR-0002 and `spec.md`.

## Deviations from the stub (settled with the user during build)
① **Fail-fast, not queue,** when workers > cap — simplest correct MVP; the broker still enforces
   the hard cap. Queueing over-cap runs is deferred.
② **Arbiter = a host-side rubric in the launcher, not its own bridged Inspect run.** An LLM
   cannot be trusted to honour a wall-clock/rounds budget, and the self-report rubric is
   machine-decidable — so there is no arbiter subprocess; `Conductor` runs `arbitrate` in-process
   and posts the `done` verdict directly through `Board`. Everything the stub wanted of the
   arbiter (read the board → apply the rubric → post `done`+verdict → be the swarm oracle → be
   the ticket-06 seam) holds; only its *hosting* moved host-side, which also hardens termination.
   **Consequence:** the launcher starts N subprocesses, not N+1.

## Comments

**Built (2026-09-17), worktree `ticket-05b-conductor`** (isolated because ticket 07 is editing
`dynamic_agent.py`/`mission.py` in parallel — this branch will need a merge there).

- `swarm-eval/src/swarm_eval/conductor.py` — the Conductor: `mint_swarm_id`, `SwarmConfig`,
  `build_run_env`/`build_run_argv` (the injection contract), `evaluate_board`/`arbitrate` (the
  host-side self-report rubric = the 06 oracle seam), and `Conductor.run` (board up → acquire all
  → launch → arbitrate → post `done` → `finally`: terminate/save-board/release-all). Runner,
  broker, and clock are injectable for hermetic testing.
- `swarm-eval/swarm.py` — the launcher CLI (`python swarm.py --workers N --model …`), exit 0/1/2
  = success/failure/setup-error.
- `swarm-eval/dynamic_agent.py` — made **dual-mode**: standalone (acquire+release itself, ticket
  04) vs swarm worker (read the injected `DEVICE_CONTRACT`, launcher owns the lease, board tools
  + collaboration prompt, `{swarm_id,agent_id,role}` metadata). Mode = presence of
  `DEVICE_CONTRACT`.
- `swarm-eval/src/swarm_eval/broker_client.py` — `Contract.render_contract_line()` (symmetric
  with `parse_contract`) so the launcher relays a pre-acquired contract to a worker as a file.

**Verification:** 98 tests pass (39 new: conductor orchestration incl. guaranteed partial-release,
budget timeout, cooperative-grace-then-kill, partial-launch teardown, board collation; dual-mode
worker; CLI exit codes). The live N-run swarm proof is to be run by hand with a broker up (like
04/05a).

**Reviewed** (two-axis Standards+Spec, `code-review` skill). Fixes applied from the pass:
a partial-launch orphan (handles now appended incrementally so an already-spawned run is torn
down if a later launch raises); the cooperative-stop window (`_shutdown` now waits the grace for
runs to exit on `done` *before* SIGTERM, so termination layer (a) actually happens); layer (b)
now on by default (`DEFAULT_TIME_LIMIT`); and the message-type taxonomy is shared named constants
(`messageboard.TYPE_*`) instead of re-typed strings in the arbiter.
