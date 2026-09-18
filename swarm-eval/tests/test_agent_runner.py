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
    build_run_argv,
    build_run_env,
    mint_run_id,
    write_contract,
)
from swarm_eval.broker_client import Contract, parse_contract

CONTRACT = Contract("emulator-5554", 5554, 5555, "writable-system")


# ---- argv builder --------------------------------------------------------------------------

def test_build_run_argv_selects_target_via_spec_before_model():
    argv = build_run_argv(spec="devices/healthhub.yaml", model="anthropic/x")
    # `inspect eval <task> -T spec=<yaml> --model <model>`, spec right after the task
    assert argv[:3] == ["inspect", "eval", DEFAULT_WORKER_TASK]
    i = argv.index("-T")
    assert argv[i + 1] == "spec=devices/healthhub.yaml"
    assert argv[argv.index("--model") + 1] == "anthropic/x"


def test_build_run_argv_omits_limits_by_default():
    argv = build_run_argv(spec="devices/rasp_dummy.yaml")
    assert argv == [
        "inspect", "eval", DEFAULT_WORKER_TASK,
        "-T", "spec=devices/rasp_dummy.yaml",
        "--model", DEFAULT_MODEL,
    ]
    assert "--time-limit" not in argv and "--message-limit" not in argv


def test_build_run_argv_includes_limits_when_set():
    argv = build_run_argv(spec="devices/x.yaml", time_limit=1200, message_limit=40)
    assert "--time-limit" in argv and "1200" in argv
    assert "--message-limit" in argv and "40" in argv


def test_build_run_argv_honours_a_custom_task():
    argv = build_run_argv(spec="devices/x.yaml", task="other_agent.py")
    assert argv[2] == "other_agent.py"


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
