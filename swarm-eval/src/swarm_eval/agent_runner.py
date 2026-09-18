"""Shared host-side per-run machinery — the primitive both launchers build on (ticket 03).

The apk-agnostic refactor gives the eval two clean entrypoints over ONE agent unit:
`single_agent.py` (one agent) and `swarm.py`/`conductor.py` (N agents + board). Device
acquire/release is a **launcher** concern, not an agent one (spec: "guaranteed release via a
host try/finally"), so the machinery a launcher needs to turn a leased device into a running
`inspect eval dynamic_agent.py` subprocess lives here, in one place, used identically by both:

  - lease a broker device (`acquire`/`release`, re-exported from `broker_client`);
  - write its connection contract to a host file (`write_contract`) the launcher injects;
  - build the `inspect eval dynamic_agent.py -T spec=… --model … --time-limit …` argv
    (`build_run_argv`) and the run env — always `DEVICE_CONTRACT` + `INSPECT_LOG_DIR`, plus a
    caller-supplied board env when it is a swarm (`build_run_env`);
  - launch the run as a subprocess in `swarm-eval/` (`subprocess_runner`).

`dynamic_agent` never talks to the broker itself — a contract is ALWAYS injected (as the
`DEVICE_CONTRACT` file this module writes), and the launcher owns the lease. The swarm-only
layer (messageboard, agent ids, arbiter, collation) stays in `conductor.py`; this module knows
nothing about it beyond accepting an opaque `board_env` dict to merge.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

# Re-exported so both launchers reach the broker through the shared machinery: the device lease
# is a launcher concern (guaranteed host-side release), and `dynamic_agent` never acquires.
from .broker_client import Contract
from .broker_client import acquire as acquire
from .broker_client import release as release

# The launcher→run injection contract, per run: a device contract is ALWAYS injected as a host
# file whose path rides in `DEVICE_CONTRACT`; `INSPECT_LOG_DIR` is where Inspect writes the run's
# log (and the scored self-report). The board env vars (`SWARM_ID` etc.) are the conductor's, not
# here — a single run gets neither, so its absence is the "not a swarm" signal `dynamic_agent`
# keys off (ticket 03).
ENV_DEVICE_CONTRACT = "DEVICE_CONTRACT"
ENV_INSPECT_LOG_DIR = "INSPECT_LOG_DIR"

# The spawnable agent unit both entrypoints run (1× by single_agent, N× by the conductor). Model
# is the served provider model the sandbox's keyless CC proxies to — a sweep is this one flag
# (spec S2). The per-run wall-clock cap keeps termination layer (b) — "no run loops forever" —
# holding by default, not only when an operator remembers the flag.
DEFAULT_WORKER_TASK = "dynamic_agent.py"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
DEFAULT_TIME_LIMIT = 1800


def swarm_eval_dir() -> Path:
    """The `swarm-eval/` project dir — the cwd for launched `inspect eval` subprocesses (the task
    files live there). Derived from this module's location: src/swarm_eval/agent_runner.py."""
    return Path(__file__).resolve().parents[2]


def mint_run_id(prefix: str) -> str:
    """A fresh, sortable, human-legible run id: `<prefix>-<utc>-<shortid>`. The stamp orders run
    dirs chronologically under `ls`; the shortid keeps two same-second runs distinct. Shared by
    both launchers (`single-…` for single_agent, `swarm-…` for the conductor)."""
    now = datetime.now(timezone.utc)
    return f"{prefix}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class RunSpec:
    """One `inspect eval` subprocess to launch: its argv and the env vars injected on top of the
    inherited environment (the runner merges `os.environ` under these). The launch unit both
    entrypoints hand to a runner — the agent's identity, when it has one, rides inside `env`
    (`AGENT_ID`), not as a field, so this stays the minimal thing a runner needs."""

    argv: list[str]
    env: dict[str, str]


class RunHandle(Protocol):
    """The slice of `subprocess.Popen` a launcher drives — so tests inject a fake with no real
    process. `single_agent` only needs `wait`; the conductor also terminates/kills stragglers."""

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Runner = Callable[[RunSpec], RunHandle]


def build_run_argv(
    *,
    spec: str,
    model: str = DEFAULT_MODEL,
    task: str = DEFAULT_WORKER_TASK,
    time_limit: int | None = None,
    message_limit: int | None = None,
) -> list[str]:
    """The `inspect eval` argv for one run. `-T spec=<yaml>` selects the target (the same device
    yaml the launcher pre-acquired), so the spawned `dynamic_agent` stages the right APK(s) +
    mission (apk-agnostic refactor). Per-run limits (termination layer b) ride as CLI flags; the
    log dir rides as `INSPECT_LOG_DIR` in the env, not a flag."""
    argv = ["inspect", "eval", task, "-T", f"spec={spec}", "--model", model]
    if time_limit is not None:
        argv += ["--time-limit", str(time_limit)]
    if message_limit is not None:
        argv += ["--message-limit", str(message_limit)]
    return argv


def write_contract(contract: Contract, path: Path) -> Path:
    """Write a leased device's connection contract to a host file (in the broker's one-line
    format, symmetric with `parse_contract`) and return its path. The launcher injects this path
    as `DEVICE_CONTRACT`; the run's setup solver reads + parses it and stages it into the sandbox.
    The parent dir is created so a caller can drop it straight into a fresh run/log dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contract.render_contract_line() + "\n", encoding="utf-8")
    return path


def build_run_env(
    *,
    contract_path: Path | str,
    log_dir: Path | str,
    board_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """The env injected into one run (merged over the inherited environment by the runner). Always
    the per-run pair — the injected `DEVICE_CONTRACT` file and the run's `INSPECT_LOG_DIR` — plus
    the caller's `board_env` when this is a swarm worker (the conductor supplies the board
    coordinates; a single run passes none, and its absence is the "not a swarm" signal). Kept
    minimal so a test can assert the injection exactly."""
    env = {
        ENV_DEVICE_CONTRACT: str(contract_path),
        ENV_INSPECT_LOG_DIR: str(log_dir),
    }
    if board_env:
        env.update(board_env)
    return env


def subprocess_runner(spec: RunSpec) -> subprocess.Popen:
    """Default runner: launch the run as a real `inspect eval` subprocess in `swarm-eval/`, with
    the injected env layered over the inherited one."""
    env = {**os.environ, **spec.env}
    return subprocess.Popen(spec.argv, cwd=str(swarm_eval_dir()), env=env)
