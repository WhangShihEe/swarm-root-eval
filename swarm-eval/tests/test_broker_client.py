"""Ticket 04 — host-side broker client (contract parsing, sandbox-injection rendering,
and acquire/release against a fake `bin/broker`). Hermetic: no real broker, no emulator.
The fake-broker pattern mirrors the harness's bash suites (POOL_ENV_UP fakes)."""

import os
import stat
from pathlib import Path

import pytest

from swarm_eval.broker_client import (
    Contract,
    BrokerError,
    parse_contract,
    acquire,
    release,
)

CONTRACT_LINE = "serial=emulator-5554 console_port=5554 adb_port=5555 profile=writable-system"


def test_parse_contract_happy():
    c = parse_contract(CONTRACT_LINE)
    assert c == Contract(
        serial="emulator-5554",
        console_port=5554,
        adb_port=5555,
        profile="writable-system",
    )


def test_parse_contract_ignores_surrounding_log_noise():
    # The broker prints the contract on stdout but a client may capture stray lines;
    # parse the contract line wherever it sits in a multi-line blob.
    blob = "broker: granted\n" + CONTRACT_LINE + "\nbroker: done\n"
    assert parse_contract(blob).serial == "emulator-5554"


@pytest.mark.parametrize("bad", ["", "no fields here", "serial=x console_port=nope adb_port=1 profile=p"])
def test_parse_contract_rejects_malformed(bad):
    with pytest.raises(BrokerError):
        parse_contract(bad)


def test_render_env_file_is_sourceable_shell():
    c = parse_contract(CONTRACT_LINE)
    env = c.render_env_file()
    assert "DEVICE_SERIAL=emulator-5554" in env
    assert "DEVICE_ADB_PORT=5555" in env
    assert "DEVICE_CONSOLE_PORT=5554" in env
    assert "DEVICE_PROFILE=writable-system" in env
    # host.docker.internal is the unavoidable data-plane host (emulator lives on the host).
    assert "DEVICE_ADB_HOST=host.docker.internal" in env


def test_render_connect_script_wires_adb_and_frida_check():
    c = parse_contract(CONTRACT_LINE)
    script = c.render_connect_script()
    assert "adb connect host.docker.internal:5555" in script
    assert "17.17.0" in script  # pinned frida version-match assertion


def test_render_contract_line_roundtrips_through_parse_contract():
    # 05b: the launcher relays a pre-acquired contract to a worker as a file; the worker parses
    # it back with the same `parse_contract` a real broker grant uses. Render → parse is identity.
    c = parse_contract(CONTRACT_LINE)
    assert parse_contract(c.render_contract_line()) == c


# ---- acquire/release against a fake broker -------------------------------------------------

def _write_fake_broker(dirpath: Path, body: str) -> Path:
    b = dirpath / "broker"
    b.write_text("#!/usr/bin/env bash\n" + body)
    b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return b


def test_acquire_parses_contract_from_fake_broker(tmp_path, monkeypatch):
    fake = _write_fake_broker(
        tmp_path,
        'echo "broker: acquire"\n' f'echo "{CONTRACT_LINE}"\n' "exit 0\n",
    )
    monkeypatch.setenv("SWARM_BROKER_BIN", str(fake))
    c = acquire(spec="configs/devices/pixel.yaml")
    assert c.serial == "emulator-5554"
    assert c.adb_port == 5555


def test_acquire_raises_on_broker_failure(tmp_path, monkeypatch):
    fake = _write_fake_broker(tmp_path, 'echo "broker: no capacity" >&2\nexit 1\n')
    monkeypatch.setenv("SWARM_BROKER_BIN", str(fake))
    with pytest.raises(BrokerError):
        acquire(spec="configs/devices/pixel.yaml")


def test_release_calls_broker_with_serial(tmp_path, monkeypatch):
    log = tmp_path / "release.log"
    fake = _write_fake_broker(tmp_path, f'echo "$@" >> "{log}"\nexit 0\n')
    monkeypatch.setenv("SWARM_BROKER_BIN", str(fake))
    release("emulator-5554")
    assert "release --serial emulator-5554" in log.read_text()


def test_release_never_raises(tmp_path, monkeypatch):
    # Guaranteed-release contract: cleanup must not throw even if the broker errors,
    # or a failed sample would mask the real error with a teardown crash.
    fake = _write_fake_broker(tmp_path, "exit 3\n")
    monkeypatch.setenv("SWARM_BROKER_BIN", str(fake))
    release("emulator-5554")  # must not raise
