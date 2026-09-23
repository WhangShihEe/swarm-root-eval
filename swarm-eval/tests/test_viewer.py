"""Tests for `viewer` — the bespoke review-UI builder (swarm-improvements ticket 05, cut 1).

Every test is hermetic: it builds a fixture run on disk (a forum tree + real `.eval` files written
with Inspect's own `write_eval_log`, laid out exactly as the conductor lays one out), then asserts
the *builder* — `build_view_model` / `render_html` / `build` — turns it into the expected view
model and self-contained HTML. No browser, no network, no model: the acceptance is proven on the
emitted HTML/JSON string, exactly as the ticket says. Each cut-1 acceptance checkbox has a test
below (see the section headers).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSpec,
    EvalStats,
    write_eval_log,
)
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelUsage

from swarm_eval.conductor import ROLE_ARBITER, SUCCESS
from swarm_eval.forum import Forum
from swarm_eval.messageboard import (
    TYPE_DONE,
    TYPE_FINDING,
    TYPE_GIVEUP,
    TYPE_NOTE,
    TYPE_SUCCESS,
)
from swarm_eval.run_reader import read_run
from swarm_eval import viewer


# --------------------------------------------------------------------------------------------
# Fixture — a run laid out exactly as the conductor lays one out (mirrors test_run_reader).
# --------------------------------------------------------------------------------------------


def _write_eval(
    path: Path,
    *,
    role: str,
    agent_id: str,
    swarm_id: str,
    model: str = "anthropic/claude-opus-4-8",
    status: str = "success",
    turn_count: int = 6,
    total_time: float = 300.0,
    working_time: float = 250.0,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"agent_id": agent_id, "role": role, "swarm_id": swarm_id, "served_model": model}
    spec = EvalSpec(
        created="2026-09-24T00:00:00+00:00",
        task="dynamic_agent",
        dataset=EvalDataset(),
        config=EvalConfig(),
        model=model,
        metadata=metadata,
    )
    stats = EvalStats(
        started_at="2026-09-24T00:00:00+00:00",
        completed_at="2026-09-24T00:05:00+00:00",
        model_usage={model: ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150, total_cost=0.02)},
    )
    sample = EvalSample(
        id="1", epoch=1, input="do the mission", target="SUCCESS",
        messages=[ChatMessageUser(content="u"), ChatMessageAssistant(content="a")],
        total_time=total_time, working_time=working_time, turn_count=turn_count,
        started_at="2026-09-24T00:00:00+00:00", completed_at="2026-09-24T00:05:00+00:00",
    )
    write_eval_log(EvalLog(eval=spec, stats=stats, status=status, samples=[sample]), str(path))
    return path


def _build_run(root: Path, swarm_id: str = "swarm-view-test") -> Path:
    """worker-1 (dynamic, has a device) wins; worker-2 (static, no device) gives up. Includes a DM
    from worker-1 to worker-2, per-worker statuses, board posts, and the arbiter `done`."""
    log_dir = root / swarm_id
    forum = Forum(log_dir / "forum")
    forum.ensure(["worker-1", "worker-2"])

    _write_eval(log_dir / "worker-1" / "a.eval", role="dynamic", agent_id="worker-1", swarm_id=swarm_id)
    (log_dir / "worker-1" / "console.out").write_text("tail w1\n", encoding="utf-8")
    (log_dir / "worker-1" / "worker-1.device").write_text(
        "serial=emulator-5554 console_port=5554 profile=writable-system", encoding="utf-8"
    )
    _write_eval(log_dir / "worker-2" / "b.eval", role="static", agent_id="worker-2", swarm_id=swarm_id, turn_count=9)

    forum.set_status("worker-1", "attacking RASP root check")
    forum.set_status("worker-2", "static analysis of libnative")
    forum.send_dm(sender="worker-1", to="worker-2", subject="try the JNI hook",
                  content="the check is in libfoo", type=TYPE_FINDING)

    board = forum.board
    board.post(author="worker-1", subject="found smali gate", content="MainActivity", type=TYPE_FINDING)
    board.post(author="worker-1", subject="planning", content="note body", type=TYPE_NOTE)
    board.post(author="worker-2", subject="giving up static", content="no luck", type=TYPE_GIVEUP)
    win = board.post(author="worker-1", subject="bypassed root check",
                     content="frida hook returns false", type=TYPE_SUCCESS)
    board.post(author=ROLE_ARBITER, subject=f"done: {SUCCESS}",
               content=f"worker-1 reported success ({win.id})", type=TYPE_DONE)
    return log_dir


def _model(tmp_path: Path) -> dict:
    return viewer.build_view_model(read_run(_build_run(tmp_path)))


# --------------------------------------------------------------------------------------------
# Acceptance: forum swimlanes — board lane + per-worker lanes, DMs as cross-lane connectors,
# statuses as lane labels, type coding.
# --------------------------------------------------------------------------------------------


def test_lanes_include_board_and_every_worker(tmp_path: Path):
    m = _model(tmp_path)
    assert m["lanes"][0] == "board"
    assert m["lanes"] == ["board", "worker-1", "worker-2"]


def test_board_posts_land_in_board_lane_with_type(tmp_path: Path):
    m = _model(tmp_path)
    board_events = [e for e in m["events"] if e["kind"] == "board"]
    # 4 worker posts + the arbiter done = 5 board-lane events, all in the board lane.
    assert len(board_events) == 5
    assert all(e["lane"] == "board" for e in board_events)
    types = {e["type"] for e in board_events}
    assert {TYPE_FINDING, TYPE_NOTE, TYPE_GIVEUP, TYPE_SUCCESS, TYPE_DONE} == types


def test_dm_is_a_connector_recipient_lane_with_sender(tmp_path: Path):
    m = _model(tmp_path)
    dms = [e for e in m["events"] if e["kind"] == "dm"]
    assert len(dms) == 1
    dm = dms[0]
    assert dm["lane"] == "worker-2"       # marker in the RECIPIENT's lane
    assert dm["recipient"] == "worker-2"
    assert dm["author"] == "worker-1"     # connector back to the SENDER's lane
    assert dm["type"] == TYPE_FINDING


def test_events_carry_wallclock_ms_and_axis_bounds(tmp_path: Path):
    m = _model(tmp_path)
    assert all(e["ts_ms"] is not None for e in m["events"])
    # Wall-clock axis bounds are present and ordered (silence renders as a literal gap in the UI).
    assert m["time"]["start_ms"] is not None
    assert m["time"]["end_ms"] >= m["time"]["start_ms"]
    # Events are chronological.
    ms = [e["ts_ms"] for e in m["events"]]
    assert ms == sorted(ms)


def test_status_text_is_the_lane_label(tmp_path: Path):
    m = _model(tmp_path)
    by_id = {w["worker_id"]: w for w in m["workers"]}
    assert by_id["worker-1"]["status_text"] == "attacking RASP root check"
    assert by_id["worker-2"]["status_text"] == "static analysis of libnative"


# --------------------------------------------------------------------------------------------
# Acceptance: per-agent snapshot dashboard (role, device, status, message split, DMs, outcome +
# expand block).
# --------------------------------------------------------------------------------------------


def test_dashboard_default_columns(tmp_path: Path):
    m = _model(tmp_path)
    by_id = {w["worker_id"]: w for w in m["workers"]}
    w1, w2 = by_id["worker-1"], by_id["worker-2"]

    assert w1["role"] == "dynamic" and w1["device"] == "emulator"
    assert w2["role"] == "static" and w2["device"] == "none"

    # message split: worker-1 posted 1 finding, 1 note, 1 success.
    assert w1["messages"] == {"total": 3, "findings": 1, "notes": 1, "success": 1, "giveup": 0}
    assert w2["messages"]["giveup"] == 1

    # DMs: worker-1 sent 1, worker-2 received 1.
    assert w1["dms"]["sent"] == 1 and w1["dms"]["received"] == 0
    assert w2["dms"]["received"] == 1

    # outcome: worker-1 won (success), worker-2 gave up.
    assert w1["outcome"] == "success" and w1["is_winner"] is True
    assert w2["outcome"] == "giveup"


def test_dashboard_expand_block_has_turns_tokens_times(tmp_path: Path):
    m = _model(tmp_path)
    s = {w["worker_id"]: w for w in m["workers"]}["worker-1"]["stats"]
    assert s["turn_count"] == 6
    assert s["total_tokens"] == 150
    assert s["total_time"] == 300.0 and s["working_time"] == 250.0
    assert s["served_model"] == "anthropic/claude-opus-4-8"


def test_last_activity_and_quiet_flag_present(tmp_path: Path):
    m = _model(tmp_path)
    for w in m["workers"]:
        assert "last_activity_ms" in w and "went_quiet" in w
        assert isinstance(w["went_quiet"], bool)
    # worker-1 posted (has a real last-activity time).
    assert {w["worker_id"]: w for w in m["workers"]}["worker-1"]["last_activity_ms"] is not None


# --------------------------------------------------------------------------------------------
# Acceptance: run header — arbiter verdict + winner, agent count, totals.
# --------------------------------------------------------------------------------------------


def test_run_header_verdict_winner_and_totals(tmp_path: Path):
    m = _model(tmp_path)
    assert m["verdict"]["value"] == SUCCESS
    assert m["verdict"]["winner"] == "worker-1"
    assert m["verdict"]["trigger_id"] is not None
    t = m["totals"]
    assert t["agents"] == 2
    assert t["board_messages"] == 4          # arbiter `done` excluded
    assert t["findings"] == 1 and t["successes"] == 1 and t["giveups"] == 1
    assert t["dms"] == 1
    assert t["total_tokens"] == 300          # 150 per worker


# --------------------------------------------------------------------------------------------
# Acceptance: Inspect transcripts = link-out (view URL + per-worker .eval deep-links, NOT iframe).
# --------------------------------------------------------------------------------------------


def test_inspect_linkout_view_url_and_per_worker_deeplinks(tmp_path: Path):
    m = viewer.build_view_model(read_run(_build_run(tmp_path)), view_host="127.0.0.1", view_port=7575)
    ins = m["inspect"]
    assert ins["view_url"] == "http://127.0.0.1:7575/"
    assert "?log_dir=" in ins["log_dir_url"]
    # a deep-link per worker that wrote an .eval, each a `?log_file=` into the running view
    assert set(ins["workers"]) == {"worker-1", "worker-2"}
    for wid, url in ins["workers"].items():
        assert url.startswith("http://127.0.0.1:7575/?log_file=")
        assert wid in url or ".eval" in url


def test_html_does_not_iframe_inspect_view(tmp_path: Path):
    html = viewer.render_html(_model(tmp_path))
    # link-out only: no iframe embedding of the inspect view.
    assert "<iframe" not in html.lower()
    assert 'target="_blank"' in html


# --------------------------------------------------------------------------------------------
# Acceptance: self-contained HTML — the emitted file inlines the run and opens with no external
# fetch except the intentional inspect link-out.
# --------------------------------------------------------------------------------------------


def _extract_inline_json(html: str) -> dict:
    m = re.search(r'<script id="run-data" type="application/json">(.*?)</script>', html, re.S)
    assert m, "inline run-data island missing"
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_render_html_inlines_the_view_model(tmp_path: Path):
    model = _model(tmp_path)
    html = viewer.render_html(model)
    assert viewer.RUN_DATA_TOKEN not in html          # token was substituted
    data = _extract_inline_json(html)
    assert data["schema_version"] == viewer.SCHEMA_VERSION
    assert data["verdict"]["winner"] == "worker-1"
    assert [w["worker_id"] for w in data["workers"]] == ["worker-1", "worker-2"]


def test_html_has_no_external_resource_urls(tmp_path: Path):
    html = viewer.render_html(_model(tmp_path))
    # No external stylesheets/scripts/CDNs — everything inline. The only http(s) URLs allowed are
    # the intentional inspect-view link-outs (localhost). Assert there are no others.
    assert "<link" not in html.lower()
    assert "src=" not in html.lower()                 # no external <script src=>/<img src=>
    urls = re.findall(r'https?://[^\s"\'<>()]+', html)
    assert urls, "expected the inspect link-out URLs"
    assert all("127.0.0.1" in u or "localhost" in u for u in urls)


def test_message_body_cannot_break_out_of_the_data_island(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    # A malicious/awkward body containing a literal </script>.
    Forum(log_dir / "forum").board.post(
        author="worker-1", subject="xss?", content="pwn </script><script>alert(1)</script>",
        type=TYPE_NOTE,
    )
    html = viewer.render_html(viewer.build_view_model(read_run(log_dir)))
    # The escaped body must not introduce a raw closing script tag inside the island.
    island = re.search(r'type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script>" not in island
    # ...and it still round-trips as JSON.
    _extract_inline_json(html)


def test_build_writes_self_contained_file(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    out = viewer.build(log_dir)
    assert out == log_dir / "review.html"
    assert out.exists() and out.stat().st_size > 0
    data = _extract_inline_json(out.read_text(encoding="utf-8"))
    assert data["swarm_id"] == "swarm-view-test"


# --------------------------------------------------------------------------------------------
# Acceptance: purity — the viewer adds no model dependency and does not import safetytooling.
# --------------------------------------------------------------------------------------------


def test_viewer_does_not_import_safetytooling():
    src = Path(viewer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any("safetytooling" in name or "safety_tooling" in name for name in imported), imported
    # And no LLM-client dependency reaches the builder.
    assert not any(name.split(".")[0] in {"anthropic", "openai"} for name in imported), imported


# --------------------------------------------------------------------------------------------
# Acceptance: data layer structured for a later live phase (one well-defined data object).
# --------------------------------------------------------------------------------------------


def test_data_layer_is_a_single_swappable_object(tmp_path: Path):
    html = viewer.render_html(_model(tmp_path))
    # exactly one data island, and a single getRunData() seam reading it.
    assert html.count('id="run-data"') == 1
    assert "function getRunData()" in html
    # the model is versioned so a live server and this frontend can agree on the shape.
    assert _extract_inline_json(html)["schema_version"] == viewer.SCHEMA_VERSION


# --------------------------------------------------------------------------------------------
# Acceptance: run selection — auto-lists logs/ (most-recent default) and accepts an explicit path.
# --------------------------------------------------------------------------------------------


def test_scan_runs_lists_runs_most_recent_first(tmp_path: Path):
    logs = tmp_path / "logs"
    _build_run(logs, "swarm-20260101T000000-aaaaaa")
    _build_run(logs, "swarm-20260301T000000-cccccc")
    _build_run(logs, "swarm-20260201T000000-bbbbbb")
    (logs / "archive").mkdir()  # bookkeeping dir, not a run
    (logs / "loose.txt").write_text("x")  # not a dir
    runs = viewer.scan_runs(logs)
    names = [p.name for p in runs]
    assert names == [
        "swarm-20260301T000000-cccccc",
        "swarm-20260201T000000-bbbbbb",
        "swarm-20260101T000000-aaaaaa",
    ]


def test_scan_runs_empty_when_no_logs(tmp_path: Path):
    assert viewer.scan_runs(tmp_path / "nope") == []


def test_cli_accepts_explicit_run_path(tmp_path: Path):
    log_dir = _build_run(tmp_path)
    out = tmp_path / "review.html"
    rc = viewer.main([str(log_dir), "-o", str(out)])
    assert rc == 0 and out.exists()


def test_cli_picks_newest_when_no_path_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logs = tmp_path / "logs"
    _build_run(logs, "swarm-20260101T000000-aaaaaa")
    newest = _build_run(logs, "swarm-20260301T000000-cccccc")
    # non-interactive => newest by default (no picker prompt).
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: False)
    rc = viewer.main(["--logs-dir", str(logs)])
    assert rc == 0
    assert (newest / "review.html").exists()


def test_cli_reports_when_no_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: False)
    rc = viewer.main(["--logs-dir", str(tmp_path / "empty")])
    assert rc == 2
