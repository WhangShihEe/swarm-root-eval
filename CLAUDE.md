# swarm-root-eval

Eval comparing a single model vs a swarm (orchestrator + N workers, all Claude Code via
Inspect's `sandbox_agent_bridge()`) on Android app pentest tasks. First deliverable: an
Inspect-free emulator harness (see `tickets/`).

## Agent skills

### Issue tracker

Issues and specs live as local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
