# Triage labels: the `Status:` role strings

Every issue file under `.scratch/<feature-slug>/issues/` records its triage state as a
`**Status:** <label>` line near the top (see `issue-tracker.md`). The label is free text with a
short conventional vocabulary — the strings below are the ones in use across the tracker. Keep to
them so a scan (`grep -r '^\*\*Status:' .scratch/*/issues`) reads consistently; add a parenthetical
qualifier after the label when a ticket needs nuance (e.g. `built (awaits live smoke)`).

## Lifecycle labels

| Label | Meaning |
|-------|---------|
| `ready-for-agent` | Scoped and unblocked; ready for an implementing agent to pick up. |
| `in progress` | Being worked now (code may be partially landed). |
| `built` / `done` | Implemented. `built` often carries a qualifier for what remains — typically `built (hermetic; awaits the live hand-run smoke)` when unit/hermetic tests pass but a real-device run hasn't been done yet. `done` = fully complete. |
| `superseded` | Replaced by other tickets; kept for history. Name them: `superseded (see tickets 04 & 05)`. |
| `stub` | A placeholder for future work, not yet scoped — usually `stub (future — grill before building)`. |
| `ready (human-in-the-loop iteration)` | A living brief a human iterates on, not a hand-off to an autonomous agent. |

## Wayfinding labels

`/wayfinder` maps (`.scratch/<effort>/map.md` + child tickets) use a narrower pair for the
claim/resolve loop (see the "Wayfinding operations" section of `issue-tracker.md`):

| Label | Meaning |
|-------|---------|
| `claimed` | An agent has taken the ticket and set this before doing any work. |
| `resolved` | The ticket's question is answered (the answer is appended under an `## Answer` heading). |

A wayfinding ticket also carries a `Type:` line (`research` / `prototype` / `grilling` / `task`)
and an optional `Blocked by: NN, NN` line; it is unblocked when every file it lists is `resolved`.
