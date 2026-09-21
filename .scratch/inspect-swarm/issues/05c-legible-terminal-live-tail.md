# 05c: Legible terminal + live per-worker tail (kill the TUI clobber)

**What to build:** when you launch a swarm, the terminal **stays legible** (no N fullscreen
Inspect TUIs fighting over one screen), you get a **live per-worker view** of what each agent is
doing, and **Ctrl-C tears the whole swarm down with no orphaned emulator/bridge processes**. Two
ways to watch, both work: `tail -f` the per-worker console files (guaranteed live), or run the
printed `inspect view` command for the rich browser transcript (post-hoc guaranteed; live-ish).
The insight this ticket rests on: replacing the fullscreen TUI with a per-worker
`--display conversation` redirect makes the terminal-cleaner and the live view **the same change**
— the live tail falls out of fixing the terminal, so there is no separate dashboard to build.

**Blocked by:** 05b (the Conductor — owns the run-launch, env-injection, and `_shutdown` seams
this ticket edits).

**Status:** built (hermetic; awaits the live hand-run smoke, like 04/05a/05b).

## Acceptance
- [x] **No fullscreen TUI.** Each worker run is launched with `--display conversation` instead of
      the default fullscreen TUI, so no worker paints a curses UI over the terminal. The launching
      terminal shows **only the conductor's own lifecycle lines** — legible with N=1 or N=many.
- [x] **Live per-worker tail.** Each worker's stdout+stderr (merged, so tracebacks land too) is
      redirected to `logs/<swarm-id>/<agent-id>/console.out`. `tail -f logs/<swarm-id>/*/console.out`
      shows each agent's conversation streaming **live, per model turn, ANSI-free**, labeled per
      worker (each worker is its own process → its own file → no interleaving).
- [x] **Per-agent log dir (legibility for the webview path).** Each worker's
      `INSPECT_LOG_DIR = logs/<swarm-id>/<agent-id>/` (restores the ADR-0002 `<swarm-id>/<agent-id>/`
      intent that 05b flattened), so its `.eval` is legibly separated and
      `inspect view --log-dir logs/<swarm-id> --recursive` lists **one distinguishable entry per
      worker**. The board is still saved to `logs/<swarm-id>/messageboard/` (05b, unchanged).
- [x] **Detached + owned teardown (the one correctness item).** Workers start in their own
      session/process group (`start_new_session`), and `_shutdown` kills each worker's **whole
      process group** (SIGTERM → grace → SIGKILL). So Ctrl-C or an over-cap fail-fast leaves **no
      orphaned emulator/bridge/docker grandchildren**. `start_new_session` and the group-kill are
      one atomic change — shipping detachment without the group-kill is a strict regression (the
      tty can no longer reach the detached workers, so the conductor becomes the only kill path).
- [x] **Lifecycle status lines + watch hints.** The launcher prints one concise line per step
      (acquire / launch / verdict / teardown), and right after launch prints the **two watch
      hints**: the `tail -f logs/<swarm-id>/*/console.out` command and the
      `inspect view --log-dir logs/<swarm-id> --recursive --port <p>` command.
- [x] **N=1-is-single, uniform path.** Identical launch/redirect/teardown for one worker and N.
- [x] **05b preserved + new hermetic tests.** All 05b behaviour and its passing suite stay green.
      New tests use the injected fakes (no real subprocess / broker / emulator / server) and cover:
      the argv carries `--display conversation`; the runner redirects to the per-agent
      `console.out` and sets `start_new_session`; per-agent `INSPECT_LOG_DIR`; `_shutdown` issues a
      **process-group** kill (not a per-`Popen` kill).
- [ ] **Live smoke (broker up, hand-run like 04 / 05a / 05b).** `python swarm.py --workers 2` →
      terminal stays legible; `tail -f` shows both agents streaming live; the printed `inspect view`
      command serves a legible per-worker list; Ctrl-C stops the swarm and `ps` confirms **no
      orphaned emulator/bridge processes** survive.

## Notes / deferred
- **What the tail actually shows (set expectations):** the **model's-eye view**, bursty per model
  turn. You see the agent's reasoning + the command it *decides* to run immediately; the command's
  real output appears **one turn later** as the tool result the model reads back — not a live shell,
  not real-time frida/adb stdout. Between turns the file is quiet (normal, not a hang); cadence
  tracks model latency.
- **Webview is a printed manual command, not conductor-managed** (settled: Q11). Auto-launching
  `inspect view` (injectable launcher + teardown-in-`finally` + `dashboard_port` in
  `SwarmConfig`/CLI + `--trusted-origin`) is **deferred** — the `.eval` files update live, so the
  webview "works" by running the printed command in a spare terminal when wanted. Promote to
  auto-launch later only if pasting the command proves annoying (isolated follow-up).
- **Webview mid-run liveness is not a concern** (settled). The **tail carries the live
  requirement** (proven). The webview is guaranteed rich for post-hoc review and live-*ish* if the
  pending-sample buffer surfaces an in-progress single sample — nice if it does, not required.
- **`--watch-board` (live board-delta tail) → its own later ticket.** The board is a *different*
  signal (inter-agent coordination + verdicts) the transcript can't show; it deserves its own view,
  not a cram into this ticket's freshly-cleaned terminal.
- **Bespoke swarm cockpit (custom UI + in-browser stop button) is out.** This dashboard is a
  *means* (watch runs to iterate faster on the root-bypass probe), not an *end*. An in-browser stop
  button would need a control-plane + a custom UI (Inspect's viewer is read-only) — a separate
  ticket if that itch ever returns.

## Design decisions (settled with the user via grilling)
- **Display = `conversation`, not `none`/`plain`.** `conversation` streams the transcript per-turn
  to a file, ANSI-free and flushed incrementally (verified against inspect-ai 0.3.263); `plain` is
  a **block-buffered** heartbeat (nothing appears until process exit without `PYTHONUNBUFFERED`) and
  `none` is blind. So `conversation` is what makes "clean terminal" and "live view" one change.
- **Stop = Ctrl-C on the launcher** (it owns the process group from the group-kill above). No
  in-browser stop button.
- **Scope stayed small on purpose.** The handed-down "05c dashboard" treated a clean terminal as a
  *prerequisite to* a conductor-managed browser dashboard; grilling collapsed it to ~four edits in
  files 05b already owns (`build_run_argv`, `subprocess_runner`, `build_run_env`, `_shutdown`) plus
  two printed hints. The heavier dashboard is opt-in later, not this ticket.

## Comments

**Built (2026-09-21).** Implemented as the ticket scoped it — the four 05b-owned seams plus the
two printed hints, no separate dashboard:

- `swarm_eval/agent_runner.py` — `build_run_argv` gained a `display` param (the conductor passes
  `conversation`); `RunSpec` gained `console_path`; `RunHandle` now teardowns at the
  process-group level (`terminate_group`/`kill_group`, replacing the lone-process `terminate`/
  `kill`); new `RunProcess` handle wraps `Popen` and group-signals via `os.killpg(os.getpgid(pid))`
  when detached (attached fallback signals only the lone proc, so single_agent never hits the
  launcher's own group); `subprocess_runner` redirects a worker's merged stdout+stderr into its
  `console.out` and sets `start_new_session=True` — one atomic change with the group-kill.
- `swarm_eval/conductor.py` — per-worker log dir `logs/<swarm-id>/<agent-id>/` (restores the
  ADR-0002 intent 05b flattened): its `INSPECT_LOG_DIR`, `.device` contract, and `console.out`;
  board still saved to `messageboard/`. `_shutdown` group-kills; `run()` prints the acquire /
  launch / teardown lifecycle lines and the two watch hints (`tail -f …/*/console.out` and
  `inspect view --log-dir … --recursive --port 7575`) right after launch. `--display conversation`
  applies uniformly at N=1 and N; single_agent (`console_path=None`) stays attached to the tty.

**Verification:** the affected suites are green (conductor/agent_runner/single/swarm CLI). 9 new
hermetic tests (no real subprocess/broker — `Popen`, `os.killpg`/`os.getpgid` are monkeypatched or
faked): argv carries `--display conversation`; the runner redirects to the per-agent `console.out`
and sets `start_new_session` (and stays attached when there's no console); per-agent
`INSPECT_LOG_DIR`; and `_shutdown` escalates a **process-group** kill, never a per-`Popen` one.
Full suite: 138 passed, 1 pre-existing unrelated failure (`test_mission.py`, from in-flight
`mission.py` work). The **live smoke** (broker up, `python swarm.py … --workers 2`, `tail -f`, the
printed `inspect view`, Ctrl-C → no orphaned emulator/bridge) remains a hand-run, like 04/05a/05b.

**Reviewed** (two-axis Standards+Spec, `code-review` skill). Standards: no hard violations; renamed
`WorkerProcess`→`RunProcess` (it wraps single_agent runs too, so it is named for the run not the
role). Spec: faithful, no scope creep (the deferred `inspect view` auto-launch, `dashboard_port`,
and `--watch-board` are all absent); added an unconditional teardown lifecycle line so the
"line per step" holds on a clean cooperative exit, not only when a straggler is killed.
