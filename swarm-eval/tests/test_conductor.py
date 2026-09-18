"""Ticket 05b — the Conductor: env injection, the host-side arbiter rubric, and the full
orchestration (device budget with guaranteed release, termination, board collation). Hermetic —
the runner, broker, and clock are all injected fakes: no real subprocess, emulator, or wall-clock.
The board is the *real* 05a substrate over a tmp dir (the conductor's coordination is proven end
to end against it, not a mock)."""

from pathlib import Path

import pytest

from swarm_eval import conductor as C
from swarm_eval.agent_runner import ENV_DEVICE_CONTRACT
from swarm_eval.broker_client import BrokerError, Contract, parse_contract
from swarm_eval.conductor import (
    ENV_AGENT_ID,
    ENV_BOARD_DIR,
    ENV_INSPECT_LOG_DIR,
    ENV_ROLE,
    ENV_SWARM_ID,
    ENV_WORKER_IDS,
    ROLE_WORKER,
    Conductor,
    SwarmConfig,
    SwarmError,
    Verdict,
    arbitrate,
    build_run_argv,
    build_run_env,
    evaluate_board,
    mint_swarm_id,
    worker_agent_id,
)
from swarm_eval.messageboard import Board, board_dir


# ---- fakes ---------------------------------------------------------------------------------

class FakeClock:
    """Injected time: `sleep(dt)` advances the clock by dt (or a fixed step for dt==0), so a
    poll/budget loop is driven deterministically with no real waiting."""

    def __init__(self, step: float = 1.0) -> None:
        self.t = 0.0
        self.step = step
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.sleeps.append(dt)
        self.t += dt if dt else self.step


class FakeHandle:
    """A stand-in `RunHandle`. `stubborn=True` ignores `terminate` (never exits on its own) to
    exercise the hard-kill layer; otherwise `terminate` makes it exit cooperatively."""

    def __init__(self, stubborn: bool = False) -> None:
        self._code: int | None = None
        self.stubborn = stubborn
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._code

    def terminate(self) -> None:
        self.terminated = True
        if not self.stubborn:
            self._code = -15

    def kill(self) -> None:
        self.killed = True
        self._code = -9

    def wait(self, timeout: float | None = None) -> int:
        if self._code is None:  # a still-running (stubborn) run does not exit within the grace
            raise TimeoutError("still running")
        return self._code


class CooperativeHandle:
    """A run that notices `done` and exits cleanly the moment it is waited on (the layer-a
    cooperative-stop window) — used to prove the Conductor does NOT SIGTERM a run that self-exits
    within the grace."""

    def __init__(self) -> None:
        self._code: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._code

    def terminate(self) -> None:
        self.terminated = True
        self._code = -15

    def kill(self) -> None:
        self.killed = True
        self._code = -9

    def wait(self, timeout: float | None = None) -> int:
        self._code = 0  # saw `done`, wrote its verdict, exited within the grace window
        return 0


class ExplodingRunner:
    """A runner that launches fine until `fail_agent`, where it raises — to prove that runs
    spawned before a later launch failure are still torn down (not orphaned)."""

    def __init__(self, fail_agent: str) -> None:
        self.fail_agent = fail_agent
        self.handles: dict[str, FakeHandle] = {}

    def __call__(self, spec: C.RunSpec) -> FakeHandle:
        agent_id = spec.env[ENV_AGENT_ID]
        if agent_id == self.fail_agent:
            raise RuntimeError(f"launch of {agent_id} boom")
        h = FakeHandle()
        self.handles[agent_id] = h
        return h


class FakeBroker:
    """A fake broker: `acquire` hands out distinct serials; `fail_on` (1-based) raises on that
    acquire to test partial-release. `release` records every freed serial."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.n = 0
        self.fail_on = fail_on
        self.released: list[str] = []

    def acquire(self, spec: str) -> Contract:
        self.n += 1
        if self.fail_on is not None and self.n == self.fail_on:
            raise BrokerError(f"acquire #{self.n} boom")
        port = 5554 + 2 * (self.n - 1)
        return Contract(f"emulator-{port}", port, port + 1, "writable-system")

    def release(self, serial: str) -> None:
        self.released.append(serial)


def make_runner(outcomes: dict[str, str], *, stubborn: set[str] | None = None):
    """A runner that simulates each worker acting: on launch it posts `outcomes[agent_id]` (e.g.
    'success'/'giveup') to the shared board as that worker, then returns a handle. This is how a
    hermetic run() drives the arbiter — the board becomes decisive because 'workers' posted."""
    stubborn = stubborn or set()
    handles: list[FakeHandle] = []

    def runner(spec: C.RunSpec) -> FakeHandle:
        agent_id = spec.env[ENV_AGENT_ID]
        kind = outcomes.get(agent_id)
        if kind:
            b = Board(board_dir(spec.env[ENV_BOARD_DIR], spec.env[ENV_SWARM_ID]))
            b.post(author=agent_id, subject=f"{agent_id} {kind}", content="x", type=kind)
        h = FakeHandle(stubborn=agent_id in stubborn)
        handles.append(h)
        return h

    runner.handles = handles  # type: ignore[attr-defined]
    return runner


def cfg(tmp_path: Path, **kw) -> SwarmConfig:
    base = dict(
        board_root=tmp_path / "board",
        log_root=tmp_path / "logs",
        budget=5.0,
        poll_interval=2.0,
        grace=3.0,
    )
    base.update(kw)
    return SwarmConfig(**base)


def _run(config: SwarmConfig, broker: FakeBroker, runner, clock: FakeClock) -> C.SwarmResult:
    return Conductor(
        config,
        runner=runner,
        acquire=broker.acquire,
        release=broker.release,
        clock=clock,
        sleep=clock.sleep,
    ).run()


# ---- pure helpers --------------------------------------------------------------------------

def test_mint_swarm_id_is_prefixed_and_unique():
    a, b = mint_swarm_id(), mint_swarm_id()
    assert a.startswith("swarm-") and b.startswith("swarm-")
    assert a != b


def test_worker_agent_id_is_one_based():
    assert worker_agent_id(1) == "worker-1"
    assert worker_agent_id(3) == "worker-3"


def test_build_run_env_injects_the_full_contract(tmp_path):
    config = cfg(tmp_path)
    env = build_run_env(
        config=config,
        swarm_id="swarm-x",
        agent_id="worker-2",
        role=ROLE_WORKER,
        log_dir=tmp_path / "logs" / "swarm-x",
        device_contract=tmp_path / "worker-2.device",
        worker_ids=["worker-1", "worker-2"],
    )
    assert env[ENV_BOARD_DIR] == str(config.board_root)
    assert env[ENV_SWARM_ID] == "swarm-x"
    assert env[ENV_AGENT_ID] == "worker-2"
    assert env[ENV_ROLE] == ROLE_WORKER
    assert env[ENV_INSPECT_LOG_DIR] == str(tmp_path / "logs" / "swarm-x")
    assert env[ENV_DEVICE_CONTRACT] == str(tmp_path / "worker-2.device")
    assert env[ENV_WORKER_IDS] == "worker-1,worker-2"


def test_build_run_env_omits_device_contract_and_roster_when_absent(tmp_path):
    env = build_run_env(
        config=cfg(tmp_path),
        swarm_id="s",
        agent_id="a",
        role="arbiter",
        log_dir=tmp_path,
    )
    assert ENV_DEVICE_CONTRACT not in env
    assert ENV_WORKER_IDS not in env


def test_build_run_argv_defaults_carry_a_time_limit(tmp_path):
    # layer (b) "no run loops forever" must hold out of the box: the default config caps each run.
    argv = build_run_argv(config=cfg(tmp_path), task="dynamic_agent.py")
    assert "--time-limit" in argv and str(C.DEFAULT_TIME_LIMIT) in argv
    assert "--message-limit" not in argv  # message limit stays opt-in


def test_build_run_argv_selects_target_via_spec(tmp_path):
    # apk-agnostic refactor (ticket 02): the worker's target is the device yaml, passed as
    # `-T spec=<yaml>` so the spawned dynamic_agent stages the right APK(s) + mission.
    argv = build_run_argv(config=cfg(tmp_path, spec="devices/healthhub.yaml"), task="dynamic_agent.py")
    assert "-T" in argv and "spec=devices/healthhub.yaml" in argv
    # -T spec=... rides right after the task, before --model
    i = argv.index("-T")
    assert argv[i - 1] == "dynamic_agent.py" and argv[i + 1] == "spec=devices/healthhub.yaml"


def test_build_run_argv_omits_limits_when_explicitly_none(tmp_path):
    argv = build_run_argv(
        config=cfg(tmp_path, time_limit=None, message_limit=None), task="dynamic_agent.py"
    )
    assert argv == [
        "inspect", "eval", "dynamic_agent.py",
        "-T", f"spec={C.DEFAULT_SPEC}",
        "--model", C.DEFAULT_MODEL,
    ]


def test_build_run_argv_includes_both_limits_when_set(tmp_path):
    argv = build_run_argv(
        config=cfg(tmp_path, time_limit=1200, message_limit=40), task="dynamic_agent.py"
    )
    assert "--time-limit" in argv and "1200" in argv
    assert "--message-limit" in argv and "40" in argv


def test_evaluate_board_first_success_wins_over_a_giveup():
    entries = [
        {"id": "1", "type": "giveup", "author": "worker-1"},
        {"id": "2", "type": "success", "author": "worker-2"},
    ]
    v = evaluate_board(entries, ["worker-1", "worker-2"])
    assert v is not None and v.value == "SUCCESS"
    assert v.trigger["author"] == "worker-2"


def test_evaluate_board_all_giveup_is_failure():
    entries = [
        {"id": "1", "type": "giveup", "author": "worker-1"},
        {"id": "2", "type": "giveup", "author": "worker-2"},
    ]
    v = evaluate_board(entries, ["worker-1", "worker-2"])
    assert v is not None and v.value == "FAILURE"


def test_evaluate_board_partial_giveup_is_undecided():
    entries = [{"id": "1", "type": "giveup", "author": "worker-1"}]
    assert evaluate_board(entries, ["worker-1", "worker-2"]) is None


def test_evaluate_board_empty_is_undecided():
    assert evaluate_board([], ["worker-1"]) is None


def test_arbitrate_returns_success_immediately(tmp_path):
    board = Board(board_dir(tmp_path, "s"))
    board.post(author="worker-1", subject="win", content="x", type="success")
    clock = FakeClock()
    v = arbitrate(board, ["worker-1"], budget=5.0, poll_interval=2.0, clock=clock, sleep=clock.sleep)
    assert v.value == "SUCCESS"
    assert clock.sleeps == []  # decisive on the first pass — never slept


def test_arbitrate_times_out_to_failure(tmp_path):
    board = Board(board_dir(tmp_path, "s"))
    board.ensure()  # no messages ever posted
    clock = FakeClock()
    v = arbitrate(board, ["worker-1"], budget=5.0, poll_interval=2.0, clock=clock, sleep=clock.sleep)
    assert v.value == "FAILURE"
    assert "budget elapsed" in v.reason


# ---- full orchestration (hermetic run()) ---------------------------------------------------

def test_run_success_posts_done_and_releases_the_device(tmp_path):
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    runner = make_runner({"worker-1": "success"})
    result = _run(config, broker, runner, FakeClock())

    assert result.verdict.value == "SUCCESS"
    assert result.worker_ids == ["worker-1"]
    # the arbiter posted a reserved `done` message carrying the verdict
    done = [m for m in Board(result.board_path).list() if m["type"] == "done"]
    assert len(done) == 1 and "SUCCESS" in done[0]["subject"]
    # the one acquired device was released at teardown
    assert broker.released == ["emulator-5554"]


def test_run_all_giveup_is_a_failure_verdict(tmp_path):
    config = cfg(tmp_path, workers=2)
    broker = FakeBroker()
    runner = make_runner({"worker-1": "giveup", "worker-2": "giveup"})
    result = _run(config, broker, runner, FakeClock())

    assert result.verdict.value == "FAILURE"
    assert sorted(broker.released) == ["emulator-5554", "emulator-5556"]


def test_run_budget_timeout_is_failure_and_still_releases(tmp_path):
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    runner = make_runner({})  # the worker posts nothing → the arbiter times out
    result = _run(config, broker, runner, FakeClock())

    assert result.verdict.value == "FAILURE"
    assert "budget elapsed" in result.verdict.reason
    assert broker.released == ["emulator-5554"]


def test_run_over_cap_fails_fast_without_acquiring(tmp_path):
    config = cfg(tmp_path, workers=4, cap=3)
    broker = FakeBroker()
    with pytest.raises(SwarmError):
        _run(config, broker, make_runner({}), FakeClock())
    assert broker.n == 0  # fail-fast: nothing acquired
    assert broker.released == []


def test_run_releases_partial_devices_when_an_acquire_fails_midway(tmp_path):
    # 2 workers, the second acquire blows up. The first device was already granted — teardown
    # must still release it (guaranteed release), and no run should have launched.
    config = cfg(tmp_path, workers=2)
    broker = FakeBroker(fail_on=2)
    runner = make_runner({})
    with pytest.raises(BrokerError):
        _run(config, broker, runner, FakeClock())
    assert broker.released == ["emulator-5554"]
    assert runner.handles == []  # never got to launching


def test_run_writes_a_parseable_device_contract_per_worker(tmp_path):
    config = cfg(tmp_path, workers=2)
    broker = FakeBroker()
    seen: dict[str, str] = {}

    def runner(spec: C.RunSpec) -> FakeHandle:
        # capture the injected DEVICE_CONTRACT path so we can assert its content post-run
        agent_id = spec.env[ENV_AGENT_ID]
        seen[agent_id] = spec.env[ENV_DEVICE_CONTRACT]
        b = Board(board_dir(spec.env[ENV_BOARD_DIR], spec.env[ENV_SWARM_ID]))
        b.post(author=agent_id, subject="win", content="x", type="success")
        return FakeHandle()

    result = _run(config, broker, runner, FakeClock())
    assert set(seen) == {"worker-1", "worker-2"}
    for agent_id, path in seen.items():
        contract = parse_contract(Path(path).read_text())  # the worker parses it the same way
        assert contract.serial.startswith("emulator-")
    # and each contract file lives inside the swarm log dir (part of the saved artifact)
    assert all(str(result.log_dir) in p for p in seen.values())


def test_run_saves_the_board_into_the_log_dir(tmp_path):
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    result = _run(config, broker, make_runner({"worker-1": "success"}), FakeClock())
    saved = result.log_dir / "messageboard"
    assert saved.is_dir()
    # the collated copy holds the same messages as the live board (incl. the arbiter's `done`)
    live = {m["id"] for m in Board(result.board_path).list()}
    copied = {p.stem for p in saved.glob("*.json")}
    assert live and live == copied


def test_run_kills_a_straggler_that_ignores_terminate(tmp_path):
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    runner = make_runner({"worker-1": "success"}, stubborn={"worker-1"})
    _run(config, broker, runner, FakeClock())
    h = runner.handles[0]
    assert h.terminated and h.killed  # terminate ignored → escalated to kill (layer c)


def test_run_tears_down_already_spawned_runs_when_a_later_launch_fails(tmp_path):
    # Ordering guarantee: "a failure at any step still releases devices and saves what exists".
    # worker-1 is spawned, then worker-2's launch raises — worker-1 must not be orphaned.
    config = cfg(tmp_path, workers=2)
    broker = FakeBroker()
    runner = ExplodingRunner("worker-2")
    with pytest.raises(RuntimeError):
        _run(config, broker, runner, FakeClock())
    assert runner.handles["worker-1"].terminated  # spawned run torn down, not left running
    # both devices were acquired (all acquires happen before any launch) → both released
    assert sorted(broker.released) == ["emulator-5554", "emulator-5556"]


def test_run_lets_a_worker_exit_cooperatively_before_terminating(tmp_path):
    # Termination layer (a): after `done` is posted, a run that exits on its own within the grace
    # is never SIGTERM/SIGKILLed — the launcher gives the cooperative-stop window first.
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    coop = CooperativeHandle()

    def runner(spec: C.RunSpec) -> CooperativeHandle:
        Board(board_dir(spec.env[ENV_BOARD_DIR], spec.env[ENV_SWARM_ID])).post(
            author=spec.env[ENV_AGENT_ID], subject="win", content="x", type="success"
        )
        return coop

    result = _run(config, broker, runner, FakeClock())
    assert result.verdict.value == "SUCCESS"
    assert coop.poll() == 0  # exited cleanly on its own
    assert not coop.terminated and not coop.killed


def test_run_n1_uses_the_same_path_as_nge2(tmp_path):
    # N=1-is-single: one worker + the host-side arbiter over a one-participant board, no special
    # casing. The board ends with exactly the worker's post + the arbiter's `done`.
    config = cfg(tmp_path, workers=1)
    broker = FakeBroker()
    result = _run(config, broker, make_runner({"worker-1": "success"}), FakeClock())
    authors = sorted(m["author"] for m in Board(result.board_path).list())
    assert authors == ["arbiter", "worker-1"]
