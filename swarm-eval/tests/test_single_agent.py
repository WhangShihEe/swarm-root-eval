"""Ticket 03 — the `single_agent` launcher: the device yaml is the required positional target,
args map onto SingleConfig, and `run_single` leases one device → injects its contract + launches
one `dynamic_agent` run (no board env) → releases the device in a `finally` (guaranteed even when
the run raises). Hermetic: `acquire`/`release`/`runner` are injected fakes — no broker, no
subprocess."""

from pathlib import Path

import pytest

import single_agent as cli
from swarm_eval.agent_runner import ENV_DEVICE_CONTRACT, ENV_INSPECT_LOG_DIR, RunSpec
from swarm_eval.broker_client import Contract, parse_contract

CONTRACT = Contract("emulator-5554", 5554, 5555, "writable-system")
YAML = "devices/healthhub.yaml"


class FakeHandle:
    def __init__(self, code: int = 0):
        self._code = code

    def wait(self, timeout=None) -> int:
        return self._code


class FakeBroker:
    """Records the acquire spec and every released serial; hands out one fixed contract."""

    def __init__(self):
        self.acquired: list[str] = []
        self.released: list[str] = []

    def acquire(self, spec: str) -> Contract:
        self.acquired.append(spec)
        return CONTRACT

    def release(self, serial: str) -> None:
        self.released.append(serial)


def _config(tmp_path: Path, **kw) -> cli.SingleConfig:
    base = dict(spec=YAML, log_root=tmp_path / "logs")
    base.update(kw)
    return cli.SingleConfig(**base)


# ---- CLI arg parsing -----------------------------------------------------------------------

def test_spec_is_the_required_positional_target():
    assert cli.parse_args([YAML]).spec == YAML
    with pytest.raises(SystemExit):  # required — no yaml is a parse error, not a silent default
        cli.parse_args([])


def test_build_config_maps_flags_and_keeps_default_log_root():
    cfg = cli.build_config(cli.parse_args([YAML, "--model", "anthropic/x", "--time-limit", "600",
                                           "--message-limit", "40"]))
    assert cfg.spec == YAML
    assert cfg.model == "anthropic/x"
    assert cfg.time_limit == 600
    assert cfg.message_limit == 40
    assert cfg.log_root.name == "logs"  # default under swarm-eval/


def test_build_config_forwards_explicit_log_dir(tmp_path):
    cfg = cli.build_config(cli.parse_args([YAML, "--log-dir", str(tmp_path / "l")]))
    assert cfg.log_root == tmp_path / "l"


# ---- run_single: lease → launch → release --------------------------------------------------

def test_run_single_leases_launches_then_releases(tmp_path):
    broker = FakeBroker()
    specs: list[RunSpec] = []

    def runner(spec: RunSpec) -> FakeHandle:
        specs.append(spec)
        return FakeHandle(code=0)

    rc = cli.run_single(_config(tmp_path), acquire=broker.acquire, release=broker.release, runner=runner)

    assert rc == 0
    # acquire → the target yaml is the broker spec; release → the leased serial, exactly once
    assert broker.acquired == [YAML]
    assert broker.released == ["emulator-5554"]
    # the one launched run: `-T spec=<yaml>` selects the target, DEVICE_CONTRACT points at a
    # written, parseable contract file, and there is NO board env (single mode).
    assert len(specs) == 1
    spec = specs[0]
    assert "-T" in spec.argv and f"spec={YAML}" in spec.argv
    contract_file = Path(spec.env[ENV_DEVICE_CONTRACT])
    assert parse_contract(contract_file.read_text()) == CONTRACT
    assert ENV_INSPECT_LOG_DIR in spec.env
    assert "SWARM_ID" not in spec.env and "AGENT_ID" not in spec.env


def test_run_single_returns_the_run_exit_code(tmp_path):
    broker = FakeBroker()
    rc = cli.run_single(
        _config(tmp_path), acquire=broker.acquire, release=broker.release,
        runner=lambda spec: FakeHandle(code=1),
    )
    assert rc == 1  # the eval's rc is passed through; the verdict lives in the Inspect log


def test_run_single_releases_the_device_even_when_the_run_raises(tmp_path):
    # Guaranteed release: a failed/crashed launch still frees the scarce broker slot.
    broker = FakeBroker()

    def boom(spec: RunSpec):
        raise RuntimeError("launch boom")

    with pytest.raises(RuntimeError):
        cli.run_single(_config(tmp_path), acquire=broker.acquire, release=broker.release, runner=boom)
    assert broker.released == ["emulator-5554"]


def test_main_wires_args_to_run_single_and_returns_its_code(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run_single(config, **kw):
        captured["config"] = config
        return 7

    monkeypatch.setattr(cli, "run_single", fake_run_single)
    assert cli.main([YAML, "--log-dir", str(tmp_path / "l")]) == 7
    assert captured["config"].spec == YAML
    assert captured["config"].log_root == tmp_path / "l"
