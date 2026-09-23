# 02: Board adoption — push unread index + mission nudge

**What to build:** Make agents actually use the board instead of degenerating into N independent runs.
On each turn, inject an **unread board-index summary** (subjects only — bodies stay pull-on-demand to keep
context clean) reusing the turn-injection plumbing from the forum ticket, and add a **mission nudge**
instructing agents to post findings/successes and to read before duplicating work. High-signal message
types (`success`, `finding`) are escalated more prominently than `note`. No hard gate — agents are pushed
and nudged, never forced to post (which would spam the channel).

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Each agent turn carries a summary of board messages posted since that agent last looked (subject index only, not full bodies).
- [ ] The mission text instructs agents to post findings/successes and to consult the board before duplicating work.
- [ ] `success`/`finding` are surfaced more prominently than `note` in the injected summary.
- [ ] There is no hard requirement to post before acting.
- [ ] A multi-worker run shows agents reading and reacting to each other's board posts more than the pre-change baseline.
