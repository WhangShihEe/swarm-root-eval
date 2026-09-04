# 01: Inspect scaffold + smoke task with a mock solver (no model, no bridge)

**What to build:** the Inspect-side Python project and the smoke **task / dataset / scorer**,
driven by a **mock solver** that deterministically produces the expected output — **no model
call, no bridge, no emulator**. This isolates "did I wire Inspect correctly" (task shape,
Sample `files` staging, scorer, logging) from "did the bridge work" (ticket 02).

**Blocked by:** none (device layer already done).

**Status:** done

- [x] A new Inspect-side Python project in its own top-level dir (**proposed `swarm/`** — not
      `inspect/`, which shadows stdlib `inspect`/`inspect_ai`). `inspect-ai` pinned; recorded
      in `versions.txt` style. The harness (`bin/`, `devices/`) stays Inspect-free.
- [x] A `@task` returns `Task(dataset, solver, scorer)`. Dataset = **one Sample**:
      `input` = the toy prompt ("if you see this, submit `yes` / call the submit tool"),
      `files` = the **RootBeer APK** (`apks/rootbeer/rootbeer.apk`) staged into the sandbox,
      `metadata`/`target` = the expected token (`yes`).
- [x] Scorer greens on the expected result via **both** paths (S1): a `submit`-style tool
      call carrying the token, **and** a final-message match. Deterministic, no model.
- [x] A **mock solver** (no model, no bridge) returns the expected output; `inspect eval`
      yields 1 sample, score = correct, and a transcript that opens in `inspect view`.
- [x] The staged APK is confirmed **present inside the sandbox** at run time (the Sample
      `files` path resolves), proving the APK-in delivery mechanism independent of the agent.
- [x] No Anthropic key required (no model call in this ticket).

## Notes
- Purpose is plumbing confidence, not capability. Keep the task deliberately trivial.
- Confirm the project dir name here (updates `spec.md` "Proposed structure").
- Sandbox choice: a bare Inspect sandbox is fine for the mock solver; ticket 02 introduces the
  CC sandbox via `inspect_swe`.
