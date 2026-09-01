# swarm-root-eval

A **capability probe**: can a swarm of Claude Code agents (orchestrator + N workers, bridged
into Inspect via `sandbox_agent_bridge()`) **compromise a real Android app** — bypass its
anti-root / RASP checks and find & build exploits from a running APK? Secondary: a **model
sweep** (swap Claude variants, later cross-vendor, behind the bridge) to see which do better.

This is feasibility + discovery, **not** a fairness-controlled single-vs-swarm benchmark:
"single agent" is just the swarm at **N=1**. The agent's interface is always one **APK file in**;
the harness is APK-agnostic. See `CONTEXT.md` for the vocabulary.

**Harness and Inspect are kept separate.** Current deliverable: an Inspect-free emulator
**broker + harness** — the device layer that must be running before any eval. Tracked as
6 chained tickets in `.scratch/emulator-harness/issues/` (01→06). The Inspect bridge, the
swarm/orchestrator, the scoring oracle, and the model sweep are a **separate later feature**,
designed but not yet ticketed.

## Agent skills

### Issue tracker

Issues and specs live as local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
