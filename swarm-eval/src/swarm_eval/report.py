"""`report.py <log-dir>` — the post-run report (swarm-improvements ticket 04).

A separate, re-runnable command that turns a *finished* swarm run into a human-readable
`logs/<swarm-id>/report.md`. It layers **synthesis** on top of the pure `run_reader`:

  1. `run_reader.read_run` collates the run (forum + per-worker `.eval` stats + arbiter verdict)
     into one `RunObject` — no model, no `safetytooling` (that stays here).
  2. `report.py` renders the run's hard facts (verdict, per-worker stats, board timeline) and asks
     a **configurable report model** — via a **direct host-side LLM call**, not a bridged agent
     and with no device/tools — to synthesize insights, then writes them together to `report.md`.

The synthesis model is **user-configurable** (`--model` / `$SWARM_REPORT_MODEL`) and defaults
**independently** of the eval's swept `--model`, so report quality never varies with the model
under evaluation. The command only ever *reads* the run and *writes* `report.md`: it re-runs
against an existing log dir without re-running the swarm and without touching its budget or
verdict.

The LLM call runs through the vendored **safety-tooling submodule** (`safety-tooling/`). That
stack's pins (anthropic/openai/pydantic) are mutually exclusive with the harness's, so it cannot
share this venv; the default backend therefore executes the call in the submodule's *own*
environment (`_report_infer.py` via `uv run --project`). The backend is injectable
(`write_report(..., infer=…)`) so tests exercise the collation + prompt + file-writing paths with
the model mocked — no network, no submodule build.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .messageboard import Message
from .run_reader import RunObject, WorkerRun, read_run

# The synthesis backend: (model_id, system_prompt, user_prompt) -> completion text. Injectable so
# tests mock it; the default (`safetytooling_infer`) runs the call in the submodule's own env.
Infer = Callable[[str, str, str], str]

# The report model is configured INDEPENDENTLY of the eval's `--model` (the swept, served model) so
# report quality is constant across a sweep. CLI `--model` > `$SWARM_REPORT_MODEL` > this built-in.
ENV_REPORT_MODEL = "SWARM_REPORT_MODEL"
DEFAULT_REPORT_MODEL = "claude-sonnet-4-5-20250929"

REPORT_FILENAME = "report.md"

# The vendored submodule (repo root `safety-tooling/`) and the in-submodule runner. `report.py`
# lives at `swarm-eval/src/swarm_eval/report.py`, so the repo root is four parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
SAFETY_TOOLING_DIR = _REPO_ROOT / "safety-tooling"
_RUNNER = Path(__file__).with_name("_report_infer.py")


def resolve_report_model(cli_model: str | None = None) -> str:
    """The report model to synthesize with: CLI `--model` > `$SWARM_REPORT_MODEL` > the built-in
    default. Independent of the eval's served `--model` by construction (a different flag and a
    different env var), so nothing here reads the swept model."""
    return cli_model or os.environ.get(ENV_REPORT_MODEL) or DEFAULT_REPORT_MODEL


# --------------------------------------------------------------------------------------------
# Prompt assembly — the run's hard facts, rendered for both the model and the report body.
# --------------------------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a security-research analyst writing the insights section of a post-run report for a "
    "swarm of autonomous agents probing an Android app's anti-root / RASP defenses. You are given "
    "the finished run's hard facts: the arbiter verdict, each worker's role and resource usage, "
    "and the shared message-board timeline. Write a concise, factual synthesis in Markdown: what "
    "the swarm achieved, which worker/approach was decisive (or why it failed), how the workers "
    "coordinated on the board, and 2-4 concrete follow-ups. Do not invent facts beyond those "
    "given; do not restate the raw tables verbatim. No preamble."
)


def _fmt_num(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "—"


def _fmt_secs(s: float | None) -> str:
    return f"{s:.0f}s" if isinstance(s, (int, float)) else "—"


def _worker_line(w: WorkerRun) -> str:
    st = w.stats
    role = w.role or "—"
    if st is None:
        return f"- {w.worker_id} (role={role}): no .eval recorded; status={w.status_text or '—'}"
    parts = [
        f"status={st.status}",
        f"turns={st.turn_count if st.turn_count is not None else '—'}",
        f"msgs={st.message_count if st.message_count is not None else '—'}",
        f"tokens={_fmt_num(st.total_tokens)}",
        f"time={_fmt_secs(st.total_time)}",
    ]
    if st.error:
        parts.append(f"error={st.error!r}")
    if st.limit:
        parts.append(f"limit={st.limit}")
    return (
        f"- {w.worker_id} (role={role}, model={w.served_model or '—'}"
        f"{', decider' if w.is_decider else ''}): "
        + ", ".join(parts)
        + (f"; status_note={w.status_text!r}" if w.status_text else "")
    )


def _board_line(m: Message) -> str:
    return f"- [{m.type}] {m.author}: {m.subject}"


def render_facts(run: RunObject) -> str:
    """The deterministic, model-free facts section of the report (and the bulk of the LLM's user
    prompt): verdict, per-worker roster/usage, and the board timeline. Built purely from the
    `RunObject`, so it is stable and testable without any model."""
    v = run.verdict
    lines: list[str] = []
    lines.append(f"## Verdict\n")
    lines.append(f"- Outcome: **{v.value or 'INCOMPLETE (no verdict posted)'}**")
    if v.reason:
        lines.append(f"- Reason: {v.reason}")
    if v.winner:
        lines.append(f"- Winning worker: **{v.winner}**")
    if v.trigger:
        lines.append(f"- Deciding message: [{v.trigger.type}] {v.trigger.subject}")
    lines.append("")

    lines.append("## Workers\n")
    for w in run.workers:
        lines.append(_worker_line(w))
    lines.append("")

    dm_total = sum(len(w.dms) for w in run.workers)
    lines.append("## Message board\n")
    lines.append(f"{len(run.board)} board message(s); {dm_total} direct message(s).\n")
    for m in run.board:
        lines.append(_board_line(m))
    lines.append("")
    return "\n".join(lines)


def build_prompt(run: RunObject) -> tuple[str, str]:
    """The (system, user) pair for the synthesis call. The user prompt is the rendered facts plus
    the DM threads (targeted coordination the board timeline alone doesn't show), so the model
    reasons over exactly what `run_reader` parsed — nothing more."""
    facts = render_facts(run)
    dm_blocks: list[str] = []
    for w in run.workers:
        for dm in w.dms:
            dm_blocks.append(f"- {dm.author} -> {w.worker_id} [{dm.type}]: {dm.subject}: {dm.content}")
    dms = "\n".join(dm_blocks) if dm_blocks else "(none)"
    user = (
        f"Swarm run `{run.swarm_id}`.\n\n"
        f"{facts}\n"
        f"## Direct messages\n\n{dms}\n\n"
        "Write the insights section now."
    )
    return SYSTEM_PROMPT, user


# --------------------------------------------------------------------------------------------
# Synthesis + report writing.
# --------------------------------------------------------------------------------------------


def synthesize(run: RunObject, *, model: str, infer: Infer) -> str:
    """Ask the report model for the insights section. Pure orchestration: builds the prompt from
    the `RunObject` and delegates the actual call to `infer` (mocked in tests, the submodule
    backend in production). Returns the model's Markdown."""
    system, user = build_prompt(run)
    return infer(model, system, user).strip()


def compose_report(run: RunObject, insights: str, *, model: str) -> str:
    """Assemble the final `report.md`: a header, the model's synthesized insights, then the
    deterministic facts (so the report stands on its own even if synthesis is terse)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"# Swarm run report — `{run.swarm_id}`\n\n"
        f"_Generated {now} · report model `{model}` · verdict "
        f"**{run.verdict.value or 'INCOMPLETE'}**_\n\n"
        f"## Insights\n\n{insights}\n\n"
        f"---\n\n{render_facts(run)}"
    )


def write_report(
    log_dir: str | Path,
    *,
    model: str | None = None,
    infer: Infer | None = None,
) -> Path:
    """Read the finished run at `log_dir`, synthesize insights with the configured report model,
    and write `<log-dir>/report.md`. Returns the report path.

    Re-runnable: it only *reads* the run (via `run_reader`) and *writes* `report.md`; it never
    touches the forum, the budget, or the verdict. `infer` defaults to the submodule backend and is
    injectable for tests. `model` defaults independently of the eval's `--model`
    (`resolve_report_model`)."""
    run = read_run(log_dir)
    report_model = resolve_report_model(model)
    backend = infer if infer is not None else safetytooling_infer
    insights = synthesize(run, model=report_model, infer=backend)
    report_path = run.log_dir / REPORT_FILENAME
    report_path.write_text(compose_report(run, insights, model=report_model), encoding="utf-8")
    return report_path


# --------------------------------------------------------------------------------------------
# Default backend — the safety-tooling submodule, in its own environment.
# --------------------------------------------------------------------------------------------


def safetytooling_infer(
    model: str,
    system: str,
    user: str,
    *,
    submodule: Path = SAFETY_TOOLING_DIR,
    timeout: float = 900.0,
) -> str:
    """Run one synthesis call through the safety-tooling submodule's OWN environment via
    `uv run --project <submodule> python _report_infer.py`. The submodule's stack is pin-
    incompatible with this harness (anthropic/openai/pydantic all differ), so the call is executed
    at the process boundary rather than imported here. Requires the submodule's env to be synced
    and the relevant provider API key in the environment (both the human's to provide for a live
    run). Raises `RuntimeError` with the runner's stderr on failure."""
    if not (submodule / "pyproject.toml").exists():
        raise RuntimeError(
            f"safety-tooling submodule not found at {submodule}; run "
            "`git submodule update --init` (see the ticket-04 wiring notes)"
        )
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / "in.json"
        out_path = Path(td) / "out.txt"
        in_path.write_text(
            json.dumps({"model": model, "system": system, "user": user}), encoding="utf-8"
        )
        argv = [
            "uv", "run", "--project", str(submodule),
            "python", str(_RUNNER), str(in_path), str(out_path),
        ]
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, cwd=str(submodule)
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"safetytooling inference failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
            )
        return out_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="report",
        description="Write logs/<swarm-id>/report.md for a finished swarm run (ticket 04).",
    )
    p.add_argument("log_dir", type=Path, help="a finished run's log dir, e.g. logs/<swarm-id>")
    p.add_argument(
        "--model", default=None,
        help="report synthesis model (independent of the eval's --model); overrides "
             f"${ENV_REPORT_MODEL} (built-in default {DEFAULT_REPORT_MODEL})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        path = write_report(args.log_dir, model=args.model)
    except FileNotFoundError as e:
        print(f"report: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"report: synthesis failed: {e}", file=sys.stderr)
        return 1
    print(f"report: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
