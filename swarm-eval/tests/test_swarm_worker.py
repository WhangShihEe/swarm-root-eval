"""Ticket 05b — the dynamic agent's swarm-worker mode. When the Conductor injects
`DEVICE_CONTRACT` (a pre-acquired contract) the run reads it instead of acquiring, does NOT
release at teardown (the launcher owns the lease), and gets the shared-board tools + a
collaboration prompt. Standalone (ticket 04) behaviour is unchanged. Hermetic: no broker, no
docker — `acquire`/`sandbox()` are faked and the contract is a tmp file."""

import types

import pytest

import dynamic_agent as da
from swarm_eval.broker_client import Contract
from swarm_eval.conductor import (
    ENV_AGENT_ID,
    ENV_DEVICE_CONTRACT,
    ENV_ROLE,
    ENV_SWARM_ID,
    ENV_WORKER_IDS,
)

CONTRACT = Contract("emulator-5554", 5554, 5555, "writable-system")
CONTRACT_LINE = CONTRACT.render_contract_line()


class FakeSandbox:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.execs: list[list[str]] = []

    async def write_file(self, path, contents):
        self.files[path] = contents

    async def exec(self, cmd, *args, **kwargs):
        self.execs.append(cmd)


def _state():
    return types.SimpleNamespace(metadata={}, output=types.SimpleNamespace(completion=""))


@pytest.fixture(autouse=True)
def _clean_swarm_env(monkeypatch):
    # keep every test starting from standalone mode unless it opts in
    for var in (ENV_DEVICE_CONTRACT, ENV_SWARM_ID, ENV_AGENT_ID, ENV_ROLE, ENV_WORKER_IDS):
        monkeypatch.delenv(var, raising=False)


# ---- mode detection & contract sourcing ----------------------------------------------------

def test_swarm_mode_is_off_by_default_and_on_with_device_contract(monkeypatch, tmp_path):
    assert da.swarm_mode() is False
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(tmp_path / "worker-1.device"))
    assert da.swarm_mode() is True


def test_obtain_contract_standalone_acquires_and_owns_the_lease(monkeypatch):
    monkeypatch.setattr(da, "acquire", lambda spec: CONTRACT)
    state = _state()
    got = da._obtain_contract("devices/rootbeer.yaml", state)
    assert got == CONTRACT
    assert state.metadata["device_owner"] == da.OWNER_SOLVER


def test_obtain_contract_swarm_reads_injected_file_and_does_not_acquire(monkeypatch, tmp_path):
    path = tmp_path / "worker-1.device"
    path.write_text(CONTRACT_LINE + "\n")
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(path))

    def _boom(spec):
        raise AssertionError("swarm mode must not acquire — the launcher already did")

    monkeypatch.setattr(da, "acquire", _boom)
    state = _state()
    got = da._obtain_contract("devices/rootbeer.yaml", state)
    assert got == CONTRACT
    assert state.metadata["device_owner"] == da.OWNER_LAUNCHER


# ---- setup solver injects the contract in both modes ---------------------------------------

@pytest.mark.asyncio
async def test_acquire_device_swarm_injects_contract_without_acquiring(monkeypatch, tmp_path):
    path = tmp_path / "worker-1.device"
    path.write_text(CONTRACT_LINE + "\n")
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(path))
    monkeypatch.setattr(da, "acquire", lambda spec: (_ for _ in ()).throw(AssertionError("no acquire")))
    sbx = FakeSandbox()
    monkeypatch.setattr(da, "sandbox", lambda: sbx)

    state = _state()
    await da.acquire_device("devices/rootbeer.yaml")(state, generate=None)

    assert state.metadata["device"]["serial"] == "emulator-5554"
    assert "DEVICE_ADB_PORT=5555" in sbx.files[da.CONTRACT_PATH]
    assert "adb connect host.docker.internal:5555" in sbx.files[da.CONNECT_SCRIPT]
    assert ["chmod", "+x", da.CONNECT_SCRIPT] in sbx.execs


# ---- teardown release honours the lease owner ----------------------------------------------

@pytest.mark.asyncio
async def test_release_device_skips_when_the_launcher_owns_the_lease(monkeypatch):
    released = []
    monkeypatch.setattr(da, "release", lambda serial: released.append(serial))
    state = _state()
    state.metadata["device"] = {"serial": "emulator-5554"}
    state.metadata["device_owner"] = da.OWNER_LAUNCHER
    await da.release_device(state)
    assert released == []  # the Conductor releases it, not this run — no double-free


@pytest.mark.asyncio
async def test_release_device_releases_when_this_run_owns_the_lease(monkeypatch):
    released = []
    monkeypatch.setattr(da, "release", lambda serial: released.append(serial))
    state = _state()
    state.metadata["device"] = {"serial": "emulator-5554"}
    state.metadata["device_owner"] = da.OWNER_SOLVER
    await da.release_device(state)
    assert released == ["emulator-5554"]


# ---- collaboration prompt ------------------------------------------------------------------

def test_swarm_prompt_names_identity_peers_board_and_protocol():
    prompt = da.swarm_prompt("BASE-MISSION-TEXT", "worker-2", ["worker-1", "worker-2"])
    assert "worker-2" in prompt
    assert "worker-1" in prompt  # the peer roster
    assert "BASE-MISSION-TEXT" in prompt  # composed around the mission, not replacing it
    assert "board" in prompt  # the MCP server / tools are named
    # ties into the arbiter rubric + cooperative-stop termination
    assert "done" in prompt and "success" in prompt and "giveup" in prompt


# ---- task wiring per mode ------------------------------------------------------------------

def test_task_standalone_has_no_swarm_metadata():
    t = da.dynamic_agent()
    assert t.metadata == {}
    # standalone prompt is the bare mission — no collaboration protocol wrapper
    assert "Collaboration protocol" not in t.dataset[0].input


def test_task_swarm_mode_wraps_prompt_and_stamps_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(tmp_path / "worker-1.device"))
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")
    monkeypatch.setenv(ENV_AGENT_ID, "worker-1")
    monkeypatch.setenv(ENV_ROLE, "worker")
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2")

    t = da.dynamic_agent()
    assert t.metadata == {"swarm_id": "swarm-abc", "agent_id": "worker-1", "role": "worker"}
    prompt = t.dataset[0].input
    assert "Collaboration protocol" in prompt
    assert "worker-2" in prompt  # peer named
