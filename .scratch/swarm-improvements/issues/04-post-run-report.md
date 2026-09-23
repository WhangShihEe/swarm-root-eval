# 04: Post-run report (`report.py`)

**What to build:** A separate, re-runnable command that turns a finished swarm run into a human-readable
report. `report.py <log-dir>` collates the run's inputs — the forum (board timeline + DMs), each worker's
verdict and transcript, and the arbiter verdict — and makes a **direct host-side LLM call** (not a bridged
agent, no device/tools) to synthesize insights, writing `logs/<swarm-id>/report.md`. Inference goes
through the `safetytooling` submodule (already added at `third_party/safety-tooling`); this ticket
includes wiring it as a path/editable dependency of the swarm-eval Python project so `report.py` can
import it. The report uses a configurable model (the user's choice), independent of the swept model so
report quality doesn't vary with what's being evaluated.

**Factor input-collation into a shared `run_reader` (decided in the 05 design pass, 2026-09-24).** The
"collate the run's inputs" step is not private to `report.py` — ticket 05's UI reads the exact same
inputs. Factor it into a reusable `run_reader` module in `swarm-eval/src/swarm_eval/` that turns a run's
forum (board + DMs + statuses) + each worker's `.eval` stats + arbiter verdict into **one typed run
object**, joined by `worker-<i>` (which is 1:1 across log dir, forum author, and DM inbox). Keep
`run_reader` a **pure parser**: it reads artifacts via Inspect's own `inspect_ai.log` reader, calls **no
model**, and does **not** import `safetytooling` — the `safetytooling` LLM call stays in `report.py`'s
synthesis step, layered on top of the reader. 05 consumes `run_reader` unchanged.

**Blocked by:** 01 (the report reads the forum layout).

**Status:** ready-for-agent

- [ ] Input-collation is a reusable, dependency-free `run_reader` module (no `safetytooling`, no model call) producing one typed run object; `report.py` layers synthesis on top of it, and ticket 05 consumes it unchanged.
- [ ] `report.py <log-dir>` reads a finished run's forum, per-worker verdicts/transcripts, and arbiter verdict, and writes `logs/<swarm-id>/report.md`.
- [ ] Inference runs via the `safetytooling` submodule; the submodule is wired as a dependency of the swarm-eval project and imports cleanly.
- [ ] The report model is user-configurable and defaults independently of the eval's `--model`.
- [ ] The command is re-runnable against an existing log dir without re-running the swarm and without touching the run's budget/verdict.
