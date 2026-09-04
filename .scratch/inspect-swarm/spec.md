# inspect-swarm — the Inspect side of the house

The **swarm** (orchestrator + N bridged Claude Code workers) run as an Inspect eval on top of
the completed device layer (pool + broker). This is the feature CONTEXT.md calls the
**Inspect layer**. The harness stays Inspect-free; this code is where Inspect lives.

Built in **three thin slices**, each independently green:

1. **Smoke slice** (tickets 01–02) — prove the plumbing: one bridged Claude Code agent, toy
   prompt, APK staged but unused, **no orchestrator, no emulator**. Inspect task →
   `sandbox_agent_bridge()` → CC runs → completion → scorer → transcript logged.
2. **Orchestrator slice** (ticket 03, stub) — add the N-parametric orchestrator→worker
   fan-out at **N=1**, still no device. The infra must make **N=2 a prompt change**, not new
   plumbing.
3. **Dynamic-agent slice** (ticket 04, stub) — a worker acquires a device from the broker,
   drives it over adb/frida, runs a real loop on **RootBeer**.

Slices 2–3 are **stubs on purpose** (per the grilling): slice 1 will change our priors about
solver/sandbox/fan-out shape, so their design decisions are captured as open questions to
**resume grilling** once the smoke slice is real — not locked in now.

---

## Settled decisions (from grilling, 2026-09-03/04)

- **Eval unit.** `Sample = one target APK`. `input` = the mission; `files` = the APK staged
  into the sandbox; `metadata`/`target` = the oracle's success signal for that app. `Dataset`
  = the **target ladder** (RootBeer → RASP → real). **N (swarm size) is a solver/task
  parameter**, not a sample field and not the dataset. So: different rung = different sample;
  N=1 vs N=2 = same task, different arg; model sweep = same everything, different served model.
- **Slice-1 dataset** = a **single RootBeer sample**. APK always delivered via the Sample's
  `files` (staged into the sandbox), never a host path.
- **Bridge (M1) = stand on `inspect_swe.claude_code()`.** The CC-in-sandbox bridge plumbing
  is delegated to `inspect_swe`; we hand-roll the Inspect **task / dataset / scorer** now and
  the **orchestrator / fan-out** in slice 2. `inspect_swe` docs:
  https://meridianlabs-ai.github.io/inspect_swe/claude_code.html . Bridge reference:
  https://inspect.aisi.org.uk/agent-bridge.html .
- **Smoke scorer (S1)** exercises **both** completion paths: a `submit`-style **tool call**
  and a **final-message match**. Green when the agent produces the expected token either way.
- **Keyless sandbox (S2).** The bridge serves the model: sandboxed CC runs keyless against
  `ANTHROPIC_BASE_URL=http://localhost:13131` with `model="inspect"`; the **host-side**
  `inspect eval --model anthropic/claude-…` provider does the real call. This is exactly what
  makes the later **model sweep a one-flag change**. No Anthropic key baked into the image.
- **Completion is passive.** The agent just runs to completion; the solver returns
  `bridge.state`; Inspect logs the transcript passively (no explicit "done" event; a bridged
  agent's *subagent* model calls also route through the one bridge and are captured).
- **Oracle.** MVP = agent **self-report** + manual verification. Real oracle (later) = a
  per-app **manifest** declaring a machine-checkable success signal (logcat/state observed
  independently). Slice 1's scorer is a trivial token match, not the real oracle.
- **Orchestrator role (Q3).** Thin **scheduler/budget-owner** now (option b), phased toward a
  planner/coordinator later (option c). No domain planning at N=1. Hard constraint: the
  fan-out infra must be **N-parametric so N=2 is only a prompt change to the orchestrator**.
- **Separation.** The harness (`bin/`, `devices/`) stays **Inspect-free** (asserted by its
  suite). The Inspect-side code is a **separate Python project** that imports Inspect and
  reaches the broker as an **external host process** (never imports harness internals).

## Structure (confirmed in ticket 01)

- Inspect-side Python project lives in top-level **`swarm-eval/`**, importable package
  **`swarm_eval`** (uv project). Chosen over `swarm/` and `inspect-evals/`: `inspect*` would
  collide with AISI's published `inspect_evals` suite / shadow stdlib `inspect`; `swarm_eval`
  keeps the "eval" signal with no clash.
- Deps pinned in the project's own **`pyproject.toml` + `uv.lock`** (not the harness
  `versions.txt`, which stays Inspect-free). `inspect-ai` pinned as a floor; the lockfile holds
  the exact version. `inspect_swe` to be added in ticket 02.

## Device layer it sits on (done)

- **Broker** — standing host process, file-backed request/response **queue** under
  `BROKER_DIR/queue/` (no socket). Client verbs: `acquire`/`release`/`status`/`list`/`ping`/
  `shutdown`. Grant response = connection contract **plus** launch profile:
  `serial=… console_port=… adb_port=… profile=frida-only`. CLI: `bin/broker`. Serial by
  design (one boot at a time), cap default **3**. `host.docker.internal` reachability from a
  sandbox is explicitly **out of scope** in the harness — the queue dir is the seam a socket
  shim would wrap. See `.scratch/emulator-harness/issues/06-broker-service.md`.

---

## Deferred decisions — resume grilling here

### Slice 2 (orchestrator / fan-out)
- **Fan-out mechanism.** Where does "spawn N workers" live?
  (i) `inspect_swe` **native subagents** (configured, e.g. `subagent_model`), (ii) an
  **orchestrator prompt** that tells the CC agent to spawn worker subagents via its own Task
  tool, (iii) **Inspect-Python** fan-out (solver spawns N bridged agents). Constraint from
  Q3: **N=2 must be a prompt change.** (i)/(ii) satisfy that most directly; (iii) is a
  config/Python change. Fact-find confirmed subagent calls route through the one bridge and
  are logged, and `inspect_swe` exposes `subagent_model`.
- **Worker isolation.** Subagents share the orchestrator's **one sandbox/filesystem**, or a
  **sandbox per worker**? Interacts with device-per-worker (slice 3): N workers each holding a
  distinct broker device.
- **Aggregation.** How the orchestrator collects worker findings into the single result the
  scorer reads (`bridge.state`).

### Slice 3 (dynamic agent / device)
- **Broker reach from the sandbox.** `inspect_swe` **`bridged_tools`** (host-side Inspect
  tools exposed to the sandboxed agent over a generated stdio MCP server) — strong candidate:
  wrap `bin/broker acquire/release` as bridged tools — **vs** `host.docker.internal` + adb
  port-forwarding into the container (the deferred networking). Which one, and who calls
  `acquire`/`release` (solver setup/teardown vs the agent via a bridged tool)?
- **Cap vs N vs epochs.** Broker cap (3) vs swarm N vs Inspect's own sample concurrency /
  epochs — how they coordinate so the cap is never oversubscribed.
- **Oracle evolution.** Move from self-report to the per-app manifest (machine-checkable
  signal from logcat/state) for RootBeer.
- **Provider-side tools.** Sandbox bridge withholds `web_search`/`code_execution`/
  `client_mcp_servers` by default — decide per-eval whether the offensive loop needs any.
