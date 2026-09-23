"""`swarm` — the Conductor CLI (ticket 05b): launch one swarm run over N dynamic agents.

The launcher is external to Inspect (ADR-0002): it mints a swarm-id, creates the 05a board,
pre-acquires one broker device per worker, starts N `inspect eval` worker subprocesses, runs the
host-side arbiter over the board, posts the `done` verdict, and collates everything under
`logs/<swarm-id>/`. A broker must be up first (`bin/broker start`).

    # single agent = the swarm at N=1 (uniform path, not special-cased)
    python swarm.py devices/rasp_dummy.yaml --workers 1

    # a 3-agent swarm on HealthHub, 20-min per-run cap, 45-min swarm budget
    python swarm.py devices/healthhub.yaml --workers 3 --time-limit 1200 --budget 2700 \
        --model anthropic/claude-sonnet-4-5-20250929

The target is selected ENTIRELY by the device yaml (apk-agnostic): the required positional is the
same yaml the broker acquires and the workers attack (`-T spec=`). The `--model` flag is the
model-sweep lever (spec S2): the sandbox's keyless CC proxies to it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from swarm_eval.conductor import (
    DEFAULT_CAP,
    DEFAULT_MODEL,
    DEFAULT_TIME_LIMIT,
    DEFAULT_VIEW_PORT,
    SUCCESS,
    Conductor,
    SwarmConfig,
    SwarmError,
)
from swarm_eval.target import load_run_config

# The launcher's built-in defaults for the run knobs an eval config may set — the last tier of the
# ticket-03 precedence (CLI > eval config > this). The swarm hard wall-clock and the single-agent
# baseline worker count.
DEFAULT_BUDGET = 3600.0
DEFAULT_WORKERS = 1


def _pick(cli, cfg, default):
    """CLI > config > built-in default: the CLI value when the flag was given (not None), else the
    eval-config value when it set one (not None), else the built-in default (ticket 03)."""
    if cli is not None:
        return cli
    if cfg is not None:
        return cfg
    return default


def build_config(args: argparse.Namespace) -> SwarmConfig:
    """Map parsed args + the eval config's run knobs → `SwarmConfig`, resolving CLI > config >
    built-in default per knob (ticket 03): `--workers`/`--model`/limits/budget/cap left unset are
    `None` here (see `parse_args`), so the eval config's value stands; a legacy device yaml yields
    an empty `RunConfig`, so the built-in defaults apply (no regression). `--board-dir`/`--log-dir`
    are only forwarded when given, so the config's under-`swarm-eval/` defaults stand otherwise."""
    run = load_run_config(args.spec)
    kwargs: dict = dict(
        workers=_pick(args.workers, run.worker_count, DEFAULT_WORKERS),
        model=_pick(args.model, run.model, DEFAULT_MODEL),
        spec=args.spec,
        cap=_pick(args.cap, run.cap, DEFAULT_CAP),
        time_limit=_pick(args.time_limit, run.time_limit, DEFAULT_TIME_LIMIT),
        message_limit=_pick(args.message_limit, run.message_limit, None),
        budget=_pick(args.budget, run.budget, DEFAULT_BUDGET),
        grace=args.grace,
        poll_interval=args.poll_interval,
        view=args.view,
        view_port=args.view_port,
    )
    if args.board_dir is not None:
        kwargs["board_root"] = args.board_dir
    if args.log_dir is not None:
        kwargs["log_root"] = args.log_dir
    return SwarmConfig(**kwargs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="swarm", description="Launch one swarm run (ticket 05b).")
    p.add_argument("spec", help="eval config or device yaml selecting the target/run, e.g. "
                                "configs/evals/rasp_dummy.yaml")
    # Run-knob flags default to None (not the built-in default) so an unset flag is distinguishable
    # from one passed with the default value — `build_config` then applies CLI > config > default.
    p.add_argument("-n", "--workers", type=int, default=None,
                   help="number of worker agents (N=1 is the single-agent case); overrides the "
                        "eval config's worker roster (built-in default 1)")
    p.add_argument("--model", default=None,
                   help="served provider model the sandboxed CC proxies to (the sweep lever); "
                        "overrides the eval config's `model`")
    p.add_argument("--cap", type=int, default=None,
                   help="max workers before fail-fast (mirrors the broker cap); overrides the eval "
                        "config's limits.cap (built-in default 6)")
    p.add_argument("--time-limit", type=int, default=None,
                   help="per-run Inspect --time-limit in seconds (layer-b termination); overrides "
                        "the eval config's limits.time_limit")
    p.add_argument("--message-limit", type=int, default=None,
                   help="per-run Inspect --message-limit (layer-b termination); overrides the eval "
                        "config's limits.message_limit")
    p.add_argument("--budget", type=float, default=None,
                   help="launcher hard wall-clock, seconds, before the swarm fails; overrides the "
                        "eval config's limits.budget (built-in default 3600)")
    p.add_argument("--grace", type=float, default=30.0,
                   help="seconds a run gets to exit after `done` before it is killed (default 30)")
    p.add_argument("--poll-interval", type=float, default=2.0,
                   help="how often the arbiter re-reads the board, seconds (default 2)")
    p.add_argument("--no-view", dest="view", action="store_false",
                   help="don't auto-start the inspect webview; print the manual command instead")
    p.add_argument("--view-port", type=int, default=DEFAULT_VIEW_PORT,
                   help=f"port for the auto-started inspect webview (default {DEFAULT_VIEW_PORT})")
    p.add_argument("--board-dir", type=Path, default=None,
                   help="board root (default swarm-eval/board); the board is <root>/<swarm-id>/")
    p.add_argument("--log-dir", type=Path, default=None,
                   help="log root (default swarm-eval/logs); logs land in <root>/<swarm-id>/")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    try:
        result = Conductor(build_config(args)).run()
    except SwarmError as e:
        print(f"swarm: {e}", file=sys.stderr)
        return 2
    v = result.verdict
    print(f"\nswarm {result.swarm_id}: {v.value} — {v.reason}")
    print(f"  workers:  {', '.join(result.worker_ids)}")
    print(f"  artifact: {result.log_dir}  (transcripts + messageboard/)")
    # Exit 0 on a SUCCESS verdict, 1 on FAILURE — a swarm that ran fine but did not crack the app
    # is a clean non-zero, distinct from the exit-2 setup failure above.
    return 0 if v.value == SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
