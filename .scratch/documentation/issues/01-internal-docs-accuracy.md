# 01: Internal docs accuracy

**What to build:** The accurate internal reference docs that the public README will link into,
plus a cleanup of the stale agent-facing docs. After this ticket, an engineer (or agent)
reading the in-repo docs gets a correct picture of the broker and the Inspect layer, and the
agent-facing briefs match reality.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `bin/README.md` created: how the emulator broker works and its interfaces — `start`/`stop`
      (incl. the profile override and stop grace), `acquire`/`release`/`status`/`list`/`ping`/`demo`,
      and the connection-contract stdout shape (`serial= console_port= adb_port= profile=`). Point at
      the lower layers (`pool`, `env-up`/`env-down`, `verify`, `doctor`) without duplicating their
      header comments.
- [x] `swarm-eval/README.md` filled (currently empty): single vs swarm entrypoints
      (`single_agent.py`, `swarm.py`), the message board (append-only, `board` MCP tools, taxonomy,
      host-stamped author), the cyber tools exposed to agents (frida/objection/androguard, jadx/apktool,
      the non-interactive `frida-run`), logging (`logs/<run-id>` / `logs/<swarm-id>`, `inspect view`),
      and the full **non-traditional-Inspect** story (parallel independent Inspect instances joined only
      by the board; per-agent Inspect env for log clarity; no built-in multi-swarm parallelism;
      CC-harness-per-agent, un-swept).
- [x] `CLAUDE.md` refreshed: it understates current state — the emulator-harness dir holds 8 tickets
      (not 6), and the Inspect swarm layer (`inspect-swarm/`) exists and runs rather than being
      "designed but not yet ticketed."
- [x] `RUNBOOK.md` refreshed to the standardized **android-35** image; stale API-37.1 references
      reconciled or flagged (see the `versions.txt` note below).
- [x] The dangling `triage-labels.md` reference in `docs/agents/issue-tracker.md` is resolved
      (create the file, or remove the reference).
- [x] The `versions.txt` `SDK_PLATFORM_API=37.1` vs android-35 inconsistency is **noted** for the env
      workstream (out of scope to fix here; docs must not over-claim android-35 where it isn't verified).
