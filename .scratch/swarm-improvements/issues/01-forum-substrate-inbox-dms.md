# 01: Forum substrate — relocate board + per-agent inbox/DMs/status

**What to build:** Give the swarm a coordination "forum". Relocate the existing messageboard under
`logs/<swarm-id>/forum/messageboard/` and add a per-agent direct-messaging layer at
`logs/<swarm-id>/forum/dms/<worker-id>/`. Each agent can set a short "currently working on" **status**,
**read its inbox** (its DMs since last read + its own status), and **send a DM** to another agent —
reusing the messageboard's file-per-message + atomic-rename mechanics, with author host-stamped from the
injected `AGENT_ID` (unforgeable, same as the board). Unread DMs are **pushed into an agent's turn**,
ranked above board notes, so a targeted message reaches the recipient without it having to poll. Any
agent can DM any other (peer coordination); the coordinator role will be the heaviest user later.

**Blocked by:** yaml-config-extension #04 (sequencing: phase 2 lands after the config refactor; this
ticket itself only touches board/agent-tool plumbing).

**Status:** ready-for-agent

- [ ] Swarm coordination artifacts live under `logs/<swarm-id>/forum/`, with `messageboard/` and `dms/<worker-id>/` subfolders; the board relocation does not break the arbiter or existing board tools.
- [ ] Agents have `set_status`, `read_inbox`, and `send_dm` tools; author is host-stamped, not caller-supplied.
- [ ] A DM written to a worker's inbox is delivered into that worker's next turn, ranked above board notes.
- [ ] A two-worker run demonstrates: worker A sets a status and DMs worker B; worker B reads the DM in-turn.
- [ ] Both integration commands still pass (verified in the `.eval`), including the single-agent (no-board) path.
