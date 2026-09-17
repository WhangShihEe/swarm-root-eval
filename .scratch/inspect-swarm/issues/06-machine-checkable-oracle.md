# 06: Machine-checkable oracle — replace self-report for RootBeer  [FUTURE — gates the model sweep]

**Status:** stub (future — grill before building)

**Blocked by:** 04 (dynamic agent), 05b (the arbiter is where it plugs in).

**Goal:** replace the **self-report** oracle with a **machine-checkable** success signal for
RootBeer — an independent observation that the anti-root check was actually defeated (per
CONTEXT's real-oracle definition: a per-app manifest declaring a concrete signal, e.g. the app
reaches its post-root-check state, observed from logcat / UI state, not the agent's word).

**Why it matters:** the **model sweep is gated on a first green *and* cannot run on a manual /
self-report oracle** — you can't hand-verify every swept run. So an automated oracle must land
before the sweep begins.

## Open questions to grill (resume here)
1. **The RootBeer signal.** What concrete, observable state means "bypassed"? (logcat line, an
   app state/activity reached, a check-result surfaced to the UI/log.) Needs to be observable
   **independently of the agent**.
2. **Where the check runs.** The arbiter (05b) reads device state via adb/logcat and decides,
   vs a dedicated scorer/host helper. Likely the arbiter (it's already the oracle seam).
3. **Manifest format.** CONTEXT's per-app oracle manifest — schema + where it lives (alongside
   the target APK / device-spec?), so each ladder rung (RootBeer → RASP → real) declares its own
   signal.
4. **Interaction with self-report.** Keep self-report as a fast-path hint but require the
   machine check to confirm, vs replace it outright.

## Established context
- Ticket 05b's arbiter currently trusts self-report; this ticket swaps that judgment for a real
  check without changing the termination/verdict wiring.
- CONTEXT "Oracle" term + `spec.md` record the self-report→manifest evolution.
