"""Ticket 04 — the control-plane wiring unique to the dynamic agent: the setup solver injects
the contract into the sandbox and stashes the serial; teardown releases it (even with nothing
stashed). Hermetic — `acquire`/`release`/`sandbox()` are faked, no broker, no docker."""

import types

import pytest

import dynamic_agent as da
from swarm_eval.broker_client import Contract

CONTRACT = Contract(serial="emulator-5554", console_port=5554, adb_port=5555, profile="writable-system")


class FakeSandbox:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.execs: list[list[str]] = []

    async def write_file(self, path, contents):
        self.files[path] = contents

    async def exec(self, cmd, *args, **kwargs):
        self.execs.append(cmd)


def _state():
    # The solver/cleanup only touch state.metadata and state.output.completion.
    return types.SimpleNamespace(
        metadata={},
        output=types.SimpleNamespace(completion=""),
    )


@pytest.mark.asyncio
async def test_acquire_device_injects_contract_and_stashes_serial(monkeypatch):
    sbx = FakeSandbox()
    monkeypatch.setattr(da, "acquire", lambda spec: CONTRACT)
    monkeypatch.setattr(da, "sandbox", lambda: sbx)

    state = _state()
    solve = da.acquire_device("devices/rootbeer.yaml")
    await solve(state, generate=None)

    assert state.metadata["device"]["serial"] == "emulator-5554"
    assert da.CONTRACT_PATH in sbx.files
    assert "DEVICE_ADB_PORT=5555" in sbx.files[da.CONTRACT_PATH]
    assert da.CONNECT_SCRIPT in sbx.files
    assert "adb connect host.docker.internal:5555" in sbx.files[da.CONNECT_SCRIPT]
    # the helper is made executable (the mission tells the agent to run it directly)
    assert ["chmod", "+x", da.CONNECT_SCRIPT] in sbx.execs


@pytest.mark.asyncio
async def test_release_device_releases_stashed_serial(monkeypatch):
    released = []
    monkeypatch.setattr(da, "release", lambda serial: released.append(serial))
    state = _state()
    state.metadata["device"] = {"serial": "emulator-5554"}
    await da.release_device(state)
    assert released == ["emulator-5554"]


@pytest.mark.asyncio
async def test_release_device_noop_when_nothing_acquired(monkeypatch):
    # If setup failed before a grant, teardown must not try to release a phantom device.
    released = []
    monkeypatch.setattr(da, "release", lambda serial: released.append(serial))
    await da.release_device(_state())
    assert released == []


@pytest.mark.asyncio
async def test_self_report_scorer_greens_on_success_matching_target():
    from inspect_ai.scorer import CORRECT, INCORRECT, Target

    score = da.self_report()
    state = _state()
    state.output.completion = "did it.\nROOTBEER_BYPASS: SUCCESS\nevidence: hooked isRooted()"
    s = await score(state, Target(["SUCCESS"]))
    assert s.value == CORRECT
    assert s.answer == "SUCCESS"


@pytest.mark.asyncio
async def test_self_report_scorer_reds_on_failure_and_on_missing_verdict():
    from inspect_ai.scorer import INCORRECT, Target

    score = da.self_report()
    fail = _state(); fail.output.completion = "ROOTBEER_BYPASS: FAILURE"
    none = _state(); none.output.completion = "I gave up without a verdict line"
    assert (await score(fail, Target(["SUCCESS"]))).value == INCORRECT
    assert (await score(none, Target(["SUCCESS"]))).value == INCORRECT
