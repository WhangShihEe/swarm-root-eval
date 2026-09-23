# ADR-0002: Swarm = separate Inspect runs + external messageboard, not a central orchestrator

**Status:** accepted (2026-09-17)

## Context

The swarm was originally modelled as **one Inspect run**: a top-level Claude Code
"orchestrator" agent that spawns N worker **subagents** (Claude Code's Task tool) — "Fork A".
When built, the agent bridge could not attribute concurrent-subagent model calls to their own
transcript spans: the calls collapse onto the parent agent's span. Verified live on a 3-subagent
run — **10 of 11 model events attributed to the orchestrator span; two subagent spans were
empty**. So subagent traces interleave and per-worker observability is lost.

Root cause: the sandbox bridge is an HTTP proxy on one port, and generations run in a sandbox
service task holding the context captured when the bridge was entered (the top-level agent), so
it cannot reliably map a concurrent request back to the subagent that made it. This is inherent
to the bridge, not a bug in our code.

Inspect's own within-run parallelism (samples/epochs) was also considered and rejected: it is
designed to repeat the *same* problem for statistical consistency, not to run distinct
collaborating agents. And Inspect has **no cross-run shared state**, so N separate runs cannot
coordinate *through Inspect*.

## Decision

The swarm is **N separate Inspect runs**, one bridged Claude Code agent each — so each agent has
its own bridge and its own clean transcript (the interleaving is gone by construction). Agents
collaborate through an **external, host-side messageboard** (append-only, one file per message;
reached via `inspect_swe` `bridged_tools`). A separate **arbiter** run judges completion and
issues the verdict (the swarm oracle for now). An external **launcher** starts the runs, creates
the board, links broker devices, and correlates logs under a swarm-id.

Inspect is thus used **per agent** — for consistency, logging, and the CC bridge — while the
swarm layer (launcher, board, arbiter, cross-run scoring) lives **outside** Inspect.

## Consequences

- **Clean per-agent transcripts**; per-worker observability restored.
- **No central orchestrator**; coordination is peer collaboration via the board (stigmergy),
  with a dedicated arbiter for termination/verdict. `N=1-is-single` still holds (one run,
  one-participant board). (The later `coordinator` role — swarm-improvements ticket 03 — does
  **not** reverse this: it is one more separate peer run that only *advises* via the board/DMs; it
  spawns no one, owns no run's lifecycle, is denied `done`, and is excluded from the verdict, so
  the arbiter still owns termination. It is not the rejected Fork-A orchestrator.)
- **More machinery outside Inspect** — a standing messageboard + a launcher/collator, siblings
  to the broker — and **swarm success must be computed externally** (no native Inspect fold of N
  runs into one predicate).
- The earlier "N=2 = a prompt change" property is retired; **N = how many runs the launcher
  starts.**
- Supersedes the Fork-A design (see `.scratch/inspect-swarm/issues/03-orchestrator-smoke.md`).
