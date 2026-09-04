# 03: Orchestrator slice — N-parametric fan-out at N=1  [STUB — grill before building]

**Status:** stub (do not build — resume grilling first)

**Blocked by:** 02.

**Goal (settled):** introduce the **orchestrator → worker** fan-out, running at **N=1**, still
**no device**. The orchestrator is a thin **scheduler/budget-owner** (Q3 = b now, → c later),
no domain planning. The hard constraint: the infra must be **N-parametric so going to N=2 is
only a prompt change to the orchestrator**, not new plumbing. `N=1` is not special-cased.

**Why a stub:** the fan-out mechanism should be chosen *after* the smoke slice teaches us the
real shape of the bridged solver and how `inspect_swe` handles subagents. Locking it now bakes
in guesses.

## Open questions to grill (resume here)
1. **Fan-out mechanism** — pick one:
   - (i) `inspect_swe` **native subagents** (configured; `subagent_model` can even route roles
     to different served models).
   - (ii) an **orchestrator prompt** that instructs the CC agent to spawn worker subagents via
     its own Task tool.
   - (iii) **Inspect-Python** fan-out: the solver spawns N bridged agents and aggregates.
   Constraint: **N=2 = prompt change** — favors (i)/(ii). Fact-find confirmed subagent model
   calls route through the one bridge and are logged passively.
2. **Worker isolation** — subagents share the orchestrator's **one sandbox**, or a **sandbox
   per worker**? (Interacts with device-per-worker in ticket 04.)
3. **Aggregation** — how the orchestrator folds worker outputs into the single result the
   scorer reads via `bridge.state`.
4. **What N=1 looks like** — confirm it is genuinely "orchestrator + one worker, no cleverness"
   and shares the exact code path as N>1.

## Established context (so grilling can resume cold)
- Standing on `inspect_swe.claude_code()` (M1); task/dataset/scorer are hand-rolled and proven
  in tickets 01–02. Sample = APK; N = solver param. Keyless sandbox; host `--model` serves.
- See `spec.md` "Deferred decisions → Slice 2" for the same list in context.
