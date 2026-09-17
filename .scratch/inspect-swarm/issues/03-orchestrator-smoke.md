# 03: Orchestrator smoke — a CC orchestrator spawns a subagent that runs a command

> **SUPERSEDED (2026-09-17).** The Fork-A approach (one CC agent spawning subagents) was
> abandoned after the bridge proved unable to attribute concurrent-subagent model calls to
> their own transcript spans — the calls collapse onto the parent agent span, so subagent
> traces interleave (verified live: 10/11 model events attributed to the orchestrator span,
> subagent spans empty). The swarm pivoted to **separate Inspect runs per agent** (one agent =
> one run = one bridge = one clean transcript), collaborating via an external messageboard.
> See tickets **04** (single dynamic agent, end-to-end) and **05** (swarm framework). Kept for
> the rationale; do not build.

**What to build:** extend the smoke so the top-level `claude_code()` agent acts as a **thin
orchestrator** (Fork A): given a task param `N`, its dispatcher prompt spawns `N` **built-in
general-purpose subagents** (Claude Code's Task tool + Bash), each runs a command, and the
orchestrator **relays their output**. Still **no broker, no device, no offensive toolchain,
same minimal image, self-report scoring** — this is the plumbing proof that fan-out works and
is bridged/logged, and that **N=2 is a prompt change, not new plumbing**.

**Blocked by:** 02 (done).

**Status:** superseded (see tickets 04 & 05)

- [ ] Orchestrator = the top-level `claude_code()` agent with a **thin dispatcher** system
      prompt that takes `N`; workers = Claude Code's **built-in general-purpose subagents**
      (Task + Bash). **No custom worker/subagent definition yet** (that arrives with the
      dynamic agent, ticket 04).
- [ ] Each spawned subagent runs a command in the sandbox (e.g. `echo <nonce>`) and returns
      its output; the orchestrator relays **every** nonce in its final message.
- [ ] Scorer greens on **BOTH** (the false-green trap): **(a)** all expected nonces
      round-trip in the final message (reuse/extend `token_present`), **and** **(b)** the
      transcript shows a **genuine subagent spawn** (a Task/subagent event). A lazy
      orchestrator that runs the command *itself* (it has Bash) must **fail (b)** — otherwise
      you've "proven" fan-out that never happened.
- [ ] `N` is a **task param** that feeds the orchestrator prompt. `inspect eval` demoed at
      **N=1 and N=2** (two subagents, distinct nonces, both relayed) — proving N=2 is a prompt
      change with no plumbing change. This is the actual validation of the infra goal.
- [ ] Verify against `inspect_swe` docs whether subagents work **out of the box** or need a
      `subagents=` / `subagent_model` config on `claude_code()`; **record the answer** in Notes.
- [ ] Same minimal sandbox image (curl + `claude`), keyless bridge, self-report scoring. No
      broker, no device, no frida/adb/objection.
- [ ] Harness stays Inspect-free; broker untouched.

## Notes
- **Why (b) matters:** the orchestrator is an LLM with its own Bash tool, so a token-only
  scorer greens even with zero delegation. Asserting a real subagent spawn is the whole point
  of this ticket.
- `subagent_model` (if present) later lets a model sweep route worker models separately from
  the orchestrator — not needed now, but it's the seam.
- Fork A means subagents share the orchestrator's **one container** (logical, not physical,
  isolation). Fine here; whether that holds for device-per-worker is a ticket-04 question.
- Ref: https://meridianlabs-ai.github.io/inspect_swe/claude_code.html
