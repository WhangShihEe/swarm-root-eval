# 02: Prove resident frida converts the dbs near-miss into a completed bypass

**What to build:** Demonstrate end-to-end that the resident-frida fix turns dbs — where the agent
previously authored a correct detection hook that never fired because the session tore down and the
app stayed frozen — into a completed RASP bypass that reaches the app's real UI. This is the live
"the environment no longer eats the win" check for ticket 01.

**Blocked by:** 01 (resident frida + auto-foreground must be built and in the sandbox image first).

**Status:** blocker-reported (accepted outcome) — env plumbing + resident-frida image validated; served-model stamp (ticket 03) validated live; dbs bypass NOT completed within budget (precise finding below), per ticket criterion "a clear blocker report is itself a valid outcome"

Context: `.scratch/env-hardening/report.md` §S1 depth synthesis — dbs is the corpus's clearest
near-miss, blocked only by the frida lifecycle gap (spawn-freeze), not by V-Key hardness.

- [ ] A single-agent run against dbs (~10–30 min wall) completes with the agent using resident mode.
- [ ] A throwaway, per-run prompt override tells the agent to **stop once the RASP is bypassed** and
      skip the exploit phase; this override is not a committed spec change.
- [ ] From the run's log and the device: the detection hook stayed effective and the app reached a
      RESUMED real UI (activity-manager state + a non-blank UI dump), with no fatal crash after launch.
- [ ] Budget noted for the runner: a working-time limit (~600s) under a wall ceiling, since
      rate-limit backoff dominates wall time.
- [ ] If dbs still does not complete, the run captures a precise blocker and says whether it is still
      tooling or now genuine V-Key hardness — a clear blocker report is itself a valid outcome.

## Comments

## Outcome (orchestrator Phase B — live run)

Run: `single_agent.py configs/evals/dbs_solution.yaml`, served model
`openai-api/litellm/bedrock-claude-opus-4.8`, 10:06 wall, log
`swarm-eval/logs/single-20260923T172636-3d29e3/`. Device leased + released cleanly (pool 0/6).

**Validated:**
- Environment plumbing end-to-end: the resident-frida sandbox image (ticket 01) builds and runs,
  `single_agent.py` leases/releases the broker device, eval finishes rc=0.
- Ticket 03 served-model stamp, live and non-Claude: `eval.metadata.served_model` /
  `sample.metadata.served_model` = `openai-api/litellm/bedrock-claude-opus-4.8`, matching
  `eval.model` and the sample's `model_usage`.

**Not completed (the precise blocker):** the run did NOT demonstrate the resident-frida *conversion*
to a stable UI. Two reasons:
1. **The near-miss premise was partly wrong.** dbs does NOT hard-block at startup on this image: a
   plain `am start` on `…ui.demo.SplashActivity` reaches a real pre-login screen
   (`…ui.vbonboarding.VBOnboardingMFEPreLoginActivity`, RESUMED, visible) — no bypass needed to
   reach *that*. The wall is that the app is then reaped/backgrounded to the Nexus launcher (cached-
   apps freezer and/or a DELAYED V-Key verdict). So the goal is to keep it *stable* at its UI, not
   to clear a startup gate.
2. **Budget.** With `time_limit: 600` the agent spent the whole window on V-Key VGuard static
   analysis (`jadx --deobf` slow, `apktool` exit=1) + adb-reconnect friction and hit the limit
   **before** ever invoking `frida-run -k` — the resident path was never exercised.

Protection identified for a future run: V-Key VGuard, native-backed — `com.vkey.android.vguard`
(`VGuardFactory$Callback` threat callback) + `libvos*/libvguard*.so`.

**Decision (user):** accept this as the valid blocker outcome for ticket 02; do NOT spend another
run now. `configs/evals/dbs_solution.yaml` was corrected to match the observed behaviour (start from
VBOnboarding + reap; skip full decompile; target VGuard; `time_limit` raised to 1200) so it is a
correct oracle whenever someone chooses to run it later.
