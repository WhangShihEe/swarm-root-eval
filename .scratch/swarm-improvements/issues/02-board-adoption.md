# 02: Board adoption — push unread index + mission nudge

**What to build:** Make agents actually use the board instead of degenerating into N independent runs.
On each turn, inject an **unread board-index summary** (subjects only — bodies stay pull-on-demand to keep
context clean) reusing the turn-injection plumbing from the forum ticket, and add a **mission nudge**
instructing agents to post findings/successes and to read before duplicating work. High-signal message
types (`success`, `finding`) are escalated more prominently than `note`. No hard gate — agents are pushed
and nudged, never forced to post (which would spam the channel).

**Blocked by:** 01.

**Status:** implemented (hermetic; 230 tests pass) — live multi-worker smoke pending (last box).

- [x] Each agent turn carries a summary of board messages posted since that agent last looked (subject index only, not full bodies). — `model_filters._board_index_injection` + `make_swarm_turn_filter` now push the board index (`forum.board.list(since=cursor)`, subjects only via the `index_entry` view) below the DM section, with its own deliver-once cursor; the agent's own posts are skipped but still advance the cursor. `test_model_filters.py` (7 new tests).
- [x] The mission text instructs agents to post findings/successes and to consult the board before duplicating work. — `dynamic_agent.swarm_prompt` protocol gains a board-index nudge (the index is auto-pushed each turn; `read_message` relevant posts BEFORE starting work to avoid duplication). `test_swarm_worker.py::test_swarm_prompt_nudges_post_and_read_before_duplicating`.
- [x] `success`/`finding` are surfaced more prominently than `note` in the injected summary. — `_board_index_injection` splits the index into a high-signal block (`success`/`finding`, `_HIGH_SIGNAL`) rendered above the routine `note`/`giveup` block. `test_success_and_finding_are_surfaced_above_notes`.
- [x] There is no hard requirement to post before acting. — push + nudge only; no gate. The board injection is advisory text appended to the turn, never a tool-call precondition.
- [ ] A multi-worker run shows agents reading and reacting to each other's board posts more than the pre-change baseline. — LIVE verification pending (needs broker + emulator + budget); the two integration smokes are the DoD gate for this.
