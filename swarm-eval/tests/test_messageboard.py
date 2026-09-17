"""Ticket 05a — the messageboard substrate: a host-side, append-only, one-file-per-message
directory. Hermetic — a tmp dir stands in for BOARD_DIR; no Inspect, no sandbox, no device."""

import json

import pytest

from swarm_eval.messageboard import (
    MESSAGE_TYPES,
    Board,
    BoardError,
    Message,
    board_dir,
)


@pytest.fixture
def board(tmp_path):
    b = Board(board_dir(tmp_path, "swarm-xyz"))
    b.ensure()
    return b


def test_board_dir_is_root_slash_swarm_id(tmp_path):
    assert board_dir(tmp_path, "swarm-xyz") == tmp_path / "swarm-xyz"


def test_post_writes_one_file_per_message(board):
    board.post(author="worker-1", subject="hello", content="body one")
    board.post(author="worker-1", subject="again", content="body two")
    files = sorted(board.path.glob("*.json"))
    assert len(files) == 2


def test_post_file_body_is_the_five_fields_no_id(board):
    msg = board.post(author="worker-1", subject="s", content="c", type="finding")
    on_disk = json.loads((board.path / f"{msg.id}.json").read_text())
    # the file carries exactly the spec's five fields — id lives in the filename, not the body
    assert set(on_disk) == {"ts", "author", "subject", "type", "content"}
    assert on_disk == {
        "ts": msg.ts,
        "author": "worker-1",
        "subject": "s",
        "type": "finding",
        "content": "c",
    }


def test_post_returns_message_with_id_matching_filename(board):
    msg = board.post(author="w", subject="s", content="c")
    assert isinstance(msg, Message)
    assert (board.path / f"{msg.id}.json").exists()


def test_id_prefix_is_a_legible_sortable_utc_timestamp(board):
    # The filename is `<ts>-<author>-<shortid>` (ticket format): the leading token is a
    # colon-free UTC stamp — human-legible under `ls`, and it shares the message's date.
    msg = board.post(author="w", subject="s", content="c")
    stamp = msg.id.split("-", 1)[0]
    assert ":" not in stamp  # filesystem-safe
    assert stamp[:8] == msg.ts[:10].replace("-", "")  # same UTC date as the ISO body ts


def test_default_type_is_note(board):
    msg = board.post(author="w", subject="s", content="c")
    assert msg.type == "note"


def test_post_rejects_unknown_type(board):
    with pytest.raises(BoardError):
        board.post(author="w", subject="s", content="c", type="bogus")


def test_all_declared_types_are_accepted(board):
    for t in MESSAGE_TYPES:
        board.post(author="w", subject=t, content="c", type=t)
    assert len(list(board.path.glob("*.json"))) == len(MESSAGE_TYPES)


def test_list_returns_index_only_not_bodies(board):
    board.post(author="worker-1", subject="hello", content="the secret body")
    (entry,) = board.list()
    assert set(entry) == {"id", "subject", "author", "ts", "type"}
    assert "content" not in entry
    assert entry["subject"] == "hello"
    assert entry["author"] == "worker-1"


def test_list_is_sorted_chronologically(board):
    for i in range(5):
        board.post(author="w", subject=f"m{i}", content="c")
    subjects = [e["subject"] for e in board.list()]
    assert subjects == ["m0", "m1", "m2", "m3", "m4"]


def test_list_since_returns_only_newer_messages(board):
    first = board.post(author="w", subject="m0", content="c")
    board.post(author="w", subject="m1", content="c")
    board.post(author="w", subject="m2", content="c")
    delta = board.list(since=first.id)
    assert [e["subject"] for e in delta] == ["m1", "m2"]


def test_list_since_latest_is_empty(board):
    board.post(author="w", subject="m0", content="c")
    last = board.post(author="w", subject="m1", content="c")
    assert board.list(since=last.id) == []


def test_read_returns_full_bodies(board):
    a = board.post(author="worker-1", subject="sa", content="body A")
    b = board.post(author="worker-2", subject="sb", content="body B")
    got = board.read([a.id, b.id])
    assert {m.subject: m.content for m in got} == {"sa": "body A", "sb": "body B"}
    assert all(isinstance(m, Message) for m in got)


def test_read_preserves_requested_order(board):
    a = board.post(author="w", subject="sa", content="A")
    b = board.post(author="w", subject="sb", content="B")
    assert [m.id for m in board.read([b.id, a.id])] == [b.id, a.id]


def test_read_skips_missing_ids(board):
    a = board.post(author="w", subject="sa", content="A")
    got = board.read([a.id, "00000000000000000000-ghost-deadbeef"])
    assert [m.id for m in got] == [a.id]


def test_read_accepts_a_single_id_string(board):
    a = board.post(author="w", subject="sa", content="A")
    got = board.read(a.id)
    assert [m.subject for m in got] == ["sa"]


def test_author_is_recorded_verbatim_even_when_filename_sanitized(board):
    # An AGENT_ID with filesystem-hostile chars is sanitized in the filename but the JSON
    # `author` (the field the index/read report) stays exact.
    msg = board.post(author="team/one:2", subject="s", content="c")
    assert msg.author == "team/one:2"
    assert board.read([msg.id])[0].author == "team/one:2"
    assert "/" not in msg.id and ":" not in msg.id


def test_two_boards_on_same_dir_see_each_others_messages(tmp_path):
    # Two independent Board handles on one dir = two runs posting to a shared board.
    d = board_dir(tmp_path, "swarm-shared")
    one = Board(d)
    one.ensure()
    two = Board(d)
    one.post(author="worker-1", subject="from one", content="c1")
    two.post(author="worker-2", subject="from two", content="c2")
    authors = {e["author"] for e in two.list()}
    assert authors == {"worker-1", "worker-2"}
