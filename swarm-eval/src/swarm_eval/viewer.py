"""`viewer` — the bespoke swarm-run review UI builder (swarm-improvements ticket 05, cut 1).

A **thin builder over the pure `run_reader`**: it reads one finished swarm run off disk via
`run_reader.read_run` (no model, no `safetytooling` — the same hard constraint the reader carries),
assembles that typed `RunObject` into one flat **view model** (plain JSON-able dicts), and injects
it into a single self-contained HTML template. The output opens directly in a browser with no
external fetches except the intentional link-out to a running `inspect view` (port 7575) — the one
surface that cannot be embedded (`inspect view` hard-sets `Content-Security-Policy:
frame-ancestors 'none'` + `X-Frame-Options: DENY`, see `inspect_ai/_view/network.py:235-236`).

Three functions carry the whole contract, each provable in isolation:

  * `build_view_model(run, ...)` — the pure `RunObject -> dict` assembly (forum events, per-agent
    dashboard, run header, inspect link-outs). No I/O; the unit-testable heart.
  * `render_html(model)` — inject the view model as inline JSON into the one HTML template asset.
  * `build(run_path, out_path=?)` — read the run, assemble, render, write the HTML file.

The view model is deliberately **one well-defined object** (`schema_version` stamped) so the later
live phase (FastAPI + SSE) feeds the *same* frontend by swapping the data source — the JS reads
from `getRunData()` and nothing else; "live" is a data-source swap, not new UI. This module builds
no server (an explicitly named follow-up); cut 1 is a static review artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .conductor import (
    DEFAULT_VIEW_PORT,
    DEVICE_ROLES,
    ROLE_ARBITER,
)
from .messageboard import (
    TYPE_FINDING,
    TYPE_GIVEUP,
    TYPE_NOTE,
    TYPE_SUCCESS,
)
from .run_reader import RunObject, WorkerRun, read_run

# The view model's shape is a contract with the frontend (and the later live server). Bump this if
# a field the JS depends on changes, so a stale template fails loud instead of rendering nonsense.
SCHEMA_VERSION = 1

# The single HTML template asset this builder injects the run JSON into.
TEMPLATE_PATH = Path(__file__).with_name("templates") / "viewer.html"
# The token in the template swapped for the inline run JSON (a JSON string literal position).
RUN_DATA_TOKEN = "__RUN_DATA__"

# `inspect view` defaults (host + port); the swarm auto-starts it `--recursive` over the log root.
DEFAULT_VIEW_HOST = "127.0.0.1"

# A worker is flagged "went quiet" if its last board/DM activity predates the run's end by more
# than this — the wall-clock "who stopped talking, when" signal the forum lanes are built around.
# Adaptive, with a floor: the larger of 90s or a fifth of the run's span.
_QUIET_FLOOR_MS = 90_000
_QUIET_FRACTION = 0.2


# --------------------------------------------------------------------------------------------
# Public builder API.
# --------------------------------------------------------------------------------------------


def build(
    run_path: str | Path,
    out_path: str | Path | None = None,
    *,
    view_host: str = DEFAULT_VIEW_HOST,
    view_port: int = DEFAULT_VIEW_PORT,
) -> Path:
    """Read the finished run at `run_path`, assemble it, render the self-contained HTML, and write
    it. Returns the output path. `out_path` defaults to `<run_path>/review.html` (the HTML ships
    beside the run's own artifacts, like `report.md`). Pure disk I/O over the pure `run_reader`."""
    run = read_run(run_path)
    model = build_view_model(run, view_host=view_host, view_port=view_port)
    html = render_html(model)
    out = Path(out_path) if out_path is not None else Path(run.log_dir) / "review.html"
    out.write_text(html, encoding="utf-8")
    return out


def render_html(model: dict) -> str:
    """Inject the view model into the one HTML template as inline JSON. Escapes `</` so a message
    body containing `</script>` cannot break out of the data island; the rest is a single token
    swap, keeping the template a static, editable asset."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(RUN_DATA_TOKEN, data)


def build_view_model(
    run: RunObject,
    *,
    view_host: str = DEFAULT_VIEW_HOST,
    view_port: int = DEFAULT_VIEW_PORT,
) -> dict:
    """Assemble a `RunObject` into the flat, JSON-able view model the frontend renders. Pure: no
    I/O, no model. Everything the UI needs — forum lane events, per-agent dashboard rows, the run
    header (verdict/winner/totals), the time-axis bounds, and the inspect link-outs — is computed
    here from what `run_reader` already parsed."""
    device_roles = set(DEVICE_ROLES)
    dms_sent = _count_dms_sent(run)

    events = _build_events(run)
    ms_values = [e["ts_ms"] for e in events if e["ts_ms"] is not None]
    for w in run.workers:
        if w.stats is not None:
            for iso in (w.stats.started_at, w.stats.completed_at):
                ms = _ms(iso)
                if ms is not None:
                    ms_values.append(ms)
    start_ms = min(ms_values) if ms_values else None
    end_ms = max(ms_values) if ms_values else None
    quiet_gap = _quiet_gap_ms(start_ms, end_ms)

    workers = [
        _worker_row(
            w,
            run=run,
            device_roles=device_roles,
            dms_sent=dms_sent.get(w.worker_id, 0),
            end_ms=end_ms,
            quiet_gap=quiet_gap,
            view_host=view_host,
            view_port=view_port,
        )
        for w in run.workers
    ]

    # Board lane first, then one lane per worker in the reader's (numeric) order.
    lanes = ["board"] + [w.worker_id for w in run.workers]

    return {
        "schema_version": SCHEMA_VERSION,
        "swarm_id": run.swarm_id,
        "log_dir": str(run.log_dir),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verdict": _verdict_block(run),
        "totals": _totals_block(run, workers),
        "time": {"start_ms": start_ms, "end_ms": end_ms},
        "lanes": lanes,
        "workers": workers,
        "events": events,
        "inspect": _inspect_block(run, workers, view_host, view_port),
    }


# --------------------------------------------------------------------------------------------
# Run selection (CLI): scan `logs/` for runs.
# --------------------------------------------------------------------------------------------


def scan_runs(logs_dir: str | Path) -> list[Path]:
    """Every swarm run under `logs_dir`, most-recent first. A run dir is an immediate child that
    holds a `forum/` subdir or at least one `worker-*` subdir (the shape `run_reader` reads);
    `archive/` and other bookkeeping dirs are skipped. Names are timestamped and lexically
    sortable, so newest-first is a reverse name sort."""
    root = Path(logs_dir)
    if not root.is_dir():
        return []
    runs = [child for child in root.iterdir() if child.is_dir() and _is_run_dir(child)]
    return sorted(runs, key=lambda p: p.name, reverse=True)


def _is_run_dir(path: Path) -> bool:
    if (path / "forum").is_dir():
        return True
    return any(c.is_dir() and c.name.startswith("worker-") for c in path.iterdir())


# --------------------------------------------------------------------------------------------
# View-model assembly helpers (pure).
# --------------------------------------------------------------------------------------------


def _build_events(run: RunObject) -> list[dict]:
    """Every forum event, oldest first: each board post (in the `board` lane) and each delivered DM
    (in the *recipient's* lane, carrying its sender for the cross-lane connector). Message `type`
    rides along for color/icon coding. Content is included whole — the run's forum is low-volume,
    and the detail panel shows it."""
    events: list[dict] = []
    for m in run.board:
        events.append(
            {
                "id": m.id,
                "kind": "board",
                "lane": "board",
                "author": m.author,
                "recipient": None,
                "type": m.type,
                "subject": m.subject,
                "content": m.content,
                "ts": m.ts,
                "ts_ms": _ms(m.ts),
            }
        )
    for w in run.workers:
        for m in w.dms:
            events.append(
                {
                    "id": m.id,
                    "kind": "dm",
                    "lane": w.worker_id,  # a DM lands in the recipient's lane
                    "author": m.author,  # ...connected back to the sender's lane
                    "recipient": w.worker_id,
                    "type": m.type,
                    "subject": m.subject,
                    "content": m.content,
                    "ts": m.ts,
                    "ts_ms": _ms(m.ts),
                }
            )
    events.sort(key=lambda e: (e["ts_ms"] is None, e["ts_ms"] or 0, e["id"]))
    return events


def _count_dms_sent(run: RunObject) -> dict[str, int]:
    """`{worker_id: DMs it authored}`, summed across every inbox (a DM's `author` is its sender).
    `run_reader` gives each worker its *received* DMs; sent is derived by scanning them all."""
    sent: dict[str, int] = {}
    for w in run.workers:
        for m in w.dms:
            sent[m.author] = sent.get(m.author, 0) + 1
    return sent


def _worker_row(
    w: WorkerRun,
    *,
    run: RunObject,
    device_roles: set[str],
    dms_sent: int,
    end_ms: int | None,
    quiet_gap: int | None,
    view_host: str,
    view_port: int,
) -> dict:
    """One dashboard row for a worker: the lean default columns (role, device, status line,
    last-activity/went-quiet, message split, DM counts, outcome) plus the expand block (turns,
    tokens, wall/working time) and the per-worker inspect deep-link."""
    posted = _count_posts(run, w.worker_id)
    last_activity_ms = _last_activity_ms(run, w.worker_id)
    went_quiet = (
        last_activity_ms is not None
        and end_ms is not None
        and quiet_gap is not None
        and (end_ms - last_activity_ms) > quiet_gap
    )
    s = w.stats
    is_winner = run.verdict.winner == w.worker_id

    return {
        "worker_id": w.worker_id,
        "role": w.role,
        "device": _device_kind(w, device_roles),
        "status_text": w.status_text,
        "is_decider": w.is_decider,
        "is_winner": is_winner,
        "last_activity_ms": last_activity_ms,
        "went_quiet": bool(went_quiet),
        "messages": {
            "total": sum(posted.values()),
            "findings": posted.get(TYPE_FINDING, 0),
            "notes": posted.get(TYPE_NOTE, 0),
            "success": posted.get(TYPE_SUCCESS, 0),
            "giveup": posted.get(TYPE_GIVEUP, 0),
        },
        "dms": {"sent": dms_sent, "received": len(w.dms)},
        "outcome": _outcome(w, is_winner=is_winner, posted=posted),
        "stats": _stats_block(s),
        "eval_url": _eval_deeplink(w, view_host, view_port),
        "eval_path": str(w.eval_path) if w.eval_path else None,
        "console_path": str(w.console_path) if w.console_path else None,
    }


def _count_posts(run: RunObject, worker_id: str) -> dict[str, int]:
    """This worker's board posts, counted by `type`."""
    counts: dict[str, int] = {}
    for m in run.board:
        if m.author == worker_id:
            counts[m.type] = counts.get(m.type, 0) + 1
    return counts


def _last_activity_ms(run: RunObject, worker_id: str) -> int | None:
    """The worker's last *communicated* moment: the latest ts among the board posts it authored and
    the DMs it sent. `None` if it never posted — the went-quiet flag then simply cannot fire."""
    latest: int | None = None
    for m in run.board:
        if m.author == worker_id:
            latest = _max(latest, _ms(m.ts))
    for w in run.workers:
        for m in w.dms:
            if m.author == worker_id:
                latest = _max(latest, _ms(m.ts))
    return latest


def _device_kind(w: WorkerRun, device_roles: set[str]) -> str:
    """`emulator` / `physical` / `none`. A device role's `<id>.device` file names the serial
    (`serial=emulator-5554 …`); an `emulator-*` serial is an emulator, anything else physical. A
    non-device role (static/coordinator) leases no device, so `none`."""
    if w.device_path is not None:
        try:
            text = Path(w.device_path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        serial = _parse_kv(text).get("serial", "")
        if serial:
            return "emulator" if serial.startswith("emulator-") else "physical"
        # A device file with no serial still means a device was leased.
        return "device"
    if w.role in device_roles:
        return "device"  # a device role whose .device file didn't survive
    return "none"


def _parse_kv(text: str) -> dict[str, str]:
    """Parse the space-separated `k=v` `.device` line into a dict (tolerant of blanks)."""
    out: dict[str, str] = {}
    for tok in text.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def _outcome(w: WorkerRun, *, is_winner: bool, posted: dict[str, int]) -> str:
    """The worker's coarse outcome for the dashboard: `success` (posted a success / won), `giveup`
    (posted a giveup), `errored` (its `.eval` errored), `limit` (a sample limit stopped it), else
    its raw `.eval` status (`completed`/`started`/…), or `unknown` with no `.eval`."""
    if is_winner or posted.get(TYPE_SUCCESS, 0) > 0:
        return "success"
    if posted.get(TYPE_GIVEUP, 0) > 0:
        return "giveup"
    s = w.stats
    if s is None:
        return "unknown"
    if s.error:
        return "errored"
    if s.limit:
        return "limit"
    if s.status == "error":
        return "errored"
    if s.status == "success":
        return "completed"
    return s.status or "unknown"


def _stats_block(s) -> dict | None:
    """The expand-panel numbers, straight off `WorkerStats` (or `None` when no `.eval`)."""
    if s is None:
        return None
    return {
        "status": s.status,
        "served_model": s.served_model,
        "message_count": s.message_count,
        "turn_count": s.turn_count,
        "total_time": s.total_time,
        "working_time": s.working_time,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "total_tokens": s.total_tokens,
        "total_cost": s.total_cost,
        "error": s.error,
        "limit": s.limit,
        "limit_reason": s.limit_reason,
        "started_at": s.started_at,
        "completed_at": s.completed_at,
        "started_at_ms": _ms(s.started_at),
        "completed_at_ms": _ms(s.completed_at),
        "usage": [
            {
                "model": u.model,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "total_tokens": u.total_tokens,
                "reasoning_tokens": u.reasoning_tokens,
                "total_cost": u.total_cost,
            }
            for u in s.usage
        ],
    }


def _verdict_block(run: RunObject) -> dict:
    """The run header's verdict: value (SUCCESS/FAILURE/None), winner, reason, and the `done` ts."""
    v = run.verdict
    return {
        "value": v.value,
        "winner": v.winner,
        "reason": v.reason,
        "trigger_id": v.trigger.id if v.trigger is not None else None,
        "done_ts": v.done_message.ts if v.done_message is not None else None,
    }


def _totals_block(run: RunObject, workers: list[dict]) -> dict:
    """Run-wide counters for the header: agents, board volume (by type, arbiter `done` excluded),
    DMs, and summed tokens/cost."""
    findings = notes = successes = giveups = board_non_arbiter = 0
    for m in run.board:
        if m.author == ROLE_ARBITER:
            continue
        board_non_arbiter += 1
        if m.type == TYPE_FINDING:
            findings += 1
        elif m.type == TYPE_NOTE:
            notes += 1
        elif m.type == TYPE_SUCCESS:
            successes += 1
        elif m.type == TYPE_GIVEUP:
            giveups += 1
    total_dms = sum(w["dms"]["received"] for w in workers)
    total_tokens = sum((w["stats"] or {}).get("total_tokens", 0) or 0 for w in workers)
    costs = [
        (w["stats"] or {}).get("total_cost")
        for w in workers
        if w["stats"] is not None and w["stats"].get("total_cost") is not None
    ]
    return {
        "agents": len(run.workers),
        "board_messages": board_non_arbiter,
        "findings": findings,
        "notes": notes,
        "successes": successes,
        "giveups": giveups,
        "dms": total_dms,
        "total_tokens": total_tokens,
        "total_cost": sum(costs) if costs else None,
    }


def _inspect_block(
    run: RunObject, workers: list[dict], view_host: str, view_port: int
) -> dict:
    """The link-out surface: the running `inspect view` root (recursive over the log root) and a
    per-worker `?log_file=` deep-link to each `.eval`. Link-out only — `inspect view` cannot be
    iframed (CSP `frame-ancestors 'none'` + `X-Frame-Options: DENY`)."""
    base = f"http://{view_host}:{view_port}/"
    return {
        "view_url": base,
        "log_dir_url": f"{base}?log_dir={quote(str(run.log_dir), safe='')}",
        "workers": {w["worker_id"]: w["eval_url"] for w in workers if w["eval_url"]},
    }


def _eval_deeplink(w: WorkerRun, view_host: str, view_port: int) -> str | None:
    """A worker's `inspect view` deep-link: `http://<host>:<port>/?log_file=<abs .eval path>`.
    `None` when the worker wrote no `.eval`."""
    if w.eval_path is None:
        return None
    return f"http://{view_host}:{view_port}/?log_file={quote(str(w.eval_path), safe='')}"


# --------------------------------------------------------------------------------------------
# Small pure utilities.
# --------------------------------------------------------------------------------------------


def _ms(iso: str | None) -> int | None:
    """ISO-8601 → epoch milliseconds, or `None` if unparseable/absent."""
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except ValueError:
        return None


def _max(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _quiet_gap_ms(start_ms: int | None, end_ms: int | None) -> int | None:
    """The went-quiet threshold for this run: max(floor, fraction of the run span)."""
    if start_ms is None or end_ms is None:
        return _QUIET_FLOOR_MS
    span = max(0, end_ms - start_ms)
    return max(_QUIET_FLOOR_MS, int(span * _QUIET_FRACTION))


# --------------------------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------------------------


def _default_logs_dir() -> Path:
    """`swarm-eval/logs` — the conductor's default log root (this file is `src/swarm_eval/`)."""
    return Path(__file__).resolve().parents[2] / "logs"


def _select_run(logs_dir: Path, *, interactive: bool) -> Path | None:
    """Pick a run when none was given: newest by default; an interactive tty gets a numbered picker
    (Enter = newest). Returns `None` when `logs/` holds no runs."""
    runs = scan_runs(logs_dir)
    if not runs:
        return None
    if not interactive:
        return runs[0]
    print(f"Swarm runs under {logs_dir} (newest first):", file=sys.stderr)
    for i, r in enumerate(runs):
        marker = " (default)" if i == 0 else ""
        print(f"  [{i}] {r.name}{marker}", file=sys.stderr)
    try:
        raw = input("Pick a run [0]: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        return runs[0]
    try:
        idx = int(raw)
        return runs[idx]
    except (ValueError, IndexError):
        print(f"swarm-view: invalid selection {raw!r}", file=sys.stderr)
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="swarm-view",
        description="Build a self-contained HTML review of a finished swarm run (ticket 05).",
    )
    p.add_argument(
        "run_path",
        nargs="?",
        type=Path,
        help="a finished run's log dir (e.g. logs/<swarm-id>); omitted = pick from logs/",
    )
    p.add_argument(
        "-o", "--out", type=Path, default=None,
        help="output HTML path (default: <run>/review.html)",
    )
    p.add_argument(
        "--logs-dir", type=Path, default=None,
        help="where to scan for runs when no run_path is given (default: swarm-eval/logs)",
    )
    p.add_argument("--view-host", default=DEFAULT_VIEW_HOST, help="inspect view host for link-outs")
    p.add_argument(
        "--view-port", type=int, default=DEFAULT_VIEW_PORT, help="inspect view port for link-outs"
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_path = args.run_path
    if run_path is None:
        logs_dir = args.logs_dir or _default_logs_dir()
        run_path = _select_run(logs_dir, interactive=sys.stdin.isatty())
        if run_path is None:
            print(f"swarm-view: no runs found under {logs_dir}", file=sys.stderr)
            return 2
    try:
        out = build(
            run_path,
            args.out,
            view_host=args.view_host,
            view_port=args.view_port,
        )
    except FileNotFoundError as e:
        print(f"swarm-view: {e}", file=sys.stderr)
        return 2
    print(f"swarm-view: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
