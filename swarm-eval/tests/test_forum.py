"""swarm-improvements ticket 01 — the forum substrate: the board relocated under a per-swarm
forum tree, plus per-worker DM inboxes and status. Hermetic — a tmp dir stands in for the forum
root; no Inspect, no sandbox, no device. The board's own mechanics are covered by
`test_messageboard`; here we prove the forum LAYOUT (board + dms/<worker>/ + status) and the
DM/status operations reuse them correctly."""

import pytest

from swarm_eval.forum import (
    DMS_DIRNAME,
    ENV_FORUM_DIR,
    MESSAGEBOARD_DIRNAME,
    STATUS_FILENAME,
    Forum,
)
from swarm_eval.messageboard import BoardError, Message


@pytest.fixture
def forum(tmp_path):
    f = Forum(tmp_path / "forum")
    f.ensure(["worker-1", "worker-2"])
    return f


# ---- env resolution ------------------------------------------------------------------------

def test_from_env_reads_forum_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))
    assert Forum.from_env().root == tmp_path / "forum"


def test_from_env_raises_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_FORUM_DIR, raising=False)
    with pytest.raises(BoardError):
        Forum.from_env()


def test_from_env_or_none_is_none_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_FORUM_DIR, raising=False)
    assert Forum.from_env_or_none() is None


def test_from_env_or_none_is_forum_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FORUM_DIR, str(tmp_path / "forum"))
    assert Forum.from_env_or_none().root == tmp_path / "forum"


# ---- layout --------------------------------------------------------------------------------

def test_ensure_creates_board_and_one_inbox_per_worker(forum):
    assert (forum.root / MESSAGEBOARD_DIRNAME).is_dir()
    assert (forum.root / DMS_DIRNAME / "worker-1").is_dir()
    assert (forum.root / DMS_DIRNAME / "worker-2").is_dir()


def test_board_lives_under_the_messageboard_subdir(forum):
    assert forum.board.path == forum.root / MESSAGEBOARD_DIRNAME


def test_inbox_lives_under_dms_worker_subdir(forum):
    assert forum.inbox("worker-1").path == forum.root / DMS_DIRNAME / "worker-1"


def test_board_and_inbox_are_distinct_dirs(forum):
    forum.board.post(author="worker-1", subject="broadcast", content="c")
    forum.send_dm(sender="worker-1", to="worker-2", subject="dm", content="c")
    # a broadcast does not land in an inbox, and a DM does not land on the board
    assert [e["subject"] for e in forum.board.list()] == ["broadcast"]
    assert [e["subject"] for e in forum.inbox("worker-2").list()] == ["dm"]


# ---- DMs -----------------------------------------------------------------------------------

def test_send_dm_delivers_into_the_recipients_inbox_authored_by_sender(forum):
    forum.send_dm(sender="worker-1", to="worker-2", subject="look here", content="the payload")
    (dm,) = forum.read_dms("worker-2")
    assert isinstance(dm, Message)
    assert dm.author == "worker-1"       # the sender, stamped by the caller
    assert dm.subject == "look here"
    assert dm.content == "the payload"   # DMs return full bodies (no two-tier index)


def test_a_dm_reaches_only_its_recipient(forum):
    forum.send_dm(sender="worker-1", to="worker-2", subject="private", content="c")
    assert forum.read_dms("worker-2")  # recipient sees it
    assert forum.read_dms("worker-1") == []  # the sender's own inbox is untouched


def test_read_dms_since_returns_only_newer(forum):
    first = forum.send_dm(sender="worker-1", to="worker-2", subject="m0", content="c")
    forum.send_dm(sender="worker-1", to="worker-2", subject="m1", content="c")
    delta = forum.read_dms("worker-2", since=first.id)
    assert [m.subject for m in delta] == ["m1"]


def test_read_dms_since_latest_is_empty(forum):
    last = forum.send_dm(sender="worker-1", to="worker-2", subject="only", content="c")
    assert forum.read_dms("worker-2", since=last.id) == []


def test_send_dm_rejects_unknown_type(forum):
    with pytest.raises(BoardError):
        forum.send_dm(sender="worker-1", to="worker-2", subject="s", content="c", type="bogus")


def test_dm_to_a_worker_created_lazily_when_never_ensured(tmp_path):
    # A DM to a worker whose inbox dir was never pre-created still lands (post() ensures the dir).
    f = Forum(tmp_path / "forum")
    f.send_dm(sender="a", to="late-worker", subject="s", content="c")
    assert [m.subject for m in f.read_dms("late-worker")] == ["s"]


# ---- status --------------------------------------------------------------------------------

def test_status_round_trips(forum):
    assert forum.get_status("worker-1") is None  # none set yet
    forum.set_status("worker-1", "decompiling the APK")
    assert forum.get_status("worker-1") == "decompiling the APK"


def test_set_status_overwrites_the_previous(forum):
    forum.set_status("worker-1", "first")
    forum.set_status("worker-1", "second")
    assert forum.get_status("worker-1") == "second"


def test_status_file_is_not_seen_as_a_dm(forum):
    # The status lives inside the inbox dir but must not be mistaken for a DM message file.
    forum.set_status("worker-2", "busy")
    forum.send_dm(sender="worker-1", to="worker-2", subject="real dm", content="c")
    subjects = [m.subject for m in forum.read_dms("worker-2")]
    assert subjects == ["real dm"]  # the status.txt is not listed as a message
    assert (forum.inbox("worker-2").path / STATUS_FILENAME).exists()


def test_statuses_are_per_worker(forum):
    forum.set_status("worker-1", "on task A")
    forum.set_status("worker-2", "on task B")
    assert forum.get_status("worker-1") == "on task A"
    assert forum.get_status("worker-2") == "on task B"


def test_statuses_reports_the_whole_roster(forum):
    # ticket 03: the coordinator's peer-status read. With an explicit roster, every named worker
    # appears (one that set none maps to None); order follows the roster.
    forum.set_status("worker-1", "coordinating")
    forum.set_status("worker-2", "hooking")
    got = forum.statuses(["worker-1", "worker-2", "worker-3"])
    assert got == {"worker-1": "coordinating", "worker-2": "hooking", "worker-3": None}


def test_statuses_discovers_workers_when_no_roster_given(forum):
    # Without a roster it discovers whoever has an inbox (a bare demo/test).
    forum.set_status("worker-2", "busy")
    forum.set_status("worker-1", "idle")
    assert forum.statuses() == {"worker-1": "idle", "worker-2": "busy"}


# ---- shared substrate: two handles on one forum see each other -----------------------------

def test_two_handles_on_one_forum_share_state(tmp_path):
    a = Forum(tmp_path / "forum")
    b = Forum(tmp_path / "forum")
    a.send_dm(sender="worker-1", to="worker-2", subject="hi", content="c")
    a.set_status("worker-1", "working")
    assert [m.subject for m in b.read_dms("worker-2")] == ["hi"]
    assert b.get_status("worker-1") == "working"
