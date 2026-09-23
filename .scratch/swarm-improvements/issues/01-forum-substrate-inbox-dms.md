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

**Status:** done (implemented; 222 hermetic tests pass; both integration smokes pass; code-reviewed)

- [x] Swarm coordination artifacts live under `logs/<swarm-id>/forum/`, with `messageboard/` and `dms/<worker-id>/` subfolders; the board relocation does not break the arbiter or existing board tools. — `forum.py` (`Forum`: `messageboard/` board + `dms/<worker-id>/` inboxes + `status.txt`), conductor writes it live under the log dir (no post-run copy); board tools resolve the forum's board (legacy `board_agent` still works). `test_forum.py`, `test_conductor.py`.
- [x] Agents have `set_status`, `read_inbox`, and `send_dm` tools; author is host-stamped, not caller-supplied. — `board_tools.py` (`send_dm`/`read_inbox`/`set_status`, author from `AGENT_ID`, `done` forbidden); `forum_tools_spec` exposes all 6 under the `board` MCP server. `test_forum_tools.py`.
- [x] A DM written to a worker's inbox is delivered into that worker's next turn, ranked above board notes. — `model_filters.make_swarm_turn_filter` pushes unread DMs (top-priority section) into each turn with a deliver-once cursor; the board-index injection (below DMs) is ticket 02. `test_model_filters.py`.
- [x] A two-worker run demonstrates: worker A sets a status and DMs worker B; worker B reads the DM in-turn. — verified LIVE in the N=3 swarm smoke: all 3 workers set statuses (`set_status`, on disk) and post board findings; a host-injected DM to worker-3 was pushed into its next turn ("The DM confirms the Detector.run approach…") AND read via `read_inbox` ("That's a coordinator probe"). Also proven hermetically (`test_model_filters`, `test_forum_tools`).
- [x] Both integration commands still pass (verified in the `.eval`), including the single-agent (no-board) path. — single_agent: PASS (`.eval` status success, self_report=1.0, no errors). swarm N=3: PASS (verdict SUCCESS — worker-2 `self_report`=1.0; board findings + arbiter `done: SUCCESS` under `forum/messageboard/`; all 3 devices released; no bridge/tool errors in any worker console).
