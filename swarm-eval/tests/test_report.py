"""Tests for `report.py` — the post-run report synthesis (swarm-improvements ticket 04).

The LLM call is always injected (`infer=…`) so these are hermetic: they exercise the collation,
prompt assembly, model-selection, and file-writing paths with no network and no `safetytooling`
build. The submodule backend itself is not exercised live here (left to the human, per the
ticket) — but its wiring (path resolution, injectability) is asserted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm_eval import report
from swarm_eval.conductor import FAILURE, ROLE_ARBITER, SUCCESS
from swarm_eval.forum import Forum
from swarm_eval.messageboard import TYPE_DONE, TYPE_FINDING, TYPE_GIVEUP, TYPE_SUCCESS
from swarm_eval.report import (
    DEFAULT_REPORT_MODEL,
    ENV_REPORT_MODEL,
    REPORT_FILENAME,
    build_prompt,
    render_facts,
    resolve_report_model,
    write_report,
)

# Reuse the run-reader fixture builder so both suites parse the same on-disk shape.
from test_run_reader import _build_run, _write_eval


class _RecordingInfer:
    """A fake synthesis backend: records the (model, system, user) it was called with and returns
    a canned completion. Stands in for the safety-tooling submodule call."""

    def __init__(self, completion: str = "The dynamic worker won by hooking the native check."):
        self.completion = completion
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, model: str, system: str, user: str) -> str:
        self.calls.append((model, system, user))
        return self.completion


# --------------------------------------------------------------------------------------------
# Model configuration — independent of the eval's --model.
# --------------------------------------------------------------------------------------------


def test_default_report_model_is_the_builtin(monkeypatch):
    monkeypatch.delenv(ENV_REPORT_MODEL, raising=False)
    assert resolve_report_model() == DEFAULT_REPORT_MODEL


def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv(ENV_REPORT_MODEL, "gpt-some-report-model")
    assert resolve_report_model() == "gpt-some-report-model"


def test_cli_overrides_env(monkeypatch):
    monkeypatch.setenv(ENV_REPORT_MODEL, "env-model")
    assert resolve_report_model("cli-model") == "cli-model"


def test_report_model_independent_of_eval_model(tmp_path, monkeypatch):
    """The report model does not come from the swept eval `--model` stamped in the `.eval`
    (`served_model`): the run below is served by `claude-opus-4-8`, but the report is synthesized
    with the independently-configured report model."""
    monkeypatch.delenv(ENV_REPORT_MODEL, raising=False)
    log_dir = _build_run(tmp_path)  # served model = anthropic/claude-opus-4-8
    infer = _RecordingInfer()
    write_report(log_dir, infer=infer)
    (used_model, _, _) = infer.calls[0]
    assert used_model == DEFAULT_REPORT_MODEL
    assert used_model != "anthropic/claude-opus-4-8"


# --------------------------------------------------------------------------------------------
# Prompt assembly — the model sees exactly what run_reader parsed.
# --------------------------------------------------------------------------------------------


def test_prompt_carries_verdict_workers_and_board(tmp_path):
    from swarm_eval.run_reader import read_run

    run = read_run(_build_run(tmp_path))
    system, user = build_prompt(run)
    assert "analyst" in system.lower()
    assert run.swarm_id in user
    assert SUCCESS in user
    assert "worker-1" in user and "worker-2" in user
    # board subjects + the DM thread show up
    assert "bypassed root check" in user
    assert "try the JNI hook" in user  # the DM content
    assert "dynamic" in user and "static" in user


def test_render_facts_has_token_totals(tmp_path):
    from swarm_eval.run_reader import read_run

    run = read_run(_build_run(tmp_path))
    facts = render_facts(run)
    assert "## Verdict" in facts
    assert "## Workers" in facts
    assert "## Message board" in facts
    assert "150" in facts  # worker total_tokens rendered


# --------------------------------------------------------------------------------------------
# write_report — writes logs/<swarm-id>/report.md, layering synthesis on the facts.
# --------------------------------------------------------------------------------------------


def test_write_report_writes_report_md(tmp_path):
    log_dir = _build_run(tmp_path)
    infer = _RecordingInfer("Insight: native hook was decisive.")
    path = write_report(log_dir, model="my-report-model", infer=infer)
    assert path == log_dir / REPORT_FILENAME
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "# Swarm run report" in text
    assert "swarm-abc" in text
    assert "Insight: native hook was decisive." in text  # the synthesized section
    assert "my-report-model" in text
    assert SUCCESS in text
    assert len(infer.calls) == 1


def test_write_report_uses_default_backend_by_default(tmp_path, monkeypatch):
    """When no `infer` is injected, `write_report` calls `safetytooling_infer`. We monkeypatch it
    so no subprocess/network runs, and assert it is the backend used."""
    calls = {}

    def fake_backend(model, system, user):
        calls["model"] = model
        return "backend insight"

    monkeypatch.setattr(report, "safetytooling_infer", fake_backend)
    log_dir = _build_run(tmp_path)
    path = write_report(log_dir, model="m")
    assert "backend insight" in path.read_text(encoding="utf-8")
    assert calls["model"] == "m"


def test_report_is_rerunnable_without_touching_the_run(tmp_path):
    """Re-running the report twice must not touch the forum/verdict — only rewrite report.md."""
    from swarm_eval.run_reader import read_run

    log_dir = _build_run(tmp_path)
    board_dir = log_dir / "forum" / "messageboard"

    def board_state():
        return sorted(p.name for p in board_dir.glob("*.json"))

    before = board_state()
    v_before = read_run(log_dir).verdict

    write_report(log_dir, infer=_RecordingInfer("first"))
    write_report(log_dir, infer=_RecordingInfer("second"))

    # The forum is untouched, the verdict identical, and report.md reflects the latest run.
    assert board_state() == before
    v_after = read_run(log_dir).verdict
    assert (v_after.value, v_after.winner) == (v_before.value, v_before.winner)
    assert "second" in (log_dir / REPORT_FILENAME).read_text(encoding="utf-8")


def test_failure_run_reports_incomplete_gracefully(tmp_path):
    log_dir = tmp_path / "swarm-f"
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1"])
    _write_eval(
        log_dir / "worker-1" / "e.eval",
        model="anthropic/claude-opus-4-8",
        role="dynamic",
        agent_id="worker-1",
        swarm_id="swarm-f",
        served_model="anthropic/claude-opus-4-8",
    )
    board = forum.board
    board.post(author="worker-1", subject="stuck", content="no", type=TYPE_GIVEUP)
    board.post(
        author=ROLE_ARBITER, subject=f"done: {FAILURE}",
        content="all 1 device worker(s) gave up", type=TYPE_DONE,
    )
    path = write_report(log_dir, infer=_RecordingInfer("nothing cracked"))
    text = path.read_text(encoding="utf-8")
    assert FAILURE in text


# --------------------------------------------------------------------------------------------
# CLI + backend wiring.
# --------------------------------------------------------------------------------------------


def test_cli_main_writes_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report, "safetytooling_infer", lambda m, s, u: "cli insight")
    log_dir = _build_run(tmp_path)
    rc = report.main([str(log_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "report.md" in out
    assert (log_dir / REPORT_FILENAME).exists()


def test_cli_main_missing_dir_errors(tmp_path):
    rc = report.main([str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_backend_points_at_submodule():
    """The default backend targets the vendored submodule at the repo root `safety-tooling/`, and
    the in-submodule runner script exists and imports only stdlib + safetytooling."""
    assert report.SAFETY_TOOLING_DIR.name == "safety-tooling"
    assert report._RUNNER.name == "_report_infer.py"
    assert report._RUNNER.exists()
    src = report._RUNNER.read_text(encoding="utf-8")
    assert "import safetytooling" not in src.split("async def", 1)[0]  # imported lazily, inside
    assert "import swarm_eval" not in src and "from swarm_eval" not in src  # never imports harness


def test_backend_raises_when_submodule_absent(tmp_path):
    with pytest.raises(RuntimeError, match="submodule not found"):
        report.safetytooling_infer("m", "s", "u", submodule=tmp_path / "nope")
