"""Host-side client for the standing device broker (`bin/broker`), ticket 04.

The swarm-eval Inspect layer reaches the broker as an *external host process* — the harness
stays Inspect-free (spec: "Separation"). The Inspect **solver** acquires a device at sample
setup and releases it at teardown (guaranteed release: an LLM worker can't leak a scarce
device). This module is that thin client plus the rendering of the **connection contract**
into artifacts the sandbox can consume.

Testability: `bin/broker` is resolved from the repo root, but both the repo root and the
broker binary are overridable via env (`SWARM_REPO_ROOT`, `SWARM_BROKER_BIN`) so the client
can be exercised against a fake broker with no emulator — the same fake-injection idiom the
harness's bash suites use (POOL_ENV_UP).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# The unavoidable data-plane host: the emulator lives on the host, so a sandboxed adb must
# reach it via Docker's host loopback alias (see compose.yaml extra_hosts).
ADB_HOST = "host.docker.internal"

# The provisioned frida-server version (CONTEXT.md / harness). The sandbox's frida *client*
# is pinned to this; a client/server mismatch is a classic silent failure.
FRIDA_VERSION = "17.17.0"

# Default device-spec — the RASP dummy target (owned graded RASP/anti-tamper app).
DEFAULT_SPEC = "devices/rasp_dummy.yaml"


class BrokerError(RuntimeError):
    """A broker request failed, or its output could not be parsed into a contract."""


@dataclass(frozen=True)
class Contract:
    """The connection contract `bin/broker acquire` returns: how a client reaches a granted
    device, plus the REAL launch profile it came up under (spec-resolved or a broker override).
    """

    serial: str
    console_port: int
    adb_port: int
    profile: str

    def render_contract_line(self) -> str:
        """The broker's own one-line contract format (`serial=… console_port=… adb_port=…
        profile=…`). Symmetric with `parse_contract`: the launcher (05b) pre-acquires a device
        and writes this to the file it injects as `DEVICE_CONTRACT`, and the worker parses it
        back with `parse_contract`. Kept in the broker's format (not `render_env_file`'s
        `DEVICE_*` shape) so the same parser reads a real grant and a launcher-relayed one."""
        return (
            f"serial={self.serial} console_port={self.console_port} "
            f"adb_port={self.adb_port} profile={self.profile}"
        )

    def render_env_file(self) -> str:
        """A `source`-able shell fragment injected into the sandbox as the contract of record."""
        return (
            f"DEVICE_SERIAL={self.serial}\n"
            f"DEVICE_CONSOLE_PORT={self.console_port}\n"
            f"DEVICE_ADB_PORT={self.adb_port}\n"
            f"DEVICE_PROFILE={self.profile}\n"
            f"DEVICE_ADB_HOST={ADB_HOST}\n"
            f"FRIDA_VERSION={FRIDA_VERSION}\n"
        )

    def render_connect_script(self) -> str:
        """A convenience helper baked into the sandbox: connect adb to the host emulator and
        verify the frida client/server versions match before the agent leans on frida."""
        return f"""#!/usr/bin/env bash
# Connect this sandbox's adb to the broker-granted device on the host, and verify the frida
# client/server version match (pinned {FRIDA_VERSION}). Generated per-sample at setup.
set -euo pipefail
adb connect {ADB_HOST}:{self.adb_port}
adb wait-for-device
echo "== adb devices =="
adb devices

# Two-sided version match. (1) the client must be the pinned version:
client="$(frida --version)"
if [ "$client" != "{FRIDA_VERSION}" ]; then
  echo "frida client $client != pinned {FRIDA_VERSION}" >&2
  exit 1
fi
# (2) frida-ps -U forces a handshake with frida-server over the adb tunnel; frida ABORTS on a
# client/server version mismatch, so a clean listing is the server-side match assertion.
frida-ps -U >/dev/null
echo "frida client/server match OK ({FRIDA_VERSION})"
"""


_FIELDS = ("serial", "console_port", "adb_port", "profile")


def parse_contract(text: str) -> Contract:
    """Parse a broker contract line out of `text` (which may carry surrounding log noise).

    Expected line: `serial=… console_port=… adb_port=… profile=…`. Raises BrokerError if no
    well-formed contract line is present.
    """
    for line in text.splitlines():
        fields = dict(re.findall(r"(\w+)=(\S+)", line))
        if all(k in fields for k in _FIELDS):
            try:
                return Contract(
                    serial=fields["serial"],
                    console_port=int(fields["console_port"]),
                    adb_port=int(fields["adb_port"]),
                    profile=fields["profile"],
                )
            except ValueError:
                continue  # ports weren't integers — keep scanning
    raise BrokerError(f"no device contract found in broker output:\n{text}")


def repo_root() -> Path:
    """Repo root — override via SWARM_REPO_ROOT, else derived from this file's location
    (swarm-eval/src/swarm_eval/broker_client.py -> repo root is parents[3])."""
    override = os.environ.get("SWARM_REPO_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def broker_bin() -> Path:
    """Path to the `bin/broker` CLI — override via SWARM_BROKER_BIN (used by tests/fakes)."""
    override = os.environ.get("SWARM_BROKER_BIN")
    if override:
        return Path(override)
    return repo_root() / "bin" / "broker"


def _run_broker(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(broker_bin()), *args],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def acquire(spec: str = DEFAULT_SPEC, *extra: str, timeout: int = 900) -> Contract:
    """Acquire one device from the running broker and return its contract.

    `extra` forwards env-up args through the broker (e.g. a profile override). Raises
    BrokerError on a failed/timed-out grant so the solver's setup fails loudly (no phantom run
    against a device that never came up)."""
    try:
        cp = _run_broker(["acquire", "--spec", spec, *extra], timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise BrokerError(f"broker acquire timed out after {timeout}s") from e
    if cp.returncode != 0:
        raise BrokerError(f"broker acquire failed (rc={cp.returncode}):\n{cp.stderr}\n{cp.stdout}")
    return parse_contract(cp.stdout)


def release(serial: str, *, timeout: int = 120) -> None:
    """Release a device back to the broker. Never raises: this runs from cleanup/teardown, and
    a teardown crash would mask the real sample error and still leak the slot from the
    caller's view. Failures are swallowed (the broker also reclaims on its own shutdown)."""
    try:
        _run_broker(["release", "--serial", serial], timeout=timeout)
    except Exception:  # noqa: BLE001 — teardown must be total; broker owns ultimate reclamation
        pass
