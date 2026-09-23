# swarm-root-eval

A **capability probe**: can a swarm of Claude Code agents (N workers, bridged
into Inspect) **compromise a real Android app** — bypass its
anti-root / RASP checks and find & build exploits from a running APK? 

This is feasibility + discovery, **not** a fairness-controlled single-vs-swarm benchmark. The agent's interface is always one **APK file in**;
the harness is APK-agnostic. See `CONTEXT.md` for the vocabulary.

**Harness and Inspect are kept separate.** The first deliverable was an Inspect-free emulator
**broker + harness** — the device layer that must be running before any eval — tracked as
8 chained tickets in `.scratch/emulator-harness/issues/` (01→08); see `bin/README.md`. The
Inspect swarm layer now **exists and runs**: `swarm-eval/` bridges N Claude Code agents into
Inspect (`swarm.py` → `conductor.py`, a host-side messageboard + arbiter; `single_agent.py` for
the N=1 case), tracked in `.scratch/inspect-swarm/issues/`; see `swarm-eval/README.md`. The
machine-checkable scoring oracle and the model sweep are the remaining work.

## Agent skills

### Issue tracker

Issues and specs live as local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
