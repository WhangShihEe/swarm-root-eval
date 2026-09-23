"""Read a finished swarm run off disk into one typed run object (swarm-improvements ticket 04).

This is the **pure parser** half of the post-run tooling: given a swarm's log dir
(`logs/<swarm-id>/`), it joins — per `worker-<i>`, the id that is 1:1 across the log dir, the
forum author, and the DM inbox — the three artifacts a finished run leaves behind:

  * the **forum** (`forum/messageboard/` broadcast board + `forum/dms/<worker>/` inboxes +
    each worker's `status.txt`), read through the existing `Forum`/`Board` substrate;
  * each worker's **`.eval`** stats, read through Inspect's own `inspect_ai.log` reader
    (token usage, message/turn count, wall/working time, start/finish, error/limit, status,
    and the run's stamped `role`/`served_model`/`agent_id` metadata);
  * the **arbiter verdict** (the reserved `done` message the conductor posts to the board),
    plus the winning worker and the `success` message that triggered a win.

HARD CONSTRAINTS (ticket 04): this module calls **no model**, imports **no `safetytooling`**, and
is a pure parser. `report.py` layers its LLM synthesis on top; ticket 05's UI consumes the same
`RunObject` unchanged. Everything here is deterministic disk I/O over one finished run, so it is
provable in isolation with a fixture run — no network, no device, no Inspect task execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from inspect_ai.log import read_eval_log, read_eval_log_sample_summaries

from .conductor import (
    DEVICE_ROLES,
    FAILURE,
    ROLE_ARBITER,
    SUCCESS,
    worker_agent_id,
)
from .forum import Forum
from .messageboard import (
    TYPE_DONE,
    TYPE_SUCCESS,
    Message,
)

# The per-worker artifacts the conductor writes beside each worker's `.eval` (see
# `conductor._acquire_and_plan` / `CONSOLE_FILENAME`). Named here so the reader and the conductor
# cannot drift on the filenames.
CONSOLE_FILENAME = "console.out"
FORUM_DIRNAME = "forum"

# The arbiter's `done` subject is `done: <VALUE>` and its reason for a win is
# `"<author> reported success (<id>)"` (conductor `_post_done` / `evaluate_board`). We parse the
# triggering message id out of the reason to attribute the winner precisely; if the format ever
# changes we fall back to the first `success` on the board, so attribution degrades, never breaks.
_TRIGGER_ID_RE = re.compile(r"\(([^()]+)\)\s*$")


# --------------------------------------------------------------------------------------------
# Typed return — a stable, dependency-free shape ticket 05's UI consumes unchanged.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    """One model's token accounting, mirroring Inspect's `ModelUsage` (the fields a report cares
    about). Summed across a run's models in `WorkerStats.total_*`."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_cache_write: int | None = None
    input_tokens_cache_read: int | None = None
    reasoning_tokens: int | None = None
    total_cost: float | None = None


@dataclass(frozen=True)
class WorkerStats:
    """One worker run's `.eval` stats — the numbers a report summarizes, joined from the log
    header (`status`, `stats`, stamped `metadata`) and its single sample's summary (counts, times,
    error/limit). `None`-valued fields mean the artifact did not record them (e.g. a run that
    crashed before completing a sample)."""

    status: str  # Inspect eval status: started | success | cancelled | error
    served_model: str | None
    usage: list[TokenUsage] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float | None = None
    message_count: int | None = None
    turn_count: int | None = None
    total_time: float | None = None
    working_time: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None  # header/sample error message, if the run errored
    limit: str | None = None  # sample limit that stopped the run (e.g. "time", "message"), if any
    limit_reason: str | None = None


@dataclass(frozen=True)
class WorkerRun:
    """Everything known about one `worker-<i>`, joined across the log dir, the forum, and the DM
    inbox by its single id. `stats` is `None` when no `.eval` was found (the worker never wrote
    one); `role`/`served_model` come from the `.eval` metadata and are `None` when unknown."""

    worker_id: str
    role: str | None
    served_model: str | None
    stats: WorkerStats | None
    dms: list[Message]  # DMs delivered *to* this worker (its inbox), oldest first
    status_text: str | None  # its current `status.txt` line, or None if it set none
    eval_path: Path | None
    console_path: Path | None
    device_path: Path | None
    is_decider: bool  # does this worker's role decide the verdict (a device role)?


@dataclass(frozen=True)
class RunVerdict:
    """The arbiter's outcome for the run, read from the board's reserved `done` message. `value`
    is `SUCCESS`/`FAILURE`, or `None` when the run left no verdict (incomplete — no `done` posted).
    `winner` is the worker whose `success` decided a win (`None` on a loss/pending); `trigger` is
    that `success` message when it can be located on the board."""

    value: str | None
    reason: str | None
    winner: str | None
    trigger: Message | None
    done_message: Message | None


@dataclass(frozen=True)
class RunObject:
    """One finished swarm run, joined into a single typed object: its id, its log dir, the full
    broadcast-board timeline, each worker (with `.eval` stats + DMs + status), and the verdict.
    This is the whole public contract of `run_reader` — `report.py` and ticket 05's UI build only
    on this."""

    swarm_id: str
    log_dir: Path
    board: list[Message]  # the full broadcast timeline, oldest first (includes the arbiter `done`)
    workers: list[WorkerRun]
    verdict: RunVerdict


# --------------------------------------------------------------------------------------------
# The reader.
# --------------------------------------------------------------------------------------------


def read_run(run_path: str | Path) -> RunObject:
    """Read the finished swarm run at `run_path` (a `logs/<swarm-id>/` dir) into one `RunObject`.

    Pure disk I/O: reads the forum via the `Forum`/`Board` substrate and each worker's `.eval` via
    Inspect's `inspect_ai.log` reader. Calls no model and imports no `safetytooling`. The swarm id
    is the log dir's own name (the conductor lays runs out as `log_root/<swarm-id>/`). Workers are
    discovered by unioning the ids seen across the log-dir subdirs, the forum board authors, and
    the DM inboxes, so a worker that produced only board posts (no `.eval`) — or only an `.eval`
    (no posts) — still appears. Raises `FileNotFoundError` if `run_path` is not a directory."""
    log_dir = Path(run_path)
    if not log_dir.is_dir():
        raise FileNotFoundError(f"run path is not a directory: {log_dir}")
    swarm_id = log_dir.name

    forum = Forum(log_dir / FORUM_DIRNAME)
    board = _read_board(forum)

    worker_ids = _discover_worker_ids(log_dir, forum, board)
    device_roles = set(DEVICE_ROLES)
    workers = [
        _read_worker(log_dir, forum, wid, device_roles) for wid in worker_ids
    ]

    verdict = _read_verdict(board, workers)
    return RunObject(
        swarm_id=swarm_id,
        log_dir=log_dir,
        board=board,
        workers=workers,
        verdict=verdict,
    )


def _read_board(forum: Forum) -> list[Message]:
    """The full broadcast timeline (bodies, oldest first). Empty when the run wrote no board."""
    board = forum.board
    if not board.path.is_dir():
        return []
    ids = [e["id"] for e in board.list()]
    return board.read(ids)


def _discover_worker_ids(log_dir: Path, forum: Forum, board: list[Message]) -> list[str]:
    """The run's worker ids, unioned across the three places a `worker-<i>` shows up: its own log
    subdir, its DM inbox, and its board authorship. Ordered numerically by the `worker-<i>` index
    (with any non-conforming id sorted last, lexically), so the roster reads worker-1, worker-2, …
    regardless of which artifact each id was first seen in. The arbiter author is excluded — it is
    the host rubric, not a worker."""
    ids: set[str] = set()

    for child in log_dir.iterdir():
        if child.is_dir() and child.name.startswith("worker-"):
            ids.add(child.name)

    dms_dir = forum.root / "dms"
    if dms_dir.is_dir():
        for child in dms_dir.iterdir():
            if child.is_dir():
                ids.add(child.name)

    for msg in board:
        if msg.author and msg.author != ROLE_ARBITER:
            ids.add(msg.author)

    return sorted(ids, key=_worker_sort_key)


def _worker_sort_key(worker_id: str) -> tuple[int, int, str]:
    """Sort `worker-<n>` numerically; anything else sorts after, lexically."""
    m = re.fullmatch(r"worker-(\d+)", worker_id)
    if m:
        return (0, int(m.group(1)), worker_id)
    return (1, 0, worker_id)


def _read_worker(
    log_dir: Path, forum: Forum, worker_id: str, device_roles: set[str]
) -> WorkerRun:
    """Join one worker's log-dir artifacts (`.eval`, `console.out`, `<id>.device`) with its forum
    presence (DM inbox + `status.txt`). `.eval` stats — and the stamped `role`/`served_model` — are
    read when an `.eval` is present, else left `None`. The `is_decider` flag is derived from the
    role (a device role decides the verdict) and stays `False` when the role is unknown."""
    worker_dir = log_dir / worker_id
    eval_path = _find_eval(worker_dir)
    role, stats = _read_role_and_stats(eval_path)
    served_model = stats.served_model if stats is not None else None

    console_path = worker_dir / CONSOLE_FILENAME
    device_path = worker_dir / f"{worker_id}.device"

    return WorkerRun(
        worker_id=worker_id,
        role=role,
        served_model=served_model,
        stats=stats,
        dms=forum.read_dms(worker_id) if (forum.root / "dms" / worker_id).is_dir() else [],
        status_text=_get_status(forum, worker_id),
        eval_path=eval_path,
        console_path=console_path if console_path.exists() else None,
        device_path=device_path if device_path.exists() else None,
        is_decider=(role in device_roles) if role is not None else False,
    )


def _get_status(forum: Forum, worker_id: str) -> str | None:
    status = forum.get_status(worker_id)
    return status.strip() if status is not None else None


def _find_eval(worker_dir: Path) -> Path | None:
    """The worker's `.eval` file, if any. A worker owns one run, but if several `.eval` files exist
    (a re-run), take the most recent by name — Inspect's `<ts>_<task>_<id>.eval` names sort
    chronologically, matching the board's id ordering."""
    if not worker_dir.is_dir():
        return None
    evals = sorted(worker_dir.glob("*.eval"))
    return evals[-1] if evals else None


def _read_role_and_stats(eval_path: Path | None) -> tuple[str | None, WorkerStats | None]:
    """Read one `.eval` into `(role, WorkerStats)` via Inspect's reader, or `(None, None)` when
    there is no `.eval`. The header (cheap, `header_only`) gives status/error/`stats`/stamped
    metadata (`role`/`served_model`); the sample *summary* (also cheap — no full transcript) gives
    message/turn counts, wall/working time, and any stop limit. The two are joined so the report
    never has to touch a raw transcript, and one header read backs both the role and the stats."""
    if eval_path is None:
        return None, None
    header = read_eval_log(str(eval_path), header_only=True)
    served_model = role = None
    if header.eval.metadata:
        served_model = header.eval.metadata.get("served_model")
        role = header.eval.metadata.get("role")

    usage: list[TokenUsage] = []
    in_tok = out_tok = tot_tok = 0
    total_cost: float | None = None
    model_usage = header.stats.model_usage if header.stats else None
    if model_usage:
        for model_id, mu in model_usage.items():
            usage.append(
                TokenUsage(
                    model=model_id,
                    input_tokens=mu.input_tokens or 0,
                    output_tokens=mu.output_tokens or 0,
                    total_tokens=mu.total_tokens or 0,
                    input_tokens_cache_write=mu.input_tokens_cache_write,
                    input_tokens_cache_read=mu.input_tokens_cache_read,
                    reasoning_tokens=mu.reasoning_tokens,
                    total_cost=mu.total_cost,
                )
            )
            in_tok += mu.input_tokens or 0
            out_tok += mu.output_tokens or 0
            tot_tok += mu.total_tokens or 0
            if mu.total_cost is not None:
                total_cost = (total_cost or 0.0) + mu.total_cost

    started_at = header.stats.started_at if header.stats else None
    completed_at = header.stats.completed_at if header.stats else None
    error = header.error.message if header.error else None

    message_count = turn_count = None
    total_time = working_time = None
    limit = limit_reason = None
    try:
        summaries = read_eval_log_sample_summaries(str(eval_path))
    except Exception:
        summaries = []
    if summaries:
        s = summaries[0]
        message_count = s.message_count
        turn_count = s.turn_count
        total_time = s.total_time
        working_time = s.working_time
        if s.started_at:
            started_at = s.started_at
        if s.completed_at:
            completed_at = s.completed_at
        if error is None and s.error is not None:
            error = s.error if isinstance(s.error, str) else str(s.error)
        # In a sample *summary* the limit is the bare type token (str); in a full sample it is an
        # `EvalSampleLimit`. Accept either so the reader works off summaries or full samples.
        if s.limit is not None:
            limit = s.limit if isinstance(s.limit, str) else s.limit.type
            if not isinstance(s.limit, str):
                limit_reason = s.limit.reason
        limit_reason = limit_reason or getattr(s, "limit_reason", None)

    stats = WorkerStats(
        status=header.status,
        served_model=served_model,
        usage=usage,
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=tot_tok,
        total_cost=total_cost,
        message_count=message_count,
        turn_count=turn_count,
        total_time=total_time,
        working_time=working_time,
        started_at=started_at,
        completed_at=completed_at,
        error=error,
        limit=limit,
        limit_reason=limit_reason,
    )
    return role, stats


def _read_verdict(board: list[Message], workers: list[WorkerRun]) -> RunVerdict:
    """Read the arbiter verdict off the board's reserved `done` message (the conductor posts
    exactly one at the end via `_post_done`). The verdict *value* comes from the `done` subject
    (`done: <VALUE>`) with the content as its reason. On a `SUCCESS` we attribute the winner: the
    `success` message named in the reason (`"<author> reported success (<id>)"`), or — if the
    reason format ever changes — the first `success` posted by a known worker. A run with no `done`
    yields a `None`-valued verdict (it never completed)."""
    done = _last(m for m in board if m.type == TYPE_DONE)
    if done is None:
        return RunVerdict(value=None, reason=None, winner=None, trigger=None, done_message=None)

    value = _parse_done_value(done.subject)
    reason = done.content or None

    winner = trigger = None
    if value == SUCCESS:
        trigger = _find_trigger(board, reason, workers)
        winner = trigger.author if trigger is not None else None

    return RunVerdict(
        value=value,
        reason=reason,
        winner=winner,
        trigger=trigger,
        done_message=done,
    )


def _parse_done_value(subject: str) -> str | None:
    """`done: SUCCESS` → `SUCCESS`. Tolerant of extra text; recognizes the two known tokens."""
    tail = subject.split(":", 1)[1].strip() if ":" in subject else subject.strip()
    upper = tail.upper()
    if SUCCESS in upper:
        return SUCCESS
    if FAILURE in upper:
        return FAILURE
    return tail or None


def _find_trigger(
    board: list[Message], reason: str | None, workers: list[WorkerRun]
) -> Message | None:
    """The `success` message that decided a win. Prefer the id embedded in the arbiter's reason
    (`"… (<id>)"`); fall back to the first `success` posted by a known worker (the rubric's
    first-credible-success semantics)."""
    by_id = {m.id: m for m in board}
    if reason:
        m = _TRIGGER_ID_RE.search(reason)
        if m and m.group(1) in by_id:
            return by_id[m.group(1)]
    worker_ids = {w.worker_id for w in workers}
    for msg in board:  # board is chronological
        if msg.type == TYPE_SUCCESS and msg.author in worker_ids:
            return msg
    return None


def _last(it):
    """The last item of an iterable, or None if empty."""
    out = None
    for x in it:
        out = x
    return out


# Re-exported so callers (report.py, ticket 05) can label worker ids without re-deriving the
# format from the conductor.
__all__ = [
    "TokenUsage",
    "WorkerStats",
    "WorkerRun",
    "RunVerdict",
    "RunObject",
    "read_run",
    "worker_agent_id",
]
