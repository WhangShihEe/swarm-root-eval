# 02: Bridged Claude Code smoke — real agent over the bridge via inspect_swe

**What to build:** swap ticket 01's mock solver for a **real Claude Code agent** running in an
Inspect sandbox over `sandbox_agent_bridge()`, standing on **`inspect_swe.claude_code()`**
(M1). The toy prompt makes the agent submit the token; the **same task/dataset/scorer from 01
are unchanged**. Proves the full path: bridge + CC + tool call + passive completion + logging,
**keyless** in the sandbox.

**Blocked by:** 01.

**Status:** blocked

- [ ] Solver = `inspect_swe.claude_code()` (bridge/sandbox delegated). Task, dataset, and
      scorer from 01 are reused verbatim — only the solver changes. `inspect_swe` pinned.
- [ ] Sandboxed CC runs **keyless** against `ANTHROPIC_BASE_URL=http://localhost:13131` with
      `model="inspect"`; the **host-side** `inspect eval --model anthropic/claude-…` provider
      serves the real call (S2). No Anthropic key in the image.
- [ ] Toy prompt → the agent **calls the submit tool** (or returns the token); the scorer
      greens; the transcript shows the model call(s) captured **passively**.
- [ ] Completion works with no explicit "done": the agent runs to completion and the solver
      result comes from `bridge.state`; the final output reaches the scorer.
- [ ] **Model sweep is a one-flag change** — re-run with a different `--model` and it still
      greens (a short demo/note is enough; the real sweep is gated on a first green later).
- [ ] Sandbox/image sourcing confirmed against `inspect_swe` docs: does `claude_code()`
      **provide** the CC sandbox/compose, or must we supply a Dockerfile/`compose.yaml`?
      Record the answer. Note the sandbox bridge **withholds** `web_search`/`code_execution`/
      `client_mcp_servers` by default (fine for smoke).
- [ ] Harness still Inspect-free; broker untouched.

## Notes
- This is the last purely-plumbing ticket. Once green, the bridge is trusted and grilling
  resumes for the orchestrator slice (ticket 03).
- Ref: https://meridianlabs-ai.github.io/inspect_swe/claude_code.html ,
  https://inspect.aisi.org.uk/agent-bridge.html .
