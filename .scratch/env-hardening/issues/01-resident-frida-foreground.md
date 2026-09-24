# 01: Dynamic agent can hold a frida hook live while it drives the app

**What to build:** The dynamic agent can neutralize a RASP check and then reach the app's real UI in
one go. Today the frida runner detaches the instant the agent signals it is "done" — so the hook is
gone before the app exercises it — and a spawned app can sit frozen in the background and never run
the guarded code the hook targets. After this, the agent has a **resident** mode that keeps the
session (and the hook) live until it is killed, a spawned app is **brought to the foreground** so it
actually runs, and the agent knows the mode exists so it uses it.

**Blocked by:** None (can start immediately).

**Status:** done — all 6 criteria met; criterion 5 (real image build + build-time runner check) and criterion 6 (on-device rasp_dummy canary) confirmed live in orchestrator Phase B

Context: `.scratch/env-hardening/report.md` §S1 — device before/after already captured (shipped runner
detaches at the "done" signal; a held session keeps the hook effective; an unfocused app is frozen/
reaped so its hook never fires).

- [ ] A resident/keep-alive mode holds the frida session open until it is signalled to stop; a "done"
      message from the agent no longer tears the session down in that mode.
- [ ] The existing (non-resident) behaviour is unchanged when the mode is not requested.
- [ ] After a spawn, the app is auto-foregrounded (prefer the activity-manager start over `monkey`,
      which was flaky on this image), with an opt-out — the "hook loaded but never fires because the
      app is frozen in the background" case no longer happens.
- [ ] The agent actually discovers the mode: the dynamic-agent mission guidance and the runner's own
      `--help` describe resident mode and when to use it (persist a hook while driving adb/uiautomator
      or capturing traffic; foreground a spawn). An opt-in nobody is told about buys nothing.
- [ ] A live agent gets the new runner: the sandbox image is rebuilt and its build-time runner check
      still passes.
- [ ] Confirmed on a real device against the owned `rasp_dummy` canary: a hook stays effective across
      a held session, and a spawned app reaches the foreground.

## Comments

## Phase B on-device confirmation (criterion 6) — PASSED

Device: brokered writable-system pixel/android-15 (emulator-5554), rasp_dummy installed. Ran the
SHIPPED `frida-run` inside the `swarm-eval-default` sandbox image against the app, pure-JS heartbeat
probe (`send` every 1s, emits `done` at beat 3):

- **Resident holds past `done`:** output showed `heartbeat n:1,2,3` → `done ok=True` PRINTED →
  `heartbeat n:4,5,…,10` (`hooked:True` throughout) → `resident session ended after 10.0s window`.
  The `done` did NOT tear the session down; the hook stayed effective across the whole held window.
- **Auto-foreground via `am start`:** `[frida-run] foregrounded com.example.rasptarget/.MainActivity
  via am start`, and a host-side `dumpsys activity activities` mid-hold showed
  `topResumedActivity=com.example.rasptarget/.MainActivity` RESUMED (not the launcher) — `am start`
  path taken, not `monkey`.

Criterion 5 also confirmed: the real full `docker compose build` (corp CA present) succeeded and the
build-time runner check printed `frida-py 17.17.0` / `frida-run --help` exit 0 / `objection 1.12.5`.
