# 05a: Messageboard — host-side shared board + bridged_tools (the swarm comms substrate)

**What to build:** the swarm's shared state — a **host-side, append-only, one-file-per-message
directory** — plus the `inspect_swe` **`bridged_tools`** each agent-run uses to post and read.
Standalone building block (like the broker on the device side): provable with two hand-started
bridged runs before any launcher/arbiter exists.

**Blocked by:** 02 (done). Independent of 04 — can be built in parallel.

**Status:** done

## Acceptance
- [x] **Board layout:** a host dir `BOARD_DIR/<swarm-id>/`; each message is one JSON file named
      `<ts>-<author>-<shortid>.json` = `{ts, author, subject, type, content}`. One-file-per-
      message = the broker's no-append-races idiom. `type` ∈ `note`/`finding`/`success`/
      `giveup`/`done` (`done` reserved for the arbiter, 05b).
- [x] **Tools exposed via `bridged_tools`** (host-side, run in each run's process against the
      shared dir):
  - `post_message(subject, content, type="note")` — **stamps `author` from the run's injected
    `AGENT_ID`**, not from agent input (no spoofing). Writes one file.
  - `list_messages(since=None)` — returns the **index only**: per message `{id, subject, author,
    ts, type}`, sorted. Small — keeps agent context clean. Optional `since` cursor for deltas.
  - `read_message(ids)` — returns the **full body** of one or more named messages.
- [x] **Two-tier read proven:** an agent sees all subjects via `list_messages`, then pulls only
      the bodies it wants via `read_message` — the whole board is never force-fed into context.
- [x] **Author integrity:** a run posting cannot forge another run's `author` (stamped host-side
      from `AGENT_ID`).
- [x] **Standalone demo:** two hand-started bridged runs with distinct `AGENT_ID`s post and read
      each other's messages; the board dir shows the files; `list` shows subjects; `read` returns
      bodies. No launcher, no arbiter, no device.

## Notes
- The board doubles as the swarm's **shared memory**; the subject-line index is what keeps a
  long board from blowing up each agent's context.
- Reached host-side, so worker sandboxes need **no network** for the board (adb still does — 04).
- Not Inspect's `store` (per-sample-isolated) and not `host.docker.internal` (raw, bypasses
  Inspect). See ADR-0002.

## Comments

**Done (2026-09-17), commit `86096a0`.** Implemented on a worktree, reviewed (two-axis
Standards+Spec), and integrated onto `main`.

- `swarm-eval/src/swarm_eval/messageboard.py` — pure `Board` substrate over
  `BOARD_DIR/<swarm-id>/`: one JSON file per message named `<ts>-<author>-<shortid>.json`
  (`<ts>` = a compact, sortable, colon-free UTC stamp so ids sort chronologically and `ls`
  stays legible), atomic-rename write (no append races / no partial reads), `since` id-cursor
  for deltas. No Inspect dependency — provable in isolation like `broker_client`.
- `swarm-eval/src/swarm_eval/board_tools.py` — the three `bridged_tools`
  (`post_message`/`list_messages`/`read_message`); two-tier read; `author` stamped host-side
  from `AGENT_ID` (no forge); `done` forbidden to workers via an `allow_done` seam for 05b.
- `swarm-eval/board_agent.py` — the standalone two-run demo entrypoint + a host-side
  `posted_to_board` scorer.

**Verification:** 38 new hermetic tests (59 total in the suite) pass. The live two-run proof
was run by hand — two `inspect eval board_agent.py` runs with distinct `AGENT_ID`s sharing one
board post and read each other's messages (confirmed working on a cross-vendor served model).
