"""Ticket 05a — the standalone demo entrypoint. Hermetic checks of the parts that don't need a
live bridged run: env resolution (defaults + distinct AGENT_IDs) and the host-side scorer that
greens when this run actually posted to the board. The two-run live proof is run by hand."""

import pytest

import board_agent as ba
from swarm_eval.board_tools import BOARD_MCP_NAME
from swarm_eval.messageboard import Board, board_dir


def _fake_state():
    """A stand-in TaskState — the demo scorer only reads the board (via env), not the state."""
    return type("S", (), {"metadata": {}, "output": type("O", (), {"completion": ""})()})()


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BOARD_DIR", raising=False)
    monkeypatch.delenv("SWARM_ID", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.setattr(ba, "DEFAULT_BOARD_DIR", str(tmp_path))
    return tmp_path


def test_resolve_env_fills_defaults(clean_env):
    import os

    board_dir_v, swarm_id, agent_id = ba.resolve_env()
    assert board_dir_v == str(clean_env)
    assert swarm_id == ba.DEFAULT_SWARM_ID
    assert agent_id  # a generated, non-empty id
    # persisted into the environment so the host-side board tools resolve the same board
    assert os.environ["BOARD_DIR"] == str(clean_env)
    assert os.environ["AGENT_ID"] == agent_id


def test_resolve_env_respects_explicit_agent_id(clean_env, monkeypatch):
    monkeypatch.setenv("AGENT_ID", "worker-7")
    _, _, agent_id = ba.resolve_env()
    assert agent_id == "worker-7"


def test_generated_agent_ids_are_distinct_across_runs(clean_env, monkeypatch):
    _, _, first = ba.resolve_env()
    monkeypatch.delenv("AGENT_ID", raising=False)
    _, _, second = ba.resolve_env()
    assert first != second


async def test_scorer_greens_when_this_run_posted(clean_env, monkeypatch):
    monkeypatch.setenv("BOARD_DIR", str(clean_env))
    monkeypatch.setenv("SWARM_ID", "demo")
    monkeypatch.setenv("AGENT_ID", "worker-1")
    from inspect_ai.scorer import CORRECT, Target

    Board(board_dir(clean_env, "demo")).post(author="worker-1", subject="hi", content="c")
    score = ba.posted_to_board()
    assert (await score(_fake_state(), Target(["posted"]))).value == CORRECT


async def test_scorer_reds_when_this_run_never_posted(clean_env, monkeypatch):
    monkeypatch.setenv("BOARD_DIR", str(clean_env))
    monkeypatch.setenv("SWARM_ID", "demo")
    monkeypatch.setenv("AGENT_ID", "worker-1")
    from inspect_ai.scorer import INCORRECT, Target

    # someone else posted, but not this run
    Board(board_dir(clean_env, "demo")).post(author="worker-2", subject="hi", content="c")
    score = ba.posted_to_board()
    assert (await score(_fake_state(), Target(["posted"]))).value == INCORRECT


def test_task_wires_the_board_tools_and_scorer(clean_env):
    t = ba.board_agent()
    assert t.scorer is not None
    # the demo prompt names the board tools so the agent knows to use them
    prompt = t.dataset[0].input
    assert BOARD_MCP_NAME in prompt or "post_message" in prompt
