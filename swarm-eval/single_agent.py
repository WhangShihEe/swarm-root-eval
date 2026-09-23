"""`single_agent` — entrypoint 1: one device, one dynamic agent, no board (ticket 03).

The host-side launcher for ONE `dynamic_agent` run. It leases a broker device, injects its
contract, launches the agent as an `inspect eval` subprocess with a budget/time-limit, and
releases the device in a `finally` — guaranteed even if the run fails or times out (an LLM
worker can't be trusted to free a scarce device; the lease is a launcher concern). Used to see
whether a single model makes progress and to check the single-agent environment works.

    # attack the RASP toy with the default model, 30-min per-run cap
    python single_agent.py configs/evals/rasp_dummy.yaml

    # a real app under a sweep model, tighter caps
    python single_agent.py configs/evals/healthhub.yaml \
        --model anthropic/claude-sonnet-4-5-20250929 --time-limit 1200 --message-limit 60

The target is selected ENTIRELY by the eval config (apk-agnostic): the launcher resolves it to the
broker's acquire spec (device + APK), and the eval config itself is the agent's `-T spec=` target.
This run gets NO board env, so `dynamic_agent`
runs in single mode (the bare mission, no board tools). The scored self-report lands in the
Inspect log under the run's log dir. A broker must be up first (`bin/broker start`).

`swarm.py … -n 1` reaches the same one-agent outcome through the swarm path (one worker + a
one-participant board); `single_agent.py` is the leaner board-free path for the common case.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from swarm_eval.agent_runner import (
    DEFAULT_MODEL,
    DEFAULT_TIME_LIMIT,
    DEFAULT_WORKER_TASK,
    RunSpec,
    Runner,
    build_run_argv,
    build_run_env,
    mint_run_id,
    subprocess_runner,
    swarm_eval_dir,
    write_contract,
)
from swarm_eval.broker_client import Contract
from swarm_eval.broker_client import acquire as broker_acquire
from swarm_eval.broker_client import release as broker_release
from swarm_eval.target import load_run_config, load_target

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SingleConfig:
    """One single-agent run's knobs. `spec` is the eval config (the target selector + broker
    acquire spec). `log_root` defaults under `swarm-eval/`; the run logs into
    `log_root/<run-id>/`, where the injected device contract is also written."""

    spec: str
    model: str = DEFAULT_MODEL
    time_limit: int | None = DEFAULT_TIME_LIMIT  # per-run Inspect --time-limit (s); layer (b)
    working_limit: int | None = None  # per-run Inspect --working-limit (s); working time, opt-in
    message_limit: int | None = None  # per-run Inspect --message-limit; layer (b), opt-in
    task: str = DEFAULT_WORKER_TASK
    log_root: Path = field(default_factory=lambda: swarm_eval_dir() / "logs")


def run_single(
    config: SingleConfig,
    *,
    acquire: Callable[..., Contract] = broker_acquire,
    release: Callable[[str], None] = broker_release,
    runner: Runner = subprocess_runner,
) -> int:
    """Lease one device → inject its contract → launch one `dynamic_agent` run → release, always.

    Returns the run subprocess's exit code (the eval's — the SUCCESS/FAILURE self-report itself
    lives in the Inspect log, not the exit code, since a clean eval of a target that wasn't
    cracked is still a run that ran). The device is released in a `finally`, so a failed or
    timed-out run still frees its scarce broker slot. `acquire`/`release`/`runner` are injected so
    a test drives the whole flow with no real broker or subprocess."""
    run_id = mint_run_id("single")
    log_dir = config.log_root / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    # Resolve the eval config to learn which device
    # the broker acquires and, when the config splits the APK out of the device, the APK to install
    # (`--target-apk`). The `-T spec=` below stays the positional itself — the in-task load_target
    # reads it back into the same TargetConfig (apk-agnostic).
    target = load_target(config.spec)
    apk_args = target.env_up_args()
    logger.info("single %s: leasing device (spec=%s, device=%s)",
                run_id, config.spec, target.device_spec)
    contract: Contract = acquire(target.device_spec, *apk_args)
    try:
        contract_path = write_contract(contract, log_dir / "device.contract")
        argv = build_run_argv(
            spec=config.spec,
            model=config.model,
            task=config.task,
            time_limit=config.time_limit,
            working_limit=config.working_limit,
            message_limit=config.message_limit,
        )
        # No board env → dynamic_agent runs in single mode (bare mission, no board tools).
        env = build_run_env(contract_path=contract_path, log_dir=log_dir)
        logger.info("single %s: launching agent on device %s", run_id, contract.serial)
        handle = runner(RunSpec(argv=argv, env=env))
        rc = handle.wait()
        logger.info("single %s: eval finished (rc=%s); log in %s", run_id, rc, log_dir)
        return rc
    finally:
        logger.info("single %s: releasing device %s", run_id, contract.serial)
        release(contract.serial)


def _pick(cli, cfg, default):
    """CLI > config > built-in default: the CLI value when the flag was given (not None), else the
    eval-config value when it set one (not None), else the launcher's built-in default. This is the
    ticket-03 override rule — a run is replicable from the eval config, and any flag still wins for
    that run without editing the file."""
    if cli is not None:
        return cli
    if cfg is not None:
        return cfg
    return default


def build_config(args: argparse.Namespace) -> SingleConfig:
    """Map parsed args + the eval config's run knobs → `SingleConfig`, resolving CLI > config >
    built-in default per knob (ticket 03). A CLI flag left unset is `None` here (see `parse_args`),
    so the eval config's value stands; an eval config that omits a knob leaves it unset, so the
    built-in defaults apply (no regression). `--log-dir` is only forwarded when given, so the
    under-`swarm-eval/` default stands otherwise."""
    run = load_run_config(args.spec)
    kwargs: dict = dict(
        spec=args.spec,
        model=_pick(args.model, run.model, DEFAULT_MODEL),
        time_limit=_pick(args.time_limit, run.time_limit, DEFAULT_TIME_LIMIT),
        working_limit=_pick(args.working_limit, run.working_limit, None),
        message_limit=_pick(args.message_limit, run.message_limit, None),
    )
    if args.log_dir is not None:
        kwargs["log_root"] = args.log_dir
    return SingleConfig(**kwargs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="single_agent", description="Launch one dynamic-agent run (ticket 03)."
    )
    p.add_argument("spec", help="eval config selecting the target/run, e.g. "
                                "configs/evals/rasp_dummy.yaml")
    # Run-knob flags default to None (not the built-in default) so an unset flag is distinguishable
    # from one passed with the default value — `build_config` then applies CLI > config > default.
    p.add_argument("--model", default=None,
                   help="served provider model the sandboxed CC proxies to (the sweep lever); "
                        f"overrides the eval config's `model` (built-in default {DEFAULT_MODEL})")
    p.add_argument("--time-limit", type=int, default=None,
                   help="per-run Inspect --time-limit in seconds; overrides the eval config's "
                        f"limits.time_limit (built-in default {DEFAULT_TIME_LIMIT})")
    p.add_argument("--working-limit", type=int, default=None,
                   help="per-run Inspect --working-limit in seconds: caps WORKING time (excludes "
                        "retry/rate-limit backoff), unlike --time-limit which caps wall time; "
                        "overrides the eval config's limits.working_limit (opt-in)")
    p.add_argument("--message-limit", type=int, default=None,
                   help="per-run Inspect --message-limit; overrides the eval config's "
                        "limits.message_limit (opt-in)")
    p.add_argument("--log-dir", type=Path, default=None,
                   help="log root (default swarm-eval/logs); the run logs into <root>/<run-id>/")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    return run_single(build_config(args))


if __name__ == "__main__":
    raise SystemExit(main())
