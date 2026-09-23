# 02: Prove resident frida converts the dbs near-miss into a completed bypass

**What to build:** Demonstrate end-to-end that the resident-frida fix turns dbs — where the agent
previously authored a correct detection hook that never fired because the session tore down and the
app stayed frozen — into a completed RASP bypass that reaches the app's real UI. This is the live
"the environment no longer eats the win" check for ticket 01.

**Blocked by:** 01 (resident frida + auto-foreground must be built and in the sandbox image first).

**Status:** ready-for-agent

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
