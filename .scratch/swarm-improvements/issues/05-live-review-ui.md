# 05: Bespoke live + review messageboard UI (stretch)

**What to build:** A bespoke, human-friendly UI to explore a swarm run's **forum** — the coordination
story (board + DMs + per-worker statuses) — joined with per-agent stats and a link out to Inspect's
transcript viewer. Debugging-first, polished enough to double as a demo. Deliberately the final piece:
large scope, high polish, sequenced last. The leaner interim (04's `report.py`, plus raw `inspect view`
logs) covers day-to-day needs; this ticket is the flashy upgrade.

**Blocked by:** 01 (forum layout), 04 (owns the shared `run_reader` this UI consumes — see below).

**Status:** backlog (design decided; not on the critical path — sequenced last)

---

## Design pass (decided 2026-09-24, grilling session)

The dedicated design pass ticket 05 asked for. Every decision below was grilled to a shared
understanding; downstream build agents follow it rather than re-deciding.

### Audience & posture

Debugging-first — the daily user is Shih Ee, understanding why a run coordinated well or badly.
Clean enough that the same view doubles as an occasional demo. Design for the debugger; a legible
debug view is already demo-able.

### Cut 1 is a static review artifact; live is a later phase

- **Cut 1 = review of a *finished* run.** No server: a Python builder reads the run off disk once
  and emits a self-contained HTML file. The dashboard shows each agent's **final snapshot**.
- **Live is a deliberate later add-on, not a rewrite.** The data layer is built so the same
  frontend can later be fed by a server (FastAPI + SSE; uvicorn is already in the venv) instead of
  inlined data. "Live" becomes a data-source swap, not new UI.

### Scope — three surfaces

1. **Forum view (the core).** Per-agent **swimlanes** on a shared **wall-clock** time axis. One lane
   per worker + a dedicated **board lane**. A DM renders as a marker in the *recipient's* lane with a
   thin connector back to the sender's lane. A worker's `status.txt` is its lane label, with a marker
   each time it changes. Message `type` (note/finding/success/giveup/done) is color/icon-coded.
   Wall-clock (not event-ordinal) is deliberate: silence shows up as a literal gap, which is the
   "who went quiet, when" signal. Add adaptive compression only if real runs have dead stretches that
   waste the viewport.
2. **Dashboard (per-agent, final snapshot).** Lean by default, details on expand. Default columns:
   **role** (coordinator/dynamic/static), **device** (emulator/physical/none), **final status line**,
   **last-activity time** (drives a "went quiet" flag), **messages posted** (findings/notes split),
   **DMs sent/received**, **outcome** (posted success / giveup / errored / hit a limit). Behind an
   expand: **turns**, **token usage**, **wall-clock / working time**. Run header: arbiter verdict +
   winner, agent count, totals.
3. **Inspect transcripts — link out, not embed.** `inspect view` **cannot be iframed**: it hard-codes
   `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` on every response,
   no flag to disable (`inspect_ai/_view/network.py:235-236`, applied unconditionally at
   `fastapi_server.py:748`). Cut 1: a tab/button **opens the running `inspect view`** (port 7575,
   already `--recursive` over the swarm log root) in its own window, plus deep-links to each worker's
   `.eval`. The live phase (which runs a server anyway) may **reverse-proxy** `inspect view` and strip
   those two headers for a true in-tab embed — cheap then, a hack now.

### Stack & layout

- **Single self-contained HTML, vanilla JS, Python builder.** No npm, no bundler, no framework. Run
  data embedded as inline JSON; frontend in vanilla JS (a small CDN lib only if a layout genuinely
  needs it). One file you can open directly or send to someone. Live phase: same JS, server serves the
  JSON as an endpoint + SSE.
- **Code location.** `run_reader.py` and `viewer.py` live in `swarm-eval/src/swarm_eval/` next to
  `conductor`/`forum`/`messageboard`. Entry point `swarm-view <run-path>` (or lists `logs/` when given
  none — see run selection). `viewer.py` is a thin builder over `run_reader` + one HTML template asset.

### Run selection

Auto-scan `logs/` for swarm runs and offer a picker, defaulting to the most recent; also accept an
explicit run path so scripts / 04 can deep-link a specific run.

### Shared `run_reader` (the key structural decision)

04 and 05 read the *same* inputs (forum tree + each worker's `.eval` + `console.out`, joined by
`worker-<i>`). **04 factors input-collation into a reusable, dependency-free `run_reader`** — forum
messages + DMs + statuses + per-worker eval stats + arbiter verdict → one typed run object. 05's
viewer and 04's report both render from it, so the two never drift, and the live server later feeds the
same model. `run_reader` is a **pure parser**: it reads artifacts via Inspect's own `inspect_ai.log`
reader and calls **no model** — it does **not** depend on `safetytooling` (that dependency belongs only
to 04's synthesis step, not to the reader).

### Data facts the reader relies on (found this session)

- Per-worker logs: `logs/<swarm-id>/worker-<i>/*.eval` + live `console.out` + `<agent-id>.device`.
  `worker-<i>` maps 1:1 to its log dir, its forum `author`, and its DM inbox dir.
- Forum message JSON: `{id, ts, author, subject, type, content}` (`id` is the filename stem);
  `type` in note/finding/success/giveup/done (`done` is arbiter-only). Status is a plain-text
  `status.txt` per worker.
- Per-agent `.eval` sample stats: token usage (`model_usage`/`ModelUsage`), message/turn count
  (`messages`), `total_time`/`working_time`, `started_at`/`completed_at`, error/limit status.

### Explicitly out of cut 1 (named follow-ups)

- **Live auto-updating** (board/dashboard refresh as a run progresses) — the live phase.
- **Reverse-proxied in-tab `inspect view`** — the live phase.
- **Read-tracking** ("did agent X actually read message Y"). Reads are **not persisted to disk**; the
  forum records posts and DM *delivery*, not reads. Cut 1 renders delivery only. Inferring reads would
  require parsing each worker's transcript (what the bridge injected per turn) — a bigger parse,
  deferred.
- **Adaptive/compressed time axis** — added only if linear wall-clock wastes the viewport on real runs.

---

## Acceptance (cut 1)

- [ ] A `swarm-view` command builds a **self-contained HTML** review of a finished run: forum swimlanes
      (board lane + per-worker lanes, wall-clock axis, DMs as cross-lane connectors, statuses as lane
      labels, type color-coding) + the per-agent snapshot dashboard + run header (verdict/winner).
- [ ] The viewer consumes the shared `run_reader` (from 04); it adds no model dependency and does not
      import `safetytooling`.
- [ ] Run selection: auto-lists `logs/` with most-recent default, and accepts an explicit run path.
- [ ] An Inspect tab/button **opens** the running `inspect view` and deep-links each worker's `.eval`
      (link-out, not iframe).
- [ ] The data layer is structured so a later live phase feeds the same frontend from a server endpoint
      without reworking the UI.
