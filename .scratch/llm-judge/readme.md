# Seed: llm-judge

Context-seed for a future grilling session. **Not a ticket yet — explicitly deferred** (large
scope). Captured so the pickup is warm.

## Goal

A simple **LLM-as-a-judge** oracle for the evaluation, to replace / augment the current
self-report scorer.

## Why

The current scorer is **spoofable** — a self-report oracle reading the agent's final
`RASP_BYPASS: SUCCESS|FAILURE` line — and has already been gamed by a model (Kimi-K3 per project
memory). A judge (or a machine-checkable oracle) would make verdicts trustworthy.

## Facts found (this session)

- MVP scorer: `dynamic_agent.py` scorer `self_report()` (final-line read).
- Swarm verdict rubric: `conductor.py::evaluate_board` (first credible `success` wins;
  all-`giveup`/budget loses) — documented as the **seam** for a future machine-checkable oracle.
- Some targets have ground-truth signals a machine oracle could use directly (e.g. RASP-dummy's
  logcat `RASPTARGET verdict=PASS`), which may be cheaper/harder-to-game than an LLM judge for
  those cases — worth weighing LLM-judge vs machine-oracle vs hybrid in the grill.

## Downstream effect on docs

Not documented as available; the README/`swarm-eval/README.md` may note the scorer is an MVP and
that a judge is planned.
