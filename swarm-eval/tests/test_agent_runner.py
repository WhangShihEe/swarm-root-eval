"""Ticket 03 — the shared host-side per-run machinery both launchers build on: the argv/env
builders, the contract-file write, and the run-id/dir helpers. Pure functions — no broker, no
subprocess, no wall-clock."""

from pathlib import Path

from swarm_eval import agent_runner as ar
from swarm_eval.agent_runner import (
    DEFAULT_MODEL,
    DEFAULT_TIME_LIMIT,
    DEFAULT_WORKER_TASK,
    ENV_DEVICE_CONTRACT,
    ENV_INSPECT_LOG_DIR,
    RunSpec,
    build_run_argv,
    build_run_env,
    mint_run_id,
    write_contract,
)
from swarm_eval.broker_client import Contract, parse_contract

CONTRACT = Contract("emulator-5554", 5554, 5555, "writable-system")


# ---- argv builder --------------------------------------------------------------------------

def test_build_run_argv_selects_target_via_spec_before_model():
    argv = build_run_argv(spec="configs/evals/healthhub.yaml", model="anthropic/x")
    # `inspect eval <task> -T spec=<yaml> --model <model>`, spec right after the task
    assert argv[:3] == ["inspect", "eval", DEFAULT_WORKER_TASK]
    i = argv.index("-T")
    assert argv[i + 1] == "spec=configs/evals/healthhub.yaml"
    assert argv[argv.index("--model") + 1] == "anthropic/x"


def test_build_run_argv_omits_limits_by_default():
    argv = build_run_argv(spec="configs/evals/rasp_dummy.yaml")
    assert argv == [
        "inspect", "eval", DEFAULT_WORKER_TASK,
        "-T", "spec=configs/evals/rasp_dummy.yaml",
        "--model", DEFAULT_MODEL,
    ]
    assert "--time-limit" not in argv and "--message-limit" not in argv


def test_build_run_argv_includes_limits_when_set():
    argv = build_run_argv(spec="configs/evals/x.yaml", time_limit=1200, message_limit=40)
    assert "--time-limit" in argv and "1200" in argv
    assert "--message-limit" in argv and "40" in argv


def test_build_run_argv_honours_a_custom_task():
    argv = build_run_argv(spec="configs/evals/x.yaml", task="other_agent.py")
    assert argv[2] == "other_agent.py"


def test_build_run_argv_appends_display_when_set():
    # 05c: the conductor passes `--display conversation` so a worker streams an ANSI-free
    # transcript to its console file instead of a fullscreen TUI.
    argv = build_run_argv(spec="configs/evals/x.yaml", display="conversation")
    assert argv[argv.index("--display") + 1] == "conversation"


def test_build_run_argv_omits_display_by_default():
    assert "--display" not in build_run_argv(spec="configs/evals/x.yaml")


def test_build_run_argv_disables_strict_tools_for_openai_api_models():
    # openai-api (LiteLLM proxy) models default to strict function-calling schemas, which Azure
    # OpenAI rejects for Claude Code's optional-property tools (e.g. Agent). Disable it so the
    # bridge's tools are accepted instead of 400ing into a silent retry stall.
    argv = build_run_argv(spec="configs/evals/x.yaml", model="openai-api/litellm/azure-gpt-5.6-sol")
    assert argv[argv.index("-M") + 1] == "strict_tools=false"


def test_build_run_argv_leaves_anthropic_models_untouched():
    # Bedrock/Anthropic ignore strict schemas, so the Claude sweep models need no -M override.
    assert "-M" not in build_run_argv(spec="configs/evals/x.yaml", model="anthropic/claude-sonnet-4-5")


# ---- subprocess_runner: per-worker redirect + detachment (05c) ------------------------------

class _FakeProc:
    """Minimal `Popen` stand-in for testing the runner without a real subprocess."""

    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return None


def test_subprocess_runner_redirects_to_console_and_detaches(tmp_path, monkeypatch):
    # A swarm worker (console_path set) merges stdout+stderr into its per-agent console.out (the
    # live tail) and detaches into its own session/process group — one atomic change with the
    # conductor's group-kill.
    console = tmp_path / "swarm-x" / "worker-1" / "console.out"
    captured: dict = {}

    def fake_popen(argv, cwd=None, env=None, stdout=None, stderr=None, start_new_session=False):
        captured.update(
            cwd=cwd,
            stdout_name=getattr(stdout, "name", None),
            stderr=stderr,
            start_new_session=start_new_session,
        )
        return _FakeProc()

    monkeypatch.setattr(ar.subprocess, "Popen", fake_popen)
    handle = ar.subprocess_runner(
        RunSpec(argv=["inspect", "eval", "dynamic_agent.py"], env={"X": "1"}, console_path=console)
    )
    assert console.parent.is_dir()  # the per-agent dir is created before launch
    assert captured["stdout_name"] == str(console)  # stdout → the console file
    assert captured["stderr"] is ar.subprocess.STDOUT  # stderr merged in, so tracebacks land too
    assert captured["start_new_session"] is True  # its own session/group → group-killable
    assert isinstance(handle, ar.RunProcess)


def test_subprocess_runner_stays_attached_when_no_console(monkeypatch):
    # single_agent (console_path None) inherits the launcher's stdout/stderr and process group —
    # detaching it without a group-kill would be a regression (the tty could no longer reach it).
    captured: dict = {}

    def fake_popen(argv, cwd=None, env=None, stdout=None, stderr=None, start_new_session=False):
        captured.update(stdout=stdout, stderr=stderr, start_new_session=start_new_session)
        return _FakeProc()

    monkeypatch.setattr(ar.subprocess, "Popen", fake_popen)
    ar.subprocess_runner(RunSpec(argv=["inspect"], env={}))
    assert captured["stdout"] is None and captured["stderr"] is None  # inherited, not redirected
    assert captured["start_new_session"] is False  # stays in the launcher's group


# ---- RunProcess: process-group teardown (05c) -----------------------------------------------

class _SignalProc:
    def __init__(self, pid: int = 9999) -> None:
        self.pid = pid
        self.signalled: list[int] = []

    def send_signal(self, sig: int) -> None:
        self.signalled.append(sig)


def test_worker_process_signals_the_whole_group_when_detached(monkeypatch):
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(ar.os, "getpgid", lambda pid: pid)  # detached leader: pgid == pid
    monkeypatch.setattr(ar.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    proc = _SignalProc()
    handle = ar.RunProcess(proc, detached=True)
    handle.terminate_group()
    handle.kill_group()
    assert killed == [(9999, ar.signal.SIGTERM), (9999, ar.signal.SIGKILL)]
    assert proc.signalled == []  # the GROUP, never the lone process


def test_worker_process_signals_only_the_process_when_attached(monkeypatch):
    def boom(*a):  # attached shares the launcher's group — a group signal would hit the launcher
        raise AssertionError("killpg must not run for an attached process")

    monkeypatch.setattr(ar.os, "killpg", boom)
    proc = _SignalProc(pid=5)
    ar.RunProcess(proc, detached=False).terminate_group()
    assert proc.signalled == [ar.signal.SIGTERM]  # lone process only


# ---- env builder ---------------------------------------------------------------------------

def test_build_run_env_always_carries_the_per_run_pair(tmp_path):
    env = build_run_env(contract_path=tmp_path / "d.contract", log_dir=tmp_path / "logs" / "r")
    assert env[ENV_DEVICE_CONTRACT] == str(tmp_path / "d.contract")
    assert env[ENV_INSPECT_LOG_DIR] == str(tmp_path / "logs" / "r")
    # a single run gets no board coordinates — its absence is the "not a swarm" signal
    assert set(env) == {ENV_DEVICE_CONTRACT, ENV_INSPECT_LOG_DIR}


def test_build_run_env_merges_board_env_when_a_swarm(tmp_path):
    env = build_run_env(
        contract_path=tmp_path / "d.contract",
        log_dir=tmp_path / "r",
        board_env={"SWARM_ID": "swarm-x", "AGENT_ID": "worker-1"},
    )
    assert env["SWARM_ID"] == "swarm-x" and env["AGENT_ID"] == "worker-1"
    assert env[ENV_DEVICE_CONTRACT] == str(tmp_path / "d.contract")


# ---- contract file write -------------------------------------------------------------------

def test_write_contract_round_trips_through_parse_contract(tmp_path):
    path = write_contract(CONTRACT, tmp_path / "sub" / "worker-1.device")
    assert path.exists()  # parent dir created
    assert parse_contract(path.read_text()) == CONTRACT


# ---- run id / dirs -------------------------------------------------------------------------

def test_mint_run_id_is_prefixed_and_unique():
    a, b = mint_run_id("single"), mint_run_id("single")
    assert a.startswith("single-") and b.startswith("single-")
    assert a != b


def test_swarm_eval_dir_points_at_the_project_root_holding_the_task():
    d = ar.swarm_eval_dir()
    assert (d / DEFAULT_WORKER_TASK).exists()
