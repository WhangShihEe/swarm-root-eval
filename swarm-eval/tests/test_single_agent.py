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
YAML = "configs/evals/healthhub.yaml"
# The device spec + APK the healthhub eval config resolves to (what the launcher hands the broker).
YAML_DEVICE = "configs/devices/pixel.yaml"
YAML_APK = "apks/healthhub/base.apk"


class FakeHandle:
    def __init__(self, code: int = 0):
        self._code = code

    def wait(self, timeout=None) -> int:
        return self._code


class FakeBroker:
    """Records each acquire (device spec + any forwarded env-up args) and every released serial;
    hands out one fixed contract."""

    def __init__(self):
        self.acquired: list[tuple] = []
        self.released: list[str] = []

    def acquire(self, spec: str, *extra: str) -> Contract:
        self.acquired.append((spec, *extra))
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
    # acquire → the eval config's provisioning device spec + the app's APK via --target-apk;
    # release → the leased serial, exactly once
    assert broker.acquired == [(YAML_DEVICE, "--target-apk", YAML_APK)]
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


# ---- yaml-config ticket 02: launching from an eval config ----------------------------------

EVAL_YAML = "configs/evals/rasp_dummy.yaml"


class FakeApkBroker:
    """Records the full acquire argv (spec + any forwarded env-up args like --target-apk)."""

    def __init__(self):
        self.acquired: list[tuple] = []
        self.released: list[str] = []

    def acquire(self, spec: str, *extra: str) -> Contract:
        self.acquired.append((spec, *extra))
        return CONTRACT

    def release(self, serial: str) -> None:
        self.released.append(serial)


def test_run_single_from_eval_config_acquires_device_and_installs_apk(tmp_path):
    # An eval config splits the APK out of the device file, so the launcher hands the broker the
    # provisioning-only DEVICE spec plus the app's APK via --target-apk. The worker's `-T spec=`
    # stays the eval config itself (the in-task load_target resolves it back).
    broker = FakeApkBroker()
    specs: list[RunSpec] = []
    cli.run_single(
        _config(tmp_path, spec=EVAL_YAML),
        acquire=broker.acquire, release=broker.release,
        runner=lambda s: specs.append(s) or FakeHandle(0),
    )
    assert broker.acquired == [
        ("configs/devices/pixel.yaml", "--target-apk", "apks/rasp_dummy/rasp_dummy.apk")
    ]
    assert f"spec={EVAL_YAML}" in specs[0].argv


# ---- yaml-config ticket 03: run knobs from the eval config + CLI override -------------------

def test_build_config_takes_run_knobs_from_the_eval_config():
    # With no CLI run-flags, the eval config's model + limits drive the run (replicable from file).
    cfg = cli.build_config(cli.parse_args([EVAL_YAML]))
    assert cfg.model == "anthropic/claude-sonnet-4-5-20250929"  # configs/evals/rasp_dummy.yaml
    assert cfg.time_limit == 1800


def test_cli_flags_override_the_eval_config_values():
    # A CLI flag wins over the eval config value for that run; an unset flag leaves the config value.
    cfg = cli.build_config(cli.parse_args([EVAL_YAML, "--model", "anthropic/x", "--time-limit", "600"]))
    assert cfg.model == "anthropic/x"      # CLI overrides the config's model
    assert cfg.time_limit == 600           # CLI overrides the config's time_limit


def test_eval_config_without_run_knobs_falls_back_to_built_in_defaults(tmp_path):
    # An eval config that sets no run knobs → the launcher's built-in defaults stand.
    from swarm_eval.agent_runner import DEFAULT_MODEL, DEFAULT_TIME_LIMIT

    ev = tmp_path / "bare.yaml"
    ev.write_text("app: rasp_dummy\ndevice: pixel\nworkers: dynamic\n", encoding="utf-8")
    cfg = cli.build_config(cli.parse_args([str(ev)]))
    assert cfg.model == DEFAULT_MODEL
    assert cfg.time_limit == DEFAULT_TIME_LIMIT


def test_run_single_forwards_eval_config_device_overrides_to_the_broker(tmp_path):
    # AC3 wiring: an eval config's writable_system/headless overrides ride through acquire as the
    # env-up flags that win over the device spec (eval > device), after --target-apk. Custom app-
    # less device/worker files keep the fixture self-contained; the app is the real rasp app file.
    (tmp_path / "role.yaml").write_text("role: r\nnotes: n\n", encoding="utf-8")
    (tmp_path / "dev.yaml").write_text("name: d\nsystem_image: img\n", encoding="utf-8")
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: configs/apps/rasp_dummy.yaml\n"
        f"device: {tmp_path / 'dev.yaml'}\n"
        f"workers:\n  - role: {tmp_path / 'role.yaml'}\n    count: 1\n"
        "writable_system: false\n"
        "headless: false\n",
        encoding="utf-8",
    )
    broker = FakeApkBroker()
    cli.run_single(
        _config(tmp_path, spec=str(ev)),
        acquire=broker.acquire, release=broker.release,
        runner=lambda s: FakeHandle(0),
    )
    (spec, *extra) = broker.acquired[0]
    assert extra == ["--target-apk", "apks/rasp_dummy/rasp_dummy.apk", "--frida-only", "--window"]
