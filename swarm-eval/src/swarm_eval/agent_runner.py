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
import signal
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
    """One `inspect eval` subprocess to launch: its argv, the env vars injected on top of the
    inherited environment (the runner merges `os.environ` under these), and — for a swarm worker —
    where to redirect its merged stdout+stderr. The launch unit both entrypoints hand to a
    runner — the agent's identity, when it has one, rides inside `env` (`AGENT_ID`), not as a
    field, so this stays the minimal thing a runner needs.

    `console_path` is the 05c switch: when set (the conductor's per-worker `console.out`), the
    runner detaches the run into its own session/process group and streams its output to that file
    (the live tail); when None (single_agent, still attached to the launcher's tty), the run
    inherits the launcher's stdout/stderr and process group unchanged."""

    argv: list[str]
    env: dict[str, str]
    console_path: Path | None = None


class RunHandle(Protocol):
    """The slice of a launched run a launcher drives — so tests inject a fake with no real process.
    `single_agent` only needs `wait`; the conductor also winds stragglers down. Teardown is at the
    **process-group** level (`terminate_group`/`kill_group`), not the lone `inspect` parent, so a
    detached worker's grandchildren (adb, frida, docker, the emulator bridge) die with it (05c)."""

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate_group(self) -> None: ...
    def kill_group(self) -> None: ...


Runner = Callable[[RunSpec], RunHandle]


def build_run_argv(
    *,
    spec: str,
    model: str = DEFAULT_MODEL,
    task: str = DEFAULT_WORKER_TASK,
    time_limit: int | None = None,
    working_limit: int | None = None,
    message_limit: int | None = None,
    display: str | None = None,
) -> list[str]:
    """The `inspect eval` argv for one run. `-T spec=<yaml>` selects the target (the same device
    yaml the launcher pre-acquired), so the spawned `dynamic_agent` stages the right APK(s) +
    mission (apk-agnostic refactor). Per-run limits (termination layer b) ride as CLI flags; the
    log dir rides as `INSPECT_LOG_DIR` in the env, not a flag. `display` selects Inspect's UI —
    the conductor passes `conversation` (05c) so each worker streams an ANSI-free transcript to its
    console file instead of painting a fullscreen curses TUI over the terminal; None leaves
    Inspect's default (the fullscreen TUI, fine for a lone single_agent run)."""
    argv = ["inspect", "eval", task, "-T", f"spec={spec}", "--model", model]
    argv += _provider_model_args(model)
    if time_limit is not None:
        argv += ["--time-limit", str(time_limit)]
    if working_limit is not None:
        # Inspect's --working-limit caps model WORKING time (excludes retry/rate-limit backoff);
        # --time-limit caps wall time. On a rate-limited proxy, wall time is dominated by 429
        # backoff, so working_limit is the budget that actually reflects the agent's effort.
        argv += ["--working-limit", str(working_limit)]
    if message_limit is not None:
        argv += ["--message-limit", str(message_limit)]
    if display is not None:
        argv += ["--display", display]
    return argv


def _provider_model_args(model: str) -> list[str]:
    """Provider-specific `-M key=value` model args a served model needs to work behind the bridge.

    OpenAI-compatible providers (`openai-api/…`, i.e. every model reached through the LiteLLM
    proxy) default to `strict_tools=true`, which makes Inspect send tools with OpenAI strict
    function-calling schemas. Azure OpenAI then *enforces* the strict rule that `required` must
    list every property — but Claude Code's tool schemas carry optional properties (e.g. `Agent`
    omits `subagent_type` from `required`), so Azure 400s the request, and Inspect's retry/backoff
    turns that into a long silent stall (no `model_usage`, "does nothing for minutes"). Bedrock/
    Anthropic ignore `strict`, which is why the Claude sweep models work untouched. Disabling it is
    a no-op for models that don't enforce it, so it's safe to set for the whole openai-api family."""
    if model.startswith("openai-api/"):
        return ["-M", "strict_tools=false"]
    return []


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


class RunProcess:
    """A launched run's handle over a real `subprocess.Popen` — used by BOTH launchers (a lone
    single_agent run and each swarm worker), so it is named for the run, not the role. When
    `detached` (the run has its own session/process group via `start_new_session`),
    `terminate_group`/`kill_group` signal the WHOLE process group (`os.killpg`) so the run's
    grandchildren — adb, frida, docker, the emulator bridge — die with the `inspect` parent, not
    orphaned (05c). A non-detached run (single_agent, still attached to the launcher's tty) shares
    the launcher's own process group, so signalling that group would hit the launcher itself; it
    falls back to signalling only the run process."""

    def __init__(self, proc: subprocess.Popen, *, detached: bool) -> None:
        self._proc = proc
        self._detached = detached

    def poll(self) -> int | None:
        return self._proc.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._proc.wait(timeout)

    def terminate_group(self) -> None:
        self._signal_group(signal.SIGTERM)

    def kill_group(self) -> None:
        self._signal_group(signal.SIGKILL)

    def _signal_group(self, sig: int) -> None:
        if not self._detached:
            # Attached: the run shares the launcher's group — signal just the process, never the
            # group (that would take the launcher down with it).
            self._proc.send_signal(sig)
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), sig)
        except ProcessLookupError:
            pass  # the group is already gone — nothing left to signal


def subprocess_runner(spec: RunSpec) -> RunProcess:
    """Default runner: launch the run as a real `inspect eval` subprocess in `swarm-eval/`, the
    injected env layered over the inherited one. When `spec.console_path` is set (a swarm worker),
    the run is **detached** into its own session/process group (`start_new_session`) and its merged
    stdout+stderr stream to that file — the 05c live tail; `start_new_session` and the conductor's
    group-kill are one change (detaching without it would orphan the workers from the tty). The
    parent's copy of the console file is closed right after spawn — the child keeps its own dup —
    so launching N workers leaks no file descriptors. When `console_path` is None (single_agent),
    the run stays attached: it inherits the launcher's stdout/stderr and process group unchanged."""
    env = {**os.environ, **spec.env}
    cwd = str(swarm_eval_dir())
    if spec.console_path is None:
        return RunProcess(subprocess.Popen(spec.argv, cwd=cwd, env=env), detached=False)
    spec.console_path.parent.mkdir(parents=True, exist_ok=True)
    console = open(spec.console_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            spec.argv,
            cwd=cwd,
            env=env,
            stdout=console,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        console.close()  # the child inherited its own dup at exec; drop the parent's copy
    return RunProcess(proc, detached=True)
