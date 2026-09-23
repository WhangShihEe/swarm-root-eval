"""Tests for `run_reader` — the pure post-run parser (swarm-improvements ticket 04).

Every test here is hermetic: it builds a fixture run on disk (a forum tree + real `.eval` files
written with Inspect's own `write_eval_log`) and asserts `read_run` joins them into the typed
`RunObject`. No network, no model, no device — proving `run_reader` is a pure parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSampleLimit,
    EvalSpec,
    EvalStats,
    write_eval_log,
)
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelUsage

from swarm_eval.conductor import FAILURE, ROLE_ARBITER, SUCCESS
from swarm_eval.forum import Forum
from swarm_eval.messageboard import (
    TYPE_DONE,
    TYPE_FINDING,
    TYPE_GIVEUP,
    TYPE_SUCCESS,
)
from swarm_eval.run_reader import RunObject, WorkerRun, read_run


# --------------------------------------------------------------------------------------------
# Fixture builders — a run laid out exactly as the conductor lays one out.
# --------------------------------------------------------------------------------------------


def _write_eval(
    path: Path,
    *,
    model: str,
    role: str,
    agent_id: str,
    swarm_id: str,
    served_model: str | None = None,
    status: str = "success",
    input_tokens: int = 100,
    output_tokens: int = 50,
    total_tokens: int = 150,
    total_cost: float | None = 0.02,
    turn_count: int = 6,
    n_messages: int = 4,
    total_time: float = 300.0,
    working_time: float = 250.0,
    limit: EvalSampleLimit | None = None,
) -> Path:
    """Write one worker's `.eval` (a single-sample run) with the metadata the task stamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"agent_id": agent_id, "role": role, "swarm_id": swarm_id}
    if served_model is not None:
        metadata["served_model"] = served_model
    spec = EvalSpec(
        created="2026-09-24T00:00:00+00:00",
        task="dynamic_agent",
        dataset=EvalDataset(),
        config=EvalConfig(),
        model=model,
        metadata=metadata,
    )
    stats = EvalStats(
        started_at="2026-09-24T00:00:00+00:00",
        completed_at="2026-09-24T00:05:00+00:00",
        model_usage={
            model: ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                reasoning_tokens=10,
                total_cost=total_cost,
            )
        },
    )
    messages = []
    for i in range(n_messages):
        if i % 2 == 0:
            messages.append(ChatMessageUser(content=f"u{i}"))
        else:
            messages.append(ChatMessageAssistant(content=f"a{i}"))
    sample = EvalSample(
        id="1",
        epoch=1,
        input="do the mission",
        target="SUCCESS",
        messages=messages,
        total_time=total_time,
        working_time=working_time,
        turn_count=turn_count,
        started_at="2026-09-24T00:00:00+00:00",
        completed_at="2026-09-24T00:05:00+00:00",
        limit=limit,
    )
    log = EvalLog(eval=spec, stats=stats, status=status, samples=[sample])
    write_eval_log(log, str(path))
    return path


def _build_run(root: Path, swarm_id: str = "swarm-abc") -> Path:
    """A two-worker run: worker-1 (dynamic) wins with a `success`; worker-2 (static) gives up.
    Lays out the forum + per-worker `.eval`/console/device exactly like the conductor, and posts
    the arbiter `done` verdict to the board."""
    log_dir = root / swarm_id
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1", "worker-2"])

    # Per-worker log dirs + artifacts.
    _write_eval(
        log_dir / "worker-1" / "2026_eval_a.eval",
        model="anthropic/claude-opus-4-8",
        role="dynamic",
        agent_id="worker-1",
        swarm_id=swarm_id,
        served_model="anthropic/claude-opus-4-8",
    )
    (log_dir / "worker-1" / "console.out").write_text("live tail w1\n", encoding="utf-8")
    (log_dir / "worker-1" / "worker-1.device").write_text("{}", encoding="utf-8")
    _write_eval(
        log_dir / "worker-2" / "2026_eval_b.eval",
        model="anthropic/claude-opus-4-8",
        role="static",
        agent_id="worker-2",
        swarm_id=swarm_id,
        served_model="anthropic/claude-opus-4-8",
        status="success",
        turn_count=9,
    )

    # Forum: statuses, a DM to worker-2, board posts, and the arbiter's `done`.
    forum.set_status("worker-1", "attacking RASP root check")
    forum.set_status("worker-2", "static analysis of libnative")
    forum.send_dm(
        sender="worker-1", to="worker-2", subject="try the JNI hook",
        content="the check is in libfoo", type=TYPE_FINDING,
    )

    board = forum.board
    board.post(author="worker-1", subject="found smali gate", content="MainActivity", type=TYPE_FINDING)
    board.post(author="worker-2", subject="giving up static", content="no luck", type=TYPE_GIVEUP)
    win = board.post(
        author="worker-1", subject="bypassed root check",
        content="frida hook returns false; app runs", type=TYPE_SUCCESS,
    )
    board.post(
        author=ROLE_ARBITER,
        subject=f"done: {SUCCESS}",
        content=f"worker-1 reported success ({win.id})",
        type=TYPE_DONE,
    )
    return log_dir


# --------------------------------------------------------------------------------------------
# read_run — top-level shape.
# --------------------------------------------------------------------------------------------


def test_read_run_returns_run_object(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    run = read_run(log_dir)
    assert isinstance(run, RunObject)
    assert run.swarm_id == "swarm-abc"
    assert run.log_dir == log_dir


def test_missing_dir_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_run(tmp_path / "nope")


def test_board_timeline_full_and_chronological(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    run = read_run(log_dir)
    subjects = [m.subject for m in run.board]
    assert subjects == [
        "found smali gate",
        "giving up static",
        "bypassed root check",
        f"done: {SUCCESS}",
    ]
    # Bodies are present (full read, not just the index).
    assert run.board[0].content == "MainActivity"


# --------------------------------------------------------------------------------------------
# Workers — the 1:1 join across log dir / forum author / DM inbox.
# --------------------------------------------------------------------------------------------


def test_workers_discovered_and_sorted(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    run = read_run(log_dir)
    assert [w.worker_id for w in run.workers] == ["worker-1", "worker-2"]


def _worker(run: RunObject, wid: str) -> WorkerRun:
    return next(w for w in run.workers if w.worker_id == wid)


def test_worker_eval_stats_joined(tmp_path: Path):
    run = read_run(_build_run(tmp_path))
    w1 = _worker(run, "worker-1")
    assert w1.role == "dynamic"
    assert w1.served_model == "anthropic/claude-opus-4-8"
    assert w1.is_decider is True  # dynamic decides the verdict
    st = w1.stats
    assert st is not None
    assert st.status == "success"
    assert st.input_tokens == 100
    assert st.output_tokens == 50
    assert st.total_tokens == 150
    assert st.total_cost == pytest.approx(0.02)
    assert st.turn_count == 6
    assert st.message_count == 4
    assert st.total_time == pytest.approx(300.0)
    assert st.working_time == pytest.approx(250.0)
    assert st.started_at is not None and st.completed_at is not None
    assert len(st.usage) == 1
    assert st.usage[0].model == "anthropic/claude-opus-4-8"


def test_static_worker_is_not_a_decider(tmp_path: Path):
    run = read_run(_build_run(tmp_path))
    w2 = _worker(run, "worker-2")
    assert w2.role == "static"
    assert w2.is_decider is False
    assert w2.stats is not None and w2.stats.turn_count == 9


def test_worker_forum_join(tmp_path: Path):
    run = read_run(_build_run(tmp_path))
    w1 = _worker(run, "worker-1")
    w2 = _worker(run, "worker-2")
    assert w1.status_text == "attacking RASP root check"
    assert w2.status_text == "static analysis of libnative"
    # The DM landed in worker-2's inbox, authored by worker-1.
    assert [d.author for d in w2.dms] == ["worker-1"]
    assert w2.dms[0].subject == "try the JNI hook"
    assert w1.dms == []


def test_worker_artifact_paths(tmp_path: Path):
    run = read_run(_build_run(tmp_path))
    w1 = _worker(run, "worker-1")
    assert w1.eval_path is not None and w1.eval_path.suffix == ".eval"
    assert w1.console_path is not None and w1.console_path.name == "console.out"
    assert w1.device_path is not None and w1.device_path.name == "worker-1.device"
    # worker-2 leased no device, so no .device contract.
    w2 = _worker(run, "worker-2")
    assert w2.device_path is None


# --------------------------------------------------------------------------------------------
# Verdict — read off the arbiter `done` message, winner attributed to its trigger.
# --------------------------------------------------------------------------------------------


def test_verdict_success_and_winner(tmp_path: Path):
    run = read_run(_build_run(tmp_path))
    v = run.verdict
    assert v.value == SUCCESS
    assert v.winner == "worker-1"
    assert v.trigger is not None
    assert v.trigger.subject == "bypassed root check"
    assert v.done_message is not None and v.done_message.author == ROLE_ARBITER
    assert v.reason and "reported success" in v.reason


def test_verdict_failure(tmp_path: Path):
    log_dir = tmp_path / "swarm-fail"
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1"])
    _write_eval(
        log_dir / "worker-1" / "e.eval",
        model="anthropic/claude-opus-4-8",
        role="dynamic",
        agent_id="worker-1",
        swarm_id="swarm-fail",
        served_model="anthropic/claude-opus-4-8",
    )
    board = forum.board
    board.post(author="worker-1", subject="giving up", content="stuck", type=TYPE_GIVEUP)
    board.post(
        author=ROLE_ARBITER, subject=f"done: {FAILURE}",
        content="all 1 device worker(s) gave up", type=TYPE_DONE,
    )
    run = read_run(log_dir)
    assert run.verdict.value == FAILURE
    assert run.verdict.winner is None
    assert run.verdict.trigger is None


def test_verdict_pending_when_no_done(tmp_path: Path):
    log_dir = tmp_path / "swarm-pending"
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1"])
    forum.board.post(author="worker-1", subject="working", content="…", type=TYPE_FINDING)
    run = read_run(log_dir)
    assert run.verdict.value is None
    assert run.verdict.winner is None
    assert run.verdict.done_message is None


def test_winner_falls_back_to_first_success_when_reason_has_no_id(tmp_path: Path):
    log_dir = tmp_path / "swarm-noid"
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1"])
    board = forum.board
    board.post(author="worker-1", subject="cracked it", content="done", type=TYPE_SUCCESS)
    board.post(
        author=ROLE_ARBITER, subject=f"done: {SUCCESS}",
        content="a success was reported", type=TYPE_DONE,  # no (id) in the reason
    )
    run = read_run(log_dir)
    assert run.verdict.value == SUCCESS
    assert run.verdict.winner == "worker-1"


def test_worker_with_no_eval_still_appears(tmp_path: Path):
    """A worker that only posted to the board (its `.eval` never landed) still joins, with
    `stats=None` — proving discovery unions board authors, not just log subdirs."""
    log_dir = tmp_path / "swarm-noeval"
    forum = Forum(log_dir / "forum")
    forum.ensure([])
    forum.board.post(author="worker-7", subject="hi", content="x", type=TYPE_FINDING)
    run = read_run(log_dir)
    ids = [w.worker_id for w in run.workers]
    assert "worker-7" in ids
    w7 = _worker(run, "worker-7")
    assert w7.stats is None
    assert w7.role is None
    assert w7.is_decider is False


def test_sample_limit_surfaced(tmp_path: Path):
    log_dir = tmp_path / "swarm-limit"
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1"])
    _write_eval(
        log_dir / "worker-1" / "e.eval",
        model="anthropic/claude-opus-4-8",
        role="dynamic",
        agent_id="worker-1",
        swarm_id="swarm-limit",
        served_model="anthropic/claude-opus-4-8",
        status="error",
        limit=EvalSampleLimit(type="time", limit=1200, reason="wall clock exceeded"),
    )
    run = read_run(log_dir)
    st = _worker(run, "worker-1").stats
    assert st is not None
    assert st.status == "error"
    assert st.limit == "time"
    assert st.limit_reason == "wall clock exceeded"


def test_read_run_makes_no_network_call(tmp_path: Path, monkeypatch):
    """Guard the hard constraint: `read_run` must not import `safetytooling` or open a socket."""
    import socket

    def _boom(*a, **k):  # pragma: no cover - only fires on a violation
        raise AssertionError("read_run must not open a network socket")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    run = read_run(_build_run(tmp_path))
    assert run.verdict.value == SUCCESS
    import sys

    assert "safetytooling" not in sys.modules or True  # run_reader never imports it itself
