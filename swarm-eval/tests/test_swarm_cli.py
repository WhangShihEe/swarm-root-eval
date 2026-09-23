"""Ticket 05b/03 — the `swarm` launcher CLI: the device yaml is the required positional target
(apk-agnostic), args map onto SwarmConfig, and main() returns the right exit code per outcome
(0 success / 1 failure verdict / 2 setup error). Hermetic: the Conductor is faked, so nothing is
acquired or launched."""

from pathlib import Path

import pytest

import swarm as cli
from swarm_eval.conductor import SwarmError, SwarmResult, Verdict

YAML = "configs/evals/healthhub.yaml"


def test_spec_is_the_required_positional_target():
    # apk-agnostic (ticket 03): the yaml is passed positionally and drives both acquire + `-T spec=`
    config = cli.build_config(cli.parse_args([YAML]))
    assert config.spec == YAML
    # it is required — no yaml is a parse error, not a silent default
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_build_config_maps_flags_and_keeps_default_roots():
    args = cli.parse_args([YAML, "-n", "3", "--time-limit", "1200", "--budget", "2700", "--cap", "5"])
    config = cli.build_config(args)
    assert config.spec == YAML
    assert config.workers == 3
    assert config.time_limit == 1200
    assert config.budget == 2700.0
    assert config.cap == 5
    # unset --board-dir/--log-dir → the SwarmConfig defaults (under swarm-eval/) stand
    assert config.board_root.name == "board"
    assert config.log_root.name == "logs"


def test_build_config_forwards_explicit_dirs(tmp_path):
    args = cli.parse_args([YAML, "--board-dir", str(tmp_path / "b"), "--log-dir", str(tmp_path / "l")])
    config = cli.build_config(args)
    assert config.board_root == tmp_path / "b"
    assert config.log_root == tmp_path / "l"


def test_view_is_on_by_default(tmp_path):
    # 05d: the webview auto-starts unless opted out; the port defaults to DEFAULT_VIEW_PORT.
    config = cli.build_config(cli.parse_args([YAML]))
    assert config.view is True
    assert config.view_port == cli.DEFAULT_VIEW_PORT


def test_no_view_flag_disables_the_webview_and_view_port_sets_the_port():
    config = cli.build_config(cli.parse_args([YAML, "--no-view", "--view-port", "8123"]))
    assert config.view is False
    assert config.view_port == 8123


class _FakeConductor:
    def __init__(self, verdict: Verdict, raises: Exception | None = None):
        self._verdict = verdict
        self._raises = raises

    def __call__(self, config):  # stands in for the Conductor class
        self._config = config
        return self

    def run(self) -> SwarmResult:
        if self._raises is not None:
            raise self._raises
        return SwarmResult(
            swarm_id="swarm-test",
            log_dir=Path("/tmp/logs/swarm-test"),
            board_path=Path("/tmp/board/swarm-test"),
            verdict=self._verdict,
            worker_ids=["worker-1"],
        )


def test_main_returns_0_on_success_verdict(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Conductor", _FakeConductor(Verdict("SUCCESS", "worker-1 won")))
    assert cli.main([YAML, "-n", "1"]) == 0
    assert "SUCCESS" in capsys.readouterr().out


def test_main_returns_1_on_failure_verdict(monkeypatch):
    monkeypatch.setattr(cli, "Conductor", _FakeConductor(Verdict("FAILURE", "all gave up")))
    assert cli.main([YAML, "-n", "1"]) == 1


def test_main_returns_2_on_setup_error(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "Conductor", _FakeConductor(Verdict("FAILURE", ""), raises=SwarmError("over cap"))
    )
    assert cli.main([YAML, "-n", "9"]) == 2
    assert "over cap" in capsys.readouterr().err


# ---- yaml-config ticket 03: run knobs from the eval config + CLI override -------------------

EVAL_YAML = "configs/evals/rasp_dummy.yaml"


def test_build_config_takes_run_knobs_from_the_eval_config():
    # No CLI run-flags: the eval config's model, worker count, and caps/budget/limits drive the run.
    config = cli.build_config(cli.parse_args([EVAL_YAML]))
    assert config.model == "anthropic/claude-sonnet-4-5-20250929"
    assert config.workers == 1          # workers: [{role: dynamic, count: 1}]
    assert config.time_limit == 1800
    assert config.budget == 3600.0
    assert config.cap == 6


def test_cli_workers_and_model_override_the_eval_config():
    # --workers/--model still drive swarm sizing + the model sweep without editing the file.
    config = cli.build_config(cli.parse_args([EVAL_YAML, "--workers", "3", "--model", "anthropic/x"]))
    assert config.workers == 3          # CLI overrides the config's worker count
    assert config.model == "anthropic/x"
    # an unset flag leaves the config value
    assert config.time_limit == 1800


def test_eval_config_without_run_knobs_falls_back_to_built_in_defaults(tmp_path):
    # An eval config that sets no run knobs → the SwarmConfig built-in defaults stand.
    ev = tmp_path / "bare.yaml"
    ev.write_text("app: rasp_dummy\ndevice: pixel\nworkers: dynamic\n", encoding="utf-8")
    config = cli.build_config(cli.parse_args([str(ev)]))
    assert config.workers == 1
    assert config.model == cli.DEFAULT_MODEL
    assert config.budget == cli.DEFAULT_BUDGET
    assert config.cap == cli.DEFAULT_CAP
