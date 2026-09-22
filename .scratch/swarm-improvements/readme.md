# Seed: swarm-improvements

Context-seed for a future grilling session. **Not a ticket yet** — this captures intent + facts
so a later grill starts warm. Downstream: the README's multi-agent section is written as current
state + inline `<WIP>` markers that this workstream will fill in.

## Goal

Make the multi-agent swarm runs materially better along three lines:
1. **Message-board adoption** — agents currently under-use the board. Add notifications / prompting
   tweaks so agents actually post findings and read each other.
2. **Agent roles** — some workers have a physical device, some an emulator, some no device at all,
   and some are coordinators. Roles should themselves be **user-creatable** (define new roles).
3. **Viewing** — a better way to watch runs **live** and to **review finished** runs.

## Why

The swarm's value is coordination; if agents ignore the board it degenerates to N independent
single-agent runs. Roles unlock heterogeneous fleets (physical + emulator + coordinator). Better
viewing is needed for both demoing and debugging.

## Facts found (this session)

- Board exists and works: `swarm-eval/src/swarm_eval/messageboard.py` (append-only, one-file-per-
  message, atomic rename) + `board_tools.py` exposed to each bridged agent as MCP `board` tools
  (`post_message`, `list_messages`, `read_message`). `author` is host-stamped from injected
  `AGENT_ID` (unforgeable). Taxonomy: note/finding/success/giveup/done (done = arbiter only).
- Arbiter is a host-side rubric: `conductor.py::evaluate_board` (first credible `success` wins).
- Swarm entrypoint: `swarm.py` -> `conductor.py::Conductor`; per-worker logs are `tail -f`-able;
  `inspect view` webview default port 7575 (`--no-view` to disable).
- ADR 0002 decided: swarm = separate Inspect runs + external board, no central orchestrator
  (the bridge can't attribute concurrent-subagent model calls).

## Downstream effect on docs

README multi-agent section + `swarm-eval/README.md` describe the board/arbiter as they are today;
roles, notifications, and improved viewing go in as inline `<WIP>` to be extended here.
