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

## Intent captured (2026-09-23, from the yaml-config-extension grill)

The `yaml-config-extension` workstream splits config into **device file** (provisioning: system
image, `provision`/`frida`/`normalize_settings`/`headless`, …), an **eval config** (the
user-owned "what app + how many/what agents + what devices + budgets/model" file), and an
**app** definition (apk + mission slots). That split is the substrate this workstream builds on.
This section records the richer-worker intent surfaced during that grill, to be designed HERE:

- **Worker becomes a richer, user-authored config (its own yaml).** A worker may:
  - have an **emulator** device, a **physical** device, or **no device** at all;
  - be a **coordinator** (role), not just an attacker;
  - carry a **user-defined prompt**.
- **Device binding is per-worker.** A worker's device (physical or emulator) is defined by a
  **separate device yaml** that the worker **references**, or `None` when the worker uses no
  device. (The yaml-config split builds the eval-level, one-device-config-per-run form — N
  workers × 1 device each, same config; the *heterogeneous* per-worker binding — different
  device or none per worker — is the change to design here.)
- Roles should be **user-creatable** (define a new role), consistent with goal #2 above.

### Roles (decided this grill)

Three roles now (a role ≡ a worker-type yaml; `kind` field):
- **coordinator** — no device. Reads the board, spots which workstreams look promising, and
  **directs the other workers** (via the board, and later via direct messages — see below). A
  "middle manager" that knows what each worker is doing. It does NOT own the verdict — the
  host-side arbiter (`evaluate_board`) keeps that (ADR-0002), and the coordinator is still denied
  `done`. Future coordinator powers: ping agents that have gone quiet; **filter/route** board
  findings to only the agents who need them, so pulling the board doesn't pollute an agent's
  context with irrelevant messages.
- **dynamic** — given a device (emulator or physical). Attacks the live app (today's behavior).
- **static** — NO device; given only the sandbox with the APK staged. Deep static analysis +
  tests; shares findings on the board. (Consequence: `device: none` roles — static & coordinator
  — skip broker device leasing; only `dynamic` workers lease a device.)

### Direct messaging / inbox (intent from this grill)

Alongside the broadcast board, add a per-agent **inbox**: each agent has a small mailbox stating
**what it is currently working on** (a status), and another agent or the coordinator can **write
to that inbox to DM it directly**. Coordinators use DMs to nudge an individual agent's direction
without broadcasting to everyone. (Design detail being grilled now.)

### Viewing — bespoke UI (stretch, one of the FINAL parts)

Leaner cut first (goal #3 = `a`): run the swarm, then run a **post-run insights agent** that
reads the finished run (board + transcripts + verdict) and writes a **report**; the user reads
raw `inspect view` logs directly if they need more. STRETCH (deliberately last, "heavy and
flashy but fun"): a **bespoke live + review UI** to explore the messageboard human-friendly and
watch it update live. Large scope — sequenced after everything else.
