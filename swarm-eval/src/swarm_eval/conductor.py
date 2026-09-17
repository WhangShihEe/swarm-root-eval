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
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .board_tools import ENV_AGENT_ID
from .broker_client import DEFAULT_SPEC, Contract
from .broker_client import acquire as broker_acquire
from .broker_client import release as broker_release
from .messageboard import (
    ENV_BOARD_DIR,
    ENV_SWARM_ID,
    TYPE_DONE,
    TYPE_GIVEUP,
    TYPE_SUCCESS,
    Board,
    board_dir,
)

logger = logging.getLogger(__name__)

# The launcher↔run injection contract: the env vars the Conductor sets per run, that each run's
# task/solver reads. `ENV_BOARD_DIR`/`ENV_SWARM_ID` (the board's own, from messageboard) and
# `ENV_AGENT_ID` (board_tools) are re-used; these are the swarm-launch additions.
ENV_ROLE = "ROLE"
ENV_DEVICE_CONTRACT = "DEVICE_CONTRACT"  # dynamic roles only: path to the pre-acquired contract
ENV_WORKER_IDS = "SWARM_WORKER_IDS"  # the worker roster, so a run knows its peers by name
ENV_INSPECT_LOG_DIR = "INSPECT_LOG_DIR"  # Inspect reads this; all runs share logs/<swarm-id>/

ROLE_WORKER = "worker"
ROLE_ARBITER = "arbiter"  # the author the host-side arbiter stamps on its `done` verdict

# Verdict values — the same tokens the per-run self-report oracle uses.
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"

# Defaults. The worker run is the ticket-04 dynamic agent (dual-mode: it reads DEVICE_CONTRACT
# when the Conductor injects one). Cap mirrors the broker's POOL_CAP (the broker still enforces
# the hard cap; this is the launcher's fail-fast courtesy). Model is the served provider model
# the sandbox's keyless CC proxies to — a sweep is this one flag (spec S2).
DEFAULT_WORKER_TASK = "dynamic_agent.py"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
DEFAULT_CAP = 3
# Per-run wall-clock cap (seconds), so termination layer (b) — "no run loops forever" — holds
# by default, not only when an operator remembers the flag. Generous for a real human-in-the-loop
# RASP-target attempt yet under the launcher `budget` so a run can't outlive the swarm.
DEFAULT_TIME_LIMIT = 1800


class SwarmError(RuntimeError):
    """A swarm run could not be set up (e.g. more workers than the device cap)."""


def swarm_eval_dir() -> Path:
    """The `swarm-eval/` project dir — cwd for the launched `inspect eval` subprocesses (the
    task files live there). Derived from this module's location: src/swarm_eval/conductor.py."""
    return Path(__file__).resolve().parents[2]


def mint_swarm_id() -> str:
    """A fresh, sortable, human-legible swarm id: `swarm-<utc>-<shortid>`. The stamp orders
    swarm dirs chronologically under `ls`; the shortid keeps two same-second runs distinct."""
    now = datetime.now(timezone.utc)
    return f"swarm-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


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
    board_root: Path = field(default_factory=lambda: swarm_eval_dir() / "board")
    log_root: Path = field(default_factory=lambda: swarm_eval_dir() / "logs")


@dataclass(frozen=True)
class RunSpec:
    """A single `inspect eval` subprocess to launch: its argv and the env vars injected on top
    of the inherited environment (the runner merges `os.environ` under these)."""

    agent_id: str
    role: str
    argv: list[str]
    env: dict[str, str]


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


class RunHandle(Protocol):
    """The slice of `subprocess.Popen` the Conductor drives — so tests inject a fake with no
    real process."""

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Runner = Callable[[RunSpec], RunHandle]


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
    """The env injected into one run (merged over the inherited environment by the runner). Only
    the swarm-launch vars — kept minimal so a test can assert the injection exactly."""
    env = {
        ENV_BOARD_DIR: str(config.board_root),
        ENV_SWARM_ID: swarm_id,
        ENV_AGENT_ID: agent_id,
        ENV_ROLE: role,
        ENV_INSPECT_LOG_DIR: str(log_dir),
    }
    if device_contract is not None:
        env[ENV_DEVICE_CONTRACT] = str(device_contract)
    if worker_ids:
        env[ENV_WORKER_IDS] = ",".join(worker_ids)
    return env


def build_run_argv(*, config: SwarmConfig, task: str) -> list[str]:
    """The `inspect eval` argv for one run. Per-run limits (layer b) ride as CLI flags; the log
    dir rides as `INSPECT_LOG_DIR` in the env, not a flag."""
    argv = ["inspect", "eval", task, "--model", config.model]
    if config.time_limit is not None:
        argv += ["--time-limit", str(config.time_limit)]
    if config.message_limit is not None:
        argv += ["--message-limit", str(config.message_limit)]
    return argv


def subprocess_runner(spec: RunSpec) -> subprocess.Popen:
    """Default runner: launch the run as a real `inspect eval` subprocess in `swarm-eval/`, with
    the injected env layered over the inherited one."""
    env = {**os.environ, **spec.env}
    return subprocess.Popen(spec.argv, cwd=str(swarm_eval_dir()), env=env)


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


class Conductor:
    """Runs one swarm. Inject `runner`/`acquire`/`release`/`clock`/`sleep` to exercise the whole
    orchestration hermetically (no real subprocess, broker, or wall-clock)."""

    def __init__(
        self,
        config: SwarmConfig,
        *,
        runner: Runner = subprocess_runner,
        acquire: Callable[[str], Contract] = broker_acquire,
        release: Callable[[str], None] = broker_release,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._runner = runner
        self._acquire = acquire
        self._release = release
        self._clock = clock
        self._sleep = sleep

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
        done_posted = False  # did the arbiter announce `done`? gates the cooperative-stop window
        logger.info("swarm %s: %d worker(s), board=%s", swarm_id, cfg.workers, board.path)
        try:
            # board up → devices acquired (all, before any launch) → runs launched.
            specs = self._acquire_and_plan(swarm_id, log_dir, worker_ids, acquired)
            # Append each handle as it is spawned (not a comprehension): if a later launch raises,
            # the already-spawned runs are still in `handles` for the `finally` to tear down — no
            # orphaned subprocess.
            for spec in specs:
                handles.append(self._runner(spec))
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
            # A failure at any step still releases devices and saves what exists.
            self._shutdown(handles, cooperative=done_posted)
            self._save_board(board, log_dir)
            self._release_all(acquired)

    def _acquire_and_plan(
        self, swarm_id: str, log_dir: Path, worker_ids: list[str], acquired: list[str]
    ) -> list[RunSpec]:
        """Pre-acquire one device per worker (the dynamic role) and build each run's spec. A
        contract is written to `log_dir/<agent-id>.device` and injected as `DEVICE_CONTRACT`; the
        serial is recorded in `acquired` *before* the next acquire, so a mid-way failure still
        releases every device already granted (the caller's `finally`)."""
        specs: list[RunSpec] = []
        for agent_id in worker_ids:
            contract = self._acquire(self.config.spec)
            acquired.append(contract.serial)
            contract_path = log_dir / f"{agent_id}.device"
            contract_path.write_text(contract.render_contract_line() + "\n", encoding="utf-8")
            specs.append(
                RunSpec(
                    agent_id=agent_id,
                    role=ROLE_WORKER,
                    argv=build_run_argv(config=self.config, task=self.config.worker_task),
                    env=build_run_env(
                        config=self.config,
                        swarm_id=swarm_id,
                        agent_id=agent_id,
                        role=ROLE_WORKER,
                        log_dir=log_dir,
                        device_contract=contract_path,
                        worker_ids=worker_ids,
                    ),
                )
            )
        return specs

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
        skipped — nothing told the runs to stop, so tear them down straight away. Idempotent."""
        if cooperative:
            self._await_exit(handles, self.config.grace)
        alive = [h for h in handles if h.poll() is None]
        for h in alive:
            h.terminate()
        self._await_exit(alive, self.config.grace)
        for h in alive:
            if h.poll() is None:
                h.kill()

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
