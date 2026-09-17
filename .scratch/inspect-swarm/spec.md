# inspect-swarm — the Inspect side of the house

The **swarm** runs on top of the completed device layer (pool + broker). This is the feature
CONTEXT.md calls the **Inspect layer**. The harness stays Inspect-free; this code is where
Inspect lives.

## Swarm model (pivoted 2026-09-17)

Each agent is **its own Inspect run** — one bridged Claude Code agent = one bridge = one clean
transcript. The agents **collaborate through an external, host-side messageboard**, and a
separate **arbiter** run decides when the mission is done and issues the verdict. An external
**launcher** starts the N runs, creates the board, links devices from the broker, and
correlates the logs.

**Why not one run with subagents (Fork A, abandoned):** the agent bridge cannot attribute
concurrent-subagent model calls to their own transcript spans — they collapse onto the parent
span, so subagent traces interleave (verified live: 10/11 model events on the orchestrator
span). Separate runs fix this **by construction**.

**Why not Inspect's within-run parallelism:** samples/epochs are for repeating the *same*
problem for consistency, not for distinct collaborating agents. So Inspect is used **per
agent** (consistency + logging + the CC bridge); the swarm layer (launcher, board, arbiter,
cross-run scoring) is **entirely external** to Inspect — Inspect has no cross-run shared state.

## Ticket map

- **01–02 — Smoke slice (done).** One bridged CC agent, toy prompt, APK staged, scorer, log.
  Proves Inspect task → `sandbox_agent_bridge()` (via `inspect_swe.claude_code()`) → CC →
  completion → scorer → transcript.
- **03 — Orchestrator smoke (SUPERSEDED).** Fork A; abandoned over the interleaving above.
- **04 — Dynamic agent, end-to-end (done at infra level, a4d6cfb).** One bridged CC agent in a
  sandbox, handed a **broker-granted device**, reaching it over adb, working the **RootBeer**
  APK. Acquire/inject/connect/adb/frida-handshake all verified live. **The reusable unit ticket
  05 launches N times.**
- **07 — Dynamic-agent offensive-tooling layer (ready, human-in-the-loop).** Makes frida-17
  usable (Java bridge + `frida-compile` + non-interactive runner + objection), folds static
  tools into the image, rewrites the prompt, adds a fail-fast limit — and **iterates to a first
  RootBeer green on Claude**. With 06, unlocks the sweep. (Logically 04.5; the agent-effectiveness
  follow-on.)
- **05a — Messageboard (ready).** Host-side append-only one-file-per-message board +
  `bridged_tools` (`post_message`/`list_messages`/`read_message`). The comms substrate;
  provable with two hand-started runs. Independent of 04.
- **05b — Conductor (stub-ready).** Launcher + arbiter + termination + device-linking + log
  correlation over **N separate runs**. Builds on 04 + 05a.
- **06 — Machine-checkable oracle (future).** Replaces self-report for RootBeer; **gates the
  model sweep**.

---

## Settled decisions

- **One Inspect run = one agent working one mission.** A `Sample` carries the mission (`input`),
  the **APK via the Sample `files`** (staged into the sandbox, never a host path), and
  `metadata`/`target` for the oracle. The **swarm = N such runs over the same mission**,
  coordinated via the board; N = how many runs the **launcher** starts (not a within-run param).
  The **target ladder** (RootBeer → RASP → real) is future missions.
- **Bridge = stand on `inspect_swe.claude_code()`** (M1). CC-in-sandbox bridge plumbing is
  delegated; we hand-roll the Inspect task/dataset/scorer and the external swarm layer.
- **Keyless sandbox (S2).** Sandboxed CC runs keyless against
  `ANTHROPIC_BASE_URL=http://localhost:13131` with `model="inspect"`; the **host-side**
  `inspect eval --model anthropic/claude-…` provider does the real call — so a **model sweep is
  a one-flag change**. No Anthropic key in the image.
- **Completion is passive.** The agent runs to completion; the solver returns `bridge.state`;
  Inspect logs the transcript passively. (Per-agent now, so no subagent-attribution problem.)
- **Oracle = self-report** MVP + manual verification. Machine-checkable oracle (per-app signal
  from logcat/state) deferred — but it **gates the model sweep** (can't sweep on a manual oracle).
- **Messageboard = host-side, append-only, one file per message in a directory** (the broker's
  one-dir-per-request idiom — no append races). Reached from each run via `inspect_swe`
  **`bridged_tools`**, **not** Inspect's `store` (per-sample-isolated), **not**
  `host.docker.internal` (raw). Message = `{ts, author, subject, type, content}`. **Two-tier
  read** keeps agent context clean: `list_messages` returns the **subject index** only,
  `read_message(ids)` pulls full bodies on demand. **`author` is stamped host-side** from the
  run's `AGENT_ID` (no spoofing).
- **Arbiter = its own Inspect run** — a bridged agent that watches the board, applies a thin
  rubric (success on first credible `success` claim; fail on all-`giveup`/timeout), posts a
  reserved `done`+verdict, and is the **swarm oracle** for now.
- **Log correlation.** All worker+arbiter `.eval` logs land in `logs/<swarm-id>/` (via
  `INSPECT_LOG_DIR`) with `swarm-id/agent-id/role` metadata; the launcher also **saves the
  messageboard** into that folder, so a swarm run = transcripts + the conversation, one artifact.
- **Launch profile = `writable-/system`** (current env-up default; Frida-only a per-grant
  fallback).
- **Separation.** The harness (`bin/`, `devices/`) stays **Inspect-free**. The Inspect-side
  code is a separate Python project that reaches the broker as an **external host process**.

## Structure (confirmed in ticket 01)

- Inspect-side Python project in top-level **`swarm-eval/`**, package **`swarm_eval`** (uv
  project). Chosen over `swarm/`/`inspect-evals/` (`inspect*` would collide with AISI's
  `inspect_evals` / shadow stdlib `inspect`).
- Deps pinned in the project's own **`pyproject.toml` + `uv.lock`** (not the harness
  `versions.txt`). `inspect-ai` + `inspect_swe` pinned; lockfile holds exact versions.

## Device layer it sits on (done)

- **Broker** — standing host process, file-backed request/response **queue** under
  `BROKER_DIR/queue/` (no socket). Verbs: `acquire`/`release`/`status`/`list`/`ping`/`shutdown`.
  Grant = connection contract + profile: `serial=… console_port=… adb_port=…
  profile=writable-system` (current default). CLI: `bin/broker`. Serial (one boot at a time),
  cap default **3**. `host.docker.internal` reachability from a sandbox was left out of the
  harness on purpose — the queue dir is the seam. See
  `.scratch/emulator-harness/issues/06-broker-service.md`.

---

## Deferred decisions — resume grilling here

### Ticket 04 (single dynamic agent) — decisions folded into the ticket
- Broker reach: **control** (acquire/release) by the **solver setup/teardown** (guaranteed
  release) via `bin/broker`; **data** (drive the device) via `host.docker.internal:<adb_port>` +
  `adb connect` from inside the sandbox (unavoidable — emulator is on the host).
- Image toolchain: `adb`, `frida`/`frida-tools` pinned to server **17.17.0**, `objection`,
  `python3`; sandbox needs **host network** (not `network_mode: none`) for adb.

### Ticket 05a/05b (swarm framework) — grilled & settled, folded into the tickets
- **05a messageboard**: host-side append-only one-file-per-message dir; `bridged_tools` with
  two-tier read (`list_messages` index → `read_message` bodies); author stamped host-side.
- **05b conductor**: Python launcher in `swarm-eval/` starts N worker + 1 arbiter `inspect eval`
  subprocesses; env-var injection; **launcher pre-acquires** devices per dynamic role (≤ cap,
  fail-fast); arbiter = own run + swarm oracle (self-report rubric); termination = cooperative
  `done`-poll + per-run Inspect limit + launcher-kill; logs + saved board collated under
  `logs/<swarm-id>/`. `N=1-is-single`, uniform path.

### Ticket 07 (dynamic-agent offensive tooling) — grilled & settled, folded into the ticket
- frida-17 usable: `frida-java-bridge` + `frida-compile` (custom scripts) **and** objection
  (works-today fast path) **and** a non-interactive runner; static tools added to the dynamic
  image (jadx/apktool/aapt/…); prompt rewritten; fail-fast `time_limit`. First green on **Claude**,
  human-in-the-loop; empirical acceptance (iteration log + green transcript).

### Ticket 06 (machine-checkable oracle) — future, grill before building
- Replace self-report with an independent RootBeer signal (logcat/state) per a per-app manifest;
  plugs into the arbiter without changing termination wiring. **Gates the model sweep.**

### Model sweep — prerequisites parked
- **Reasoning-model output filter** (strip leaked `<think>…</think>` / `</think>` spam so a
  verdict is emitted) — a bridge filter alongside `swarm_eval/model_filters.py`. Needed for
  cross-vendor reasoning models (Qwen). Sweep also needs a first green (07) + a machine-checkable
  oracle (06). Cross-vendor provider caveat: prefer `cerebras`/`novita` over `deepinfra` for Qwen
  (malformed tool-call streams).
