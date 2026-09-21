# 05d: Provisioning progress lines + auto-start the inspect webview

**What to build:** two launcher UX fixes that fell out of the first live N=3 hand-run of 05c.
(1) The launcher goes **silent for minutes** while the broker cold-boots + provisions each
worker's emulator (`bin/broker acquire` blocks up to 900s per device) — it looks hung. Add a
**per-device progress heartbeat** so the operator sees `acquiring device 2/3 …` → `worker-2 ←
emulator-5556 (47s)` as each lease lands. (2) The 05c webview is a *printed manual command*; in
practice you always want it, so **auto-start `inspect view` by default** (torn down in the same
`finally` as the workers), with `--no-view` to opt out.

**Blocked by:** 05c (owns the `_acquire_and_plan` heartbeat point, the `run()`/`finally`
lifecycle, and the printed watch hints this ticket promotes to a live server).

**Status:** built (hermetic; awaits the live hand-run smoke, like 05c).

## Acceptance
- [x] **Acquire progress heartbeat.** `_acquire_and_plan` logs one concise line **before** each
      blocking `acquire` (`swarm <id>: acquiring device i/N …`) and one **after** it lands
      (`swarm <id>: worker-i ← <serial> (<elapsed>s)`), using the injected clock for elapsed. So a
      3-worker cold-boot shows steady progress instead of a dead terminal. (No % bar — the broker
      subprocess doesn't stream step progress; the per-device line + elapsed is the heartbeat.)
- [x] **Auto-start the webview by default.** After the workers launch, the Conductor starts
      `inspect view --log-dir logs/<swarm-id> --recursive --port <view-port>` as a host subprocess
      and prints its URL (`http://localhost:<view-port>`). The launcher is **injectable** (like
      `runner`/`acquire`) so tests never spawn a real server.
- [x] **`--no-view` opts out; `--view-port` sets the port.** `SwarmConfig` gains `view: bool = True`
      and `view_port: int = DEFAULT_VIEW_PORT` (7575). `swarm.py` gains `--no-view`
      (`store_false`) and `--view-port`. With `--no-view`, the Conductor prints the **manual
      command hint** (05c behaviour) instead of launching — and launches no server.
- [x] **Owned teardown.** The view server is stopped in the **same `finally`** that tears down
      workers / saves the board / releases devices — Ctrl-C or any crash leaves no orphaned
      `inspect view` process. Teardown is best-effort (a view-kill failure never masks the run
      error or blocks device release).
- [x] **Tail hint stays.** The `tail -f logs/<swarm-id>/*/console.out` hint still prints
      regardless of `--view` (the tail is the guaranteed-live view; the webview is the rich one).
- [x] **05c preserved + new hermetic tests.** All 05c behaviour + its suite stay green. New tests
      use injected fakes (no real subprocess/broker/server): the view launcher is called with
      `(log_dir, view_port)` when `view=True` and its handle is torn down in the `finally`; it is
      **not** called when `view=False` (and the manual hint prints instead); `--no-view` /
      `--view-port` map onto `SwarmConfig`; the acquire heartbeat emits a line per device.
- [ ] **Live smoke (broker up, hand-run).** `python swarm.py devices/rasp_dummy.yaml --workers 3`
      → progress lines tick as each emulator boots; the browser viewer opens at the printed URL and
      lists all 3 workers; Ctrl-C stops the swarm AND the viewer (`ps` shows no orphaned
      `inspect view`). `--no-view` reverts to the printed-command behaviour.

## Notes / deferred
- **This promotes the 05c Q11 deferral.** 05c settled the webview as a *printed manual command,
  not conductor-managed* ("deferred"). The first live run reversed that: the operator always wants
  it up. This ticket implements exactly the design 05c's deferred note pre-scoped (injectable
  launcher + teardown-in-`finally` + `view_port` in `SwarmConfig`/CLI). Recorded here so the
  reversal is deliberate, not a silent contradiction of 05c.
- **Loopback only.** `inspect view` binds loopback by default, so no `--host` / auth flags — the
  viewer is reachable at `http://localhost:<port>` on this host. `--trusted-origin` stays unused
  until a cross-origin need appears (isolated follow-up).
- **No mid-run auto-open of the browser.** We print the URL; we don't shell `open <url>`
  (leave the operator to click) — auto-opening a browser tab per run is more annoyance than help.
- **Still no in-browser stop button / bespoke cockpit** (05c, unchanged): Inspect's viewer is
  read-only; stop is Ctrl-C on the launcher.

## Design decisions
- **View launcher is injectable + returns a handle** (mirrors the `runner` seam): the default
  Popens `inspect view …`; a test injects a fake that records the call and hands back a fake
  handle, so the whole orchestration stays hermetic.
- **Elapsed via the injected clock**, not `time.time()` — keeps the heartbeat testable and
  consistent with the rest of the Conductor's injected-time discipline.
- **Default on, flag off** (`--no-view`), per the operator's stated preference ("start the inspect
  server by default, unless flag otherwise").

## Comments

**Built (2026-09-21).** Both items, in the seams 05c left:

- `swarm_eval/conductor.py` — `_acquire_and_plan` now logs `acquiring device i/N …` before each
  blocking acquire and `worker-i ← <serial> (<elapsed>s)` after (elapsed via the injected clock).
  New `ViewHandle`/`ViewLauncher` seam + `launch_inspect_view` default (Popens `inspect view
  --log-dir <swarm-dir> --recursive --port <p>`, output → `view.log` so the terminal stays clean);
  injected into `Conductor` like `runner`. `SwarmConfig` gained `view`/`view_port`. `run()` starts
  the webview after launch (via `_start_watch_views`, which still always prints the `tail -f` hint)
  and stops it in the `finally` (`_stop_view`, best-effort) alongside worker teardown / board save
  / device release.
- `swarm.py` — `--no-view` (`store_false`) and `--view-port`, mapped onto `SwarmConfig`.

**Verification:** full suite green (146 passed). New hermetic tests (fake view launcher, no real
server): webview launched once over the swarm log dir at the configured port and torn down in the
`finally` (incl. on a FAILURE teardown); not launched under `--no-view`; the default
`launch_inspect_view` builds the exact argv and redirects to `view.log`; `--no-view`/`--view-port`
map onto the config; and the acquire heartbeat emits a line per device. Live smoke remains a
hand-run (`python swarm.py devices/rasp_dummy.yaml --workers 3`).

**Promotes the 05c Q11 deferral** (webview auto-launch) deliberately — see Notes.
