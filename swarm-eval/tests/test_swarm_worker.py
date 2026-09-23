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
    ENV_ROSTER,
    ENV_SWARM_ID,
    ENV_WORKER_IDS,
    ROLE_COORDINATOR,
    ROLE_DYNAMIC,
    ROLE_STATIC,
)
from swarm_eval.served_model import ENV_SERVED_MODEL

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
                ENV_ROSTER, ENV_FORUM_DIR, ENV_SERVED_MODEL):
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


def test_swarm_prompt_nudges_post_and_read_before_duplicating():
    # ticket 02: the mission nudge — tell the agent to post findings/successes and to consult the
    # board before duplicating work, and that the unread board index is pushed into its turn.
    prompt = da.swarm_prompt("BASE", "worker-1", ["worker-1", "worker-2"])
    low = prompt.lower()
    assert "finding" in low and "success" in low       # post these
    assert "duplicat" in low                            # …before duplicating a peer's work
    # the board index (not just DMs) is auto-pushed each turn — the ticket-02 nudge names it so
    # the agent understands the injected index and reads it before starting work.
    assert "board index" in low


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
    monkeypatch.setenv(ENV_ROLE, ROLE_DYNAMIC)
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2")
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))  # a swarm worker always has one

    t = da.dynamic_agent()
    assert t.metadata == {"swarm_id": "swarm-abc", "agent_id": "worker-1", "role": ROLE_DYNAMIC}
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


# ---- swarm-improvements ticket 03: the device-less roles ------------------------------------

def _swarm_env(monkeypatch, tmp_path, *, role, agent_id, roster):
    monkeypatch.setenv(ENV_SWARM_ID, "swarm-abc")
    monkeypatch.setenv(ENV_AGENT_ID, agent_id)
    monkeypatch.setenv(ENV_ROLE, role)
    monkeypatch.setenv(ENV_WORKER_IDS, ",".join(roster))
    monkeypatch.setenv(ENV_ROSTER, ",".join(f"{a}:{r}" for a, r in roster.items()))
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))


def test_static_worker_task_is_device_less(monkeypatch, tmp_path):
    # A `static` worker gets NO device: no DEVICE_CONTRACT is injected, so the task has no device
    # setup solver and its mission carries the static-analysis brief, not the device manual.
    _swarm_env(monkeypatch, tmp_path, role=ROLE_STATIC, agent_id="worker-3",
               roster={"worker-1": "dynamic", "worker-3": "static"})
    t = da.dynamic_agent()
    assert t.setup is None  # no inject_device — nothing fails fast on the absent contract
    assert t.metadata["role"] == ROLE_STATIC
    mission = t.dataset[0].input
    assert "STATIC-ANALYSIS" in mission and "NO device" in mission
    assert "connect-device.sh" not in mission          # the device manual is absent
    assert "Collaboration protocol" in mission          # still a forum worker


def test_coordinator_worker_task_is_device_less_and_names_peers(monkeypatch, tmp_path):
    roster = {"worker-1": "dynamic", "worker-2": "static", "worker-3": "coordinator"}
    _swarm_env(monkeypatch, tmp_path, role=ROLE_COORDINATOR, agent_id="worker-3", roster=roster)
    t = da.dynamic_agent()
    assert t.setup is None
    assert t.metadata["role"] == ROLE_COORDINATOR
    mission = t.dataset[0].input
    # the injected SWARM_ROSTER is parsed into the coordinator's peer directory.
    assert "worker-1 (dynamic)" in mission and "worker-2 (static)" in mission
    assert "cannot post `done`" in mission


def test_dynamic_worker_task_keeps_the_device_setup(monkeypatch, tmp_path):
    # The `dynamic` role is unchanged: a contract is injected and the device setup solver runs.
    monkeypatch.setenv(ENV_DEVICE_CONTRACT, str(tmp_path / "worker-1.device"))
    _swarm_env(monkeypatch, tmp_path, role=ROLE_DYNAMIC, agent_id="worker-1",
               roster={"worker-1": "dynamic"})
    t = da.dynamic_agent()
    assert t.setup is not None  # inject_device runs for a device worker
    assert t.metadata["role"] == ROLE_DYNAMIC
    assert "connect-device.sh" in t.dataset[0].input  # the device manual is present


def test_parse_roster_decodes_id_role_pairs():
    assert da.parse_roster("worker-1:dynamic,worker-3:static") == {
        "worker-1": "dynamic", "worker-3": "static"
    }
    assert da.parse_roster("") == {}
    assert da.parse_roster("garbage") == {}  # no ':' → skipped, not a crash


def test_worker_role_defaults_to_dynamic(monkeypatch):
    monkeypatch.delenv(ENV_ROLE, raising=False)
    assert da.worker_role() == ROLE_DYNAMIC
