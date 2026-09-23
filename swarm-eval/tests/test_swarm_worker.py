"""Ticket 03 — the dynamic agent's swarm-worker mode. A contract is ALWAYS injected (the launcher
leases the device); the swarm SIGNAL is the presence of the board coordinates (`SWARM_ID`), which
add the shared-board tools + a collaboration prompt on top. A single run (a contract, no board
env) gets the bare mission. The agent never acquires or releases — the launcher owns the lease.
Hermetic: no broker, no docker — `sandbox()` is faked and the contract is a tmp file."""

import types

import pytest

import dynamic_agent as da
from swarm_eval.agent_runner import ENV_DEVICE_CONTRACT
from swarm_eval.broker_client import Contract
from swarm_eval.conductor import (
    ENV_AGENT_ID,
    ENV_FORUM_DIR,
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
    # keep every test starting from single mode unless it opts into the forum coordinates
    for var in (ENV_DEVICE_CONTRACT, ENV_SWARM_ID, ENV_AGENT_ID, ENV_ROLE, ENV_WORKER_IDS,
                ENV_FORUM_DIR):
        monkeypatch.delenv(var, raising=False)


# ---- swarm signal --------------------------------------------------------------------------

def test_swarm_mode_is_off_by_default_and_on_with_the_board_coordinates(monkeypatch):
    # the signal is SWARM_ID (the board coordinates), NOT DEVICE_CONTRACT (always set now)
    assert da.swarm_mode() is False
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, "/some/path.contract")
    assert da.swarm_mode() is False  # a contract alone is a single run, not a swarm
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")
    assert da.swarm_mode() is True


# ---- setup solver reads the injected contract without acquiring (both modes) ----------------

@pytest.mark.asyncio
async def test_inject_device_swarm_reads_injected_contract_without_acquiring(monkeypatch, tmp_path):
    path = tmp_path / "worker-1.device"
    path.write_text(CONTRACT_LINE + "\n")
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(path))
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")  # swarm worker
    sbx = FakeSandbox()
    monkeypatch.setattr(da, "sandbox", lambda: sbx)

    state = _state()
    await da.inject_device()(state, generate=None)

    assert state.metadata["device"]["serial"] == "emulator-5554"
    assert "DEVICE_ADB_PORT=5555" in sbx.files[da.CONTRACT_PATH]
    assert "adb connect host.docker.internal:5555" in sbx.files[da.CONNECT_SCRIPT]
    assert ["chmod", "+x", da.CONNECT_SCRIPT] in sbx.execs


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

def test_task_single_has_no_swarm_metadata():
    t = da.dynamic_agent()
    assert t.metadata == {}
    # single prompt is the bare mission — no collaboration protocol wrapper
    assert "Collaboration protocol" not in t.dataset[0].input


def test_task_swarm_mode_wraps_prompt_and_stamps_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(tmp_path / "worker-1.device"))
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")
    monkeypatch.setenv(ENV_AGENT_ID, "worker-1")
    monkeypatch.setenv(ENV_ROLE, "worker")
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2")
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))  # a swarm worker always has one

    t = da.dynamic_agent()
    assert t.metadata == {"swarm_id": "swarm-abc", "agent_id": "worker-1", "role": "worker"}
    prompt = t.dataset[0].input
    assert "Collaboration protocol" in prompt
    assert "worker-2" in prompt  # peer named


def test_task_swarm_mode_honours_spec_selected_target(monkeypatch, tmp_path):
    # The swarm path is APK-agnostic too (ticket 02): `-T spec=<yaml>` picks the target, and the
    # collaboration wrapper composes around whichever mission that yaml renders.
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(tmp_path / "worker-1.device"))
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")
    monkeypatch.setenv(ENV_AGENT_ID, "worker-1")
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1")
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))

    t = da.dynamic_agent(spec="configs/evals/healthhub.yaml")
    prompt = t.dataset[0].input
    assert "HealthHub" in prompt and "RASP Target" not in prompt
    assert "Collaboration protocol" in prompt  # still wrapped for the swarm
    assert "/root/base.apk" in t.dataset[0].files
