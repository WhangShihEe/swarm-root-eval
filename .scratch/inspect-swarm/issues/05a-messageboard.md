# 05a: Messageboard — host-side shared board + bridged_tools (the swarm comms substrate)

**What to build:** the swarm's shared state — a **host-side, append-only, one-file-per-message
directory** — plus the `inspect_swe` **`bridged_tools`** each agent-run uses to post and read.
Standalone building block (like the broker on the device side): provable with two hand-started
bridged runs before any launcher/arbiter exists.

**Blocked by:** 02 (done). Independent of 04 — can be built in parallel.

**Status:** ready

## Acceptance
- [ ] **Board layout:** a host dir `BOARD_DIR/<swarm-id>/`; each message is one JSON file named
      `<ts>-<author>-<shortid>.json` = `{ts, author, subject, type, content}`. One-file-per-
      message = the broker's no-append-races idiom. `type` ∈ `note`/`finding`/`success`/
      `giveup`/`done` (`done` reserved for the arbiter, 05b).
- [ ] **Tools exposed via `bridged_tools`** (host-side, run in each run's process against the
      shared dir):
  - `post_message(subject, content, type="note")` — **stamps `author` from the run's injected
    `AGENT_ID`**, not from agent input (no spoofing). Writes one file.
  - `list_messages(since=None)` — returns the **index only**: per message `{id, subject, author,
    ts, type}`, sorted. Small — keeps agent context clean. Optional `since` cursor for deltas.
  - `read_message(ids)` — returns the **full body** of one or more named messages.
- [ ] **Two-tier read proven:** an agent sees all subjects via `list_messages`, then pulls only
      the bodies it wants via `read_message` — the whole board is never force-fed into context.
- [ ] **Author integrity:** a run posting cannot forge another run's `author` (stamped host-side
      from `AGENT_ID`).
- [ ] **Standalone demo:** two hand-started bridged runs with distinct `AGENT_ID`s post and read
      each other's messages; the board dir shows the files; `list` shows subjects; `read` returns
      bodies. No launcher, no arbiter, no device.

## Notes
- The board doubles as the swarm's **shared memory**; the subject-line index is what keeps a
  long board from blowing up each agent's context.
- Reached host-side, so worker sandboxes need **no network** for the board (adb still does — 04).
- Not Inspect's `store` (per-sample-isolated) and not `host.docker.internal` (raw, bypasses
  Inspect). See ADR-0002.
