"""The Conductor — the external swarm launcher/arbiter/collator (ticket 05b).

Turns N ticket-04 agent runs + the 05a board into one swarm run. Entirely **outside** Inspect
(ADR-0002): Inspect has no cross-run shared state, so the swarm layer — launch, coordinate,
judge, collate — lives host-side. Per swarm run the Conductor:

  board up  →  devices acquired  →  worker runs launched  →  arbitrate (wait for a verdict)
            →  post `done`  →  collate + save board  →  release all devices  →  teardown

Every device is released and the board is saved even if a step raises (the `finally` below), so
a crashed run never leaks a scarce broker slot or loses the conversation.

**Arbiter = a host-side rubric**, not a separate bridged run (a deliberate simplification of the
ticket's "own bridged run": an LLM cannot be trusted to honour a wall-clock budget, and the
verdict rubric is machine-decidable). `evaluate_board` is the seam where ticket 06's
machine-checkable oracle swaps in — the launch/termination/collation wiring around it is
unchanged. Self-report MVP: first credible `success` wins; all-`giveup` (or the budget) loses.

Termination has three layers: (a) workers poll the board and stop when `done` is posted
(cooperative, in the worker prompt); (b) each run carries a per-run Inspect `--time-limit` /
`--message-limit` (no run loops forever); (c) the Conductor kills any run still alive after
`done` + a grace (`_terminate`).

`N=1-is-single`: N=1 is one worker + the host-side arbiter over a one-participant board — the
same code path as N>1, not special-cased.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import agent_runner
from .agent_runner import (
    DEFAULT_MODEL,
    DEFAULT_TIME_LIMIT,
    DEFAULT_WORKER_TASK,
    ENV_INSPECT_LOG_DIR,
    RunHandle,
    RunSpec,
    Runner,
    mint_run_id,
    swarm_eval_dir,
)
from .agent_runner import acquire as broker_acquire
from .agent_runner import release as broker_release
from .board_tools import ENV_AGENT_ID
from .broker_client import DEFAULT_SPEC, Contract
from .messageboard import (
    ENV_BOARD_DIR,
    ENV_SWARM_ID,
    TYPE_DONE,
    TYPE_GIVEUP,
    TYPE_SUCCESS,
    Board,
    board_dir,
)
from .target import load_target

logger = logging.getLogger(__name__)

# The swarm-only slice of the launcher↔run injection contract: the board coordinates the
# Conductor sets per worker on TOP of the shared per-run pair (`DEVICE_CONTRACT` +
# `INSPECT_LOG_DIR`, owned by `agent_runner`). `ENV_BOARD_DIR`/`ENV_SWARM_ID` (the board's own,
# from messageboard) and `ENV_AGENT_ID` (board_tools) are re-used; these are the swarm-launch
# additions. Their presence (`SWARM_ID`) is what tells a run it is a swarm worker, not a single.
ENV_ROLE = "ROLE"
ENV_WORKER_IDS = "SWARM_WORKER_IDS"  # the worker roster, so a run knows its peers by name

ROLE_WORKER = "worker"
ROLE_ARBITER = "arbiter"  # the author the host-side arbiter stamps on its `done` verdict

# Verdict values — the same tokens the per-run self-report oracle uses.
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"

# The device cap mirrors the broker's POOL_CAP (the broker still enforces the hard cap; this is
# the launcher's fail-fast courtesy). The worker task, model, and per-run time-limit defaults are
# the shared ones from `agent_runner` (re-exported above for `SwarmConfig`/tests).
DEFAULT_CAP = 6

# Each worker is launched with Inspect's `conversation` display (05c): it streams an ANSI-free
# transcript to the worker's console file per model turn (flushed incrementally) instead of
# painting a fullscreen curses TUI — so N workers no longer fight over one terminal, and the same
# redirect is the live tail. `plain` is block-buffered (blind until exit) and `none` shows nothing.
DISPLAY_CONVERSATION = "conversation"

# The per-worker console file (merged stdout+stderr) under each worker's log dir — `tail -f` this
# for the guaranteed-live view; one file per worker (own process) means no interleaving.
CONSOLE_FILENAME = "console.out"

# The auto-started webview server's own output (05d) lands here under the swarm log dir, so its
# chatter stays off the launcher terminal (the 05c clean-terminal ethos) but is there to debug a
# bind failure ("why didn't the viewer come up?").
VIEW_LOG_FILENAME = "view.log"

# A concrete port for the printed `inspect view` watch hint so the command is copy-pasteable (the
# operator changes it if taken). A conductor-managed webview — injectable launcher + a configurable
# `dashboard_port` — is deferred (05c Notes); the `.eval` files update live under the log dir, so
# the webview "works" by running this printed command in a spare terminal.
DEFAULT_VIEW_PORT = 7575


class SwarmError(RuntimeError):
    """A swarm run could not be set up (e.g. more workers than the device cap)."""


def mint_swarm_id() -> str:
    """A fresh, sortable, human-legible swarm id: `swarm-<utc>-<shortid>` (via the shared
    `mint_run_id`). The stamp orders swarm dirs chronologically; the shortid keeps two
    same-second runs distinct."""
    return mint_run_id("swarm")


def worker_agent_id(i: int) -> str:
    """The 1-based worker id (`worker-1`, `worker-2`, …) — the run's `AGENT_ID` and board author."""
    return f"worker-{i}"


@dataclass(frozen=True)
class SwarmConfig:
    """One swarm run's knobs. `board_root`/`log_root` default under `swarm-eval/`; the launched
    runs resolve the actual board at `board_root/<swarm-id>/` and log into `log_root/<swarm-id>/`.
    """

    workers: int = 1
    model: str = DEFAULT_MODEL
    spec: str = DEFAULT_SPEC
    worker_task: str = DEFAULT_WORKER_TASK
    cap: int = DEFAULT_CAP
    time_limit: int | None = DEFAULT_TIME_LIMIT  # per-run Inspect --time-limit (s); layer (b)
    message_limit: int | None = None  # per-run Inspect --message-limit; layer (b), opt-in
    budget: float = 3600.0  # launcher hard wall-clock: fail the swarm if no verdict by then
    grace: float = 30.0  # seconds a run gets to notice `done` and exit before it is killed
    poll_interval: float = 2.0  # how often the arbiter re-reads the board
    view: bool = True  # auto-start the inspect webview over the logs (05d); --no-view opts out
    view_port: int = DEFAULT_VIEW_PORT  # the auto-started webview's port
    board_root: Path = field(default_factory=lambda: swarm_eval_dir() / "board")
    log_root: Path = field(default_factory=lambda: swarm_eval_dir() / "logs")


@dataclass(frozen=True)
class Verdict:
    """The swarm's outcome. `trigger` is the board index entry (a `success`) that decided a win,
    for the transcript; None for a loss."""

    value: str  # SUCCESS | FAILURE
    reason: str
    trigger: dict[str, str] | None = None


@dataclass(frozen=True)
class SwarmResult:
    """What one swarm run produced: its id, where the collated artifact landed, the verdict, and
    the worker roster."""

    swarm_id: str
    log_dir: Path
    board_path: Path
    verdict: Verdict
    worker_ids: list[str]


def build_run_env(
    *,
    config: SwarmConfig,
    swarm_id: str,
    agent_id: str,
    role: str,
    log_dir: Path,
    device_contract: Path | None = None,
    worker_ids: list[str] | None = None,
) -> dict[str, str]:
    """The env injected into one worker run: the swarm-only board coordinates layered on top of
    the shared per-run pair (`DEVICE_CONTRACT` + `INSPECT_LOG_DIR`) via `agent_runner`. The board
    coordinates (`SWARM_ID` etc.) are the swarm signal a worker keys off; kept minimal so a test
    can assert the injection exactly."""
    board_env = {
        ENV_BOARD_DIR: str(config.board_root),
        ENV_SWARM_ID: swarm_id,
        ENV_AGENT_ID: agent_id,
        ENV_ROLE: role,
    }
    if worker_ids:
        board_env[ENV_WORKER_IDS] = ",".join(worker_ids)
    if device_contract is None:
        # A contract-less role (no device) still carries its log dir + the board coordinates.
        return {ENV_INSPECT_LOG_DIR: str(log_dir), **board_env}
    return agent_runner.build_run_env(
        contract_path=device_contract, log_dir=log_dir, board_env=board_env
    )


def build_run_argv(*, config: SwarmConfig, task: str) -> list[str]:
    """The `inspect eval` argv for one worker run — the shared `agent_runner` builder fed from
    this swarm's config (target yaml + model + per-run limits). `-T spec=<yaml>` selects the
    worker's target (the same device yaml the launcher pre-acquired) so the spawned
    `dynamic_agent` stages the right APK(s) + mission (apk-agnostic refactor)."""
    return agent_runner.build_run_argv(
        spec=config.spec,
        model=config.model,
        task=task,
        time_limit=config.time_limit,
        message_limit=config.message_limit,
        display=DISPLAY_CONVERSATION,
    )


def evaluate_board(entries: list[dict[str, str]], worker_ids: list[str]) -> Verdict | None:
    """One rubric pass over the board index. Returns a `Verdict` when the board is decisive, else
    None (keep waiting). **Self-report MVP** and the ticket-06 oracle seam: the first credible
    `success` wins; the swarm loses once every worker has posted `giveup`. `success` is checked
    before `giveup` so one worker's win beats another's surrender regardless of order.

    Note the two vocabularies this bridges: the board's message *types* (`TYPE_SUCCESS`/
    `TYPE_GIVEUP`) drive the rubric, while the `Verdict` *value* (`SUCCESS`/`FAILURE`) is the
    swarm outcome — a worker's `success` message yields a `SUCCESS` verdict."""
    for e in entries:
        if e.get("type") == TYPE_SUCCESS:
            return Verdict(SUCCESS, f"{e['author']} reported success ({e['id']})", trigger=e)
    givers = {e["author"] for e in entries if e.get("type") == TYPE_GIVEUP}
    if worker_ids and set(worker_ids) <= givers:
        return Verdict(FAILURE, f"all {len(worker_ids)} worker(s) gave up")
    return None


def arbitrate(
    board: Board,
    worker_ids: list[str],
    *,
    budget: float,
    poll_interval: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Verdict:
    """Watch the board until the rubric is decisive or the hard `budget` (wall-clock, seconds)
    elapses. On the budget, the swarm loses (a hung/empty run never produces a verdict). `clock`
    and `sleep` are injected so a test drives it without real time."""
    deadline = clock() + budget
    while True:
        verdict = evaluate_board(board.list(), worker_ids)
        if verdict is not None:
            return verdict
        if clock() >= deadline:
            return Verdict(FAILURE, f"swarm budget elapsed ({budget:g}s) before a verdict")
        sleep(poll_interval)


class ViewHandle(Protocol):
    """The slice of the inspect-view subprocess the Conductor drives — so a test injects a fake
    with no real server. Stopped (`terminate`) in the same `finally` that tears the swarm down."""

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


# A view launcher turns (log_dir, port) into a running webview handle (05d). Injected like
# `runner`, so the orchestration stays hermetic; the default below Popens the real `inspect view`.
ViewLauncher = Callable[[Path, int], ViewHandle]


def launch_inspect_view(log_dir: Path, port: int) -> subprocess.Popen:
    """Start the read-only inspect webview over the swarm's live-updating `.eval` logs (05d):
    `inspect view --log-dir <log_dir> --recursive --port <port>`, in `swarm-eval/`. `--recursive`
    lists one entry per worker (the per-agent log dirs from 05c). Binds loopback, so it is reachable
    at `http://localhost:<port>` with no auth flags. Its stdout+stderr go to `view.log` under the
    swarm dir (keeps the launcher terminal clean; a bind failure is still there to read) — the
    parent's copy of the file is closed right after spawn, the child keeps its dup. The Conductor
    stops it in its `finally`."""
    argv = ["inspect", "view", "--log-dir", str(log_dir), "--recursive", "--port", str(port)]
    view_log = open(log_dir / VIEW_LOG_FILENAME, "w", encoding="utf-8")
    try:
        return subprocess.Popen(
            argv, cwd=str(swarm_eval_dir()), stdout=view_log, stderr=subprocess.STDOUT
        )
    finally:
        view_log.close()


class Conductor:
    """Runs one swarm. Inject `runner`/`acquire`/`release`/`clock`/`sleep`/`view_launcher` to
    exercise the whole orchestration hermetically (no real subprocess, broker, wall-clock, or
    webview server)."""

    def __init__(
        self,
        config: SwarmConfig,
        *,
        runner: Runner = agent_runner.subprocess_runner,
        acquire: Callable[..., Contract] = broker_acquire,
        release: Callable[[str], None] = broker_release,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        view_launcher: ViewLauncher = launch_inspect_view,
    ) -> None:
        self.config = config
        self._runner = runner
        self._acquire = acquire
        self._release = release
        self._clock = clock
        self._sleep = sleep
        self._view_launcher = view_launcher

    def run(self) -> SwarmResult:
        cfg = self.config
        if cfg.workers < 1:
            raise SwarmError("a swarm needs at least 1 worker")
        # Fail-fast over the cap (the broker enforces the hard cap too). Queueing is the deferred
        # alternative; failing loudly is the MVP so an over-provisioned run never half-acquires.
        if cfg.workers > cfg.cap:
            raise SwarmError(
                f"{cfg.workers} workers exceed the device cap ({cfg.cap}) — reduce workers or "
                f"raise --cap (the broker still enforces its own hard cap)"
            )

        swarm_id = mint_swarm_id()
        log_dir = cfg.log_root / swarm_id
        log_dir.mkdir(parents=True, exist_ok=True)
        board = Board(board_dir(cfg.board_root, swarm_id))
        board.ensure()
        worker_ids = [worker_agent_id(i) for i in range(1, cfg.workers + 1)]

        acquired: list[str] = []  # serials to release at teardown (populated as we acquire)
        handles: list[RunHandle] = []
        view_handle: ViewHandle | None = None  # the auto-started webview, stopped in the finally
        done_posted = False  # did the arbiter announce `done`? gates the cooperative-stop window
        logger.info("swarm %s: %d worker(s), board=%s", swarm_id, cfg.workers, board.path)
        try:
            # board up → devices acquired (all, before any launch) → runs launched.
            specs = self._acquire_and_plan(swarm_id, log_dir, worker_ids, acquired)
            logger.info("swarm %s: acquired %d device(s): %s", swarm_id, len(acquired),
                        ", ".join(acquired))
            # Append each handle as it is spawned (not a comprehension): if a later launch raises,
            # the already-spawned runs are still in `handles` for the `finally` to tear down — no
            # orphaned subprocess.
            for spec in specs:
                handles.append(self._runner(spec))
            logger.info("swarm %s: launched %d worker(s)", swarm_id, len(handles))
            view_handle = self._start_watch_views(log_dir)
            # arbitrate: wait for a verdict (or the budget), then announce it so workers stop.
            verdict = arbitrate(
                board,
                worker_ids,
                budget=cfg.budget,
                poll_interval=cfg.poll_interval,
                clock=self._clock,
                sleep=self._sleep,
            )
            self._post_done(board, verdict)
            done_posted = True
            logger.info("swarm %s: verdict %s — %s", swarm_id, verdict.value, verdict.reason)
            return SwarmResult(swarm_id, log_dir, board.path, verdict, worker_ids)
        finally:
            # A failure at any step still releases devices, stops the webview, and saves what exists.
            self._shutdown(handles, cooperative=done_posted)
            self._stop_view(view_handle)
            self._save_board(board, log_dir)
            self._release_all(acquired)

    def _acquire_and_plan(
        self, swarm_id: str, log_dir: Path, worker_ids: list[str], acquired: list[str]
    ) -> list[RunSpec]:
        """Pre-acquire one device per worker (the dynamic role) and build each run's spec. Each
        worker gets its OWN log dir `log_dir/<agent-id>/` (05c: restores the ADR-0002
        `<swarm-id>/<agent-id>/` intent, so `inspect view --recursive` lists one distinguishable
        entry per worker) — its `INSPECT_LOG_DIR`, the `<agent-id>.device` contract injected as
        `DEVICE_CONTRACT`, and the `console.out` its stdout+stderr stream to (the live tail). The
        serial is recorded in `acquired` *before* the next acquire, so a mid-way failure still
        releases every device already granted (the caller's `finally`).

        Each `acquire` **blocks** while the broker cold-boots + provisions that device (up to its
        900s timeout), so a per-device heartbeat is logged before and after each one (05d) —
        otherwise the launcher looks hung for minutes with N workers."""
        # Resolve the positional config once (an eval config or a legacy device yaml): which
        # device each acquire leases and, when the config splits the APK out, which APK to install
        # (`--target-apk`). The workers' `-T spec=` stays the positional itself (build_run_argv).
        target = load_target(self.config.spec)
        apk_args = ("--target-apk", target.broker_apk) if target.broker_apk else ()
        specs: list[RunSpec] = []
        total = len(worker_ids)
        for i, agent_id in enumerate(worker_ids, start=1):
            logger.info("swarm %s: acquiring device %d/%d (booting + provisioning)…",
                        swarm_id, i, total)
            started = self._clock()
            contract = self._acquire(target.device_spec, *apk_args)
            acquired.append(contract.serial)
            logger.info("swarm %s: %s ← %s (%.0fs)",
                        swarm_id, agent_id, contract.serial, self._clock() - started)
            agent_log_dir = log_dir / agent_id
            contract_path = agent_runner.write_contract(contract, agent_log_dir / f"{agent_id}.device")
            specs.append(
                RunSpec(
                    argv=build_run_argv(config=self.config, task=self.config.worker_task),
                    env=build_run_env(
                        config=self.config,
                        swarm_id=swarm_id,
                        agent_id=agent_id,
                        role=ROLE_WORKER,
                        log_dir=agent_log_dir,
                        device_contract=contract_path,
                        worker_ids=worker_ids,
                    ),
                    console_path=agent_log_dir / CONSOLE_FILENAME,
                )
            )
        return specs

    def _start_watch_views(self, log_dir: Path) -> ViewHandle | None:
        """Surface the two ways to watch the swarm (05c/05d) and, by default, auto-start the
        webview (05d). The `tail -f` of the per-worker console files is always printed — it is the
        guaranteed-live view (ANSI-free, per model turn). The rich browser transcript over the
        live-updating `.eval` logs is auto-started unless `--no-view`: on, the webview server is
        launched and its URL printed (torn down in `run()`'s `finally`); off, the manual command is
        printed instead (the 05c behaviour). Returns the server handle, or None when not started."""
        logger.info("swarm: watch (live tail): tail -f %s/*/%s", log_dir, CONSOLE_FILENAME)
        if not self.config.view:
            logger.info("swarm: watch (webview):   inspect view --log-dir %s --recursive --port %d",
                        log_dir, self.config.view_port)
            return None
        handle = self._view_launcher(log_dir, self.config.view_port)
        logger.info("swarm: webview → http://localhost:%d  (--no-view to skip; server log: %s)",
                    self.config.view_port, log_dir / VIEW_LOG_FILENAME)
        return handle

    def _stop_view(self, view_handle: ViewHandle | None) -> None:
        """Stop the auto-started webview server (05d). Best-effort: a failure is logged, never
        raised — it must not mask the run error or block device release (like `_save_board`)."""
        if view_handle is None:
            return
        try:
            if view_handle.poll() is None:
                view_handle.terminate()
        except Exception as e:  # noqa: BLE001 — stopping the webview is best-effort
            logger.warning("swarm: could not stop the inspect view server: %s", e)

    def _post_done(self, board: Board, verdict: Verdict) -> None:
        """Post the reserved `done` verdict as the arbiter. Posting through `Board` directly (not
        the worker tool) is what makes `done` legitimate here — the host-side arbiter is the only
        writer permitted it, and workers watching the board see it and stop (termination layer a)."""
        board.post(
            author=ROLE_ARBITER,
            subject=f"done: {verdict.value}",
            content=verdict.reason,
            type=TYPE_DONE,
        )

    def _shutdown(self, handles: list[RunHandle], *, cooperative: bool) -> None:
        """Wind down every run. When `cooperative` (the arbiter posted `done`), first honour
        termination layer (a): give runs `grace` to notice `done` and exit on their own — SIGTERM
        this instant would defeat the worker's "stop when `done` appears, then write your verdict"
        step. Then layer (c): terminate any survivor, allow a second grace, and hard-kill whatever
        is still alive. On a failure teardown (`done` never posted) the cooperative wait is
        skipped — nothing told the runs to stop, so tear them down straight away. Idempotent.

        Every kill is a **process-group** signal (`terminate_group`/`kill_group`), not a signal to
        the lone `inspect` parent (05c): a detached worker leads its own group, so this reaps its
        grandchildren (adb, frida, docker, the emulator bridge) too — no orphans survive Ctrl-C or
        an over-cap fail-fast."""
        if handles:
            logger.info("swarm: tearing down %d worker(s)", len(handles))
        if cooperative:
            self._await_exit(handles, self.config.grace)
        alive = [h for h in handles if h.poll() is None]
        if alive:
            logger.info("swarm: %d worker(s) still alive after grace — terminating", len(alive))
        for h in alive:
            h.terminate_group()
        self._await_exit(alive, self.config.grace)
        for h in alive:
            if h.poll() is None:
                h.kill_group()

    def _await_exit(self, handles: list[RunHandle], timeout: float) -> None:
        """Wait up to `timeout` seconds (shared across the batch) for still-running handles to
        exit. A handle that doesn't exit in time (its `wait` times out) is simply left for the
        caller's next escalation step."""
        deadline = self._clock() + timeout
        for h in handles:
            if h.poll() is None:
                try:
                    h.wait(timeout=max(0.0, deadline - self._clock()))
                except Exception:  # noqa: BLE001 — a timeout (or a fake's raise) just means move on
                    pass

    def _save_board(self, board: Board, log_dir: Path) -> None:
        """Copy the board dir into `log_dir/messageboard/` so the swarm artifact = transcripts +
        the conversation, one folder. Never fatal: a save failure is logged, not raised (it must
        not mask the real run error or block device release)."""
        dest = log_dir / "messageboard"
        try:
            if dest.exists():
                shutil.rmtree(dest)
            if board.path.exists():
                shutil.copytree(board.path, dest)
        except Exception as e:  # noqa: BLE001 — collation is best-effort
            logger.warning("swarm: could not save board into %s: %s", dest, e)

    def _release_all(self, acquired: list[str]) -> None:
        """Guaranteed device release: free every acquired serial. `release` never raises, so one
        stuck release can't strand the others; the broker also reclaims on its own shutdown."""
        for serial in acquired:
            logger.info("swarm: releasing device %s", serial)
            self._release(serial)
