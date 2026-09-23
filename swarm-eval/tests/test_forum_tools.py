"""swarm-improvements ticket 01 — the `bridged_tools` DM/status layer over the forum, and the
board tools resolving the forum's board when a forum is injected. Hermetic: FORUM_DIR/AGENT_ID
are set exactly as the conductor injects them, a tmp dir stands in for the forum — no sandbox."""

import json

import pytest
from inspect_ai.tool import ToolError

from swarm_eval import board_tools as bt
from swarm_eval.forum import ENV_FORUM_DIR, ENV_WORKER_IDS, Forum


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Inject the per-run forum env the conductor provides, pointing the forum at a tmp dir."""
    forum_root = tmp_path / "forum"
    monkeypatch.setenv(ENV_FORUM_DIR, str(forum_root))
    monkeypatch.setenv("AGENT_ID", "worker-1")
    monkeypatch.delenv("BOARD_DIR", raising=False)
    monkeypatch.delenv("SWARM_ID", raising=False)
    monkeypatch.delenv(ENV_WORKER_IDS, raising=False)  # default: no roster → permissive send_dm
    return Forum(forum_root)


# ---- the board tools resolve the forum's board when a forum is injected ---------------------

async def test_post_message_writes_into_the_forum_board(env):
    mid = await bt.post_message()("hello", "body", "note")
    (msg,) = env.board.read([mid])
    assert msg.subject == "hello" and msg.author == "worker-1"


async def test_list_messages_reads_the_forum_board(env):
    env.board.post(author="worker-2", subject="from a peer", content="c")
    out = json.loads(await bt.list_messages()())
    assert [e["subject"] for e in out] == ["from a peer"]


# ---- send_dm -------------------------------------------------------------------------------

async def test_send_dm_delivers_into_the_recipient_inbox(env):
    mid = await bt.send_dm()("worker-2", "look", "the payload")
    (dm,) = env.read_dms("worker-2")
    assert dm.id == mid
    assert dm.author == "worker-1"   # sender, stamped from AGENT_ID
    assert dm.content == "the payload"


async def test_send_dm_does_not_touch_the_board(env):
    await bt.send_dm()("worker-2", "s", "c")
    assert env.board.list() == []  # a DM is not a broadcast


async def test_send_dm_author_is_stamped_not_forgeable(env, monkeypatch):
    await bt.send_dm()("worker-3", "from one", "c")
    monkeypatch.setenv("AGENT_ID", "worker-2")
    await bt.send_dm()("worker-3", "from two", "c")
    got = {m.subject: m.author for m in env.read_dms("worker-3")}
    assert got == {"from one": "worker-1", "from two": "worker-2"}


async def test_send_dm_forbids_done(env):
    with pytest.raises(ToolError):
        await bt.send_dm()("worker-2", "s", "c", "done")


async def test_send_dm_rejects_empty_recipient(env):
    with pytest.raises(ToolError):
        await bt.send_dm()("", "s", "c")


async def test_send_dm_rejects_unknown_type(env):
    with pytest.raises(ToolError):
        await bt.send_dm()("worker-2", "s", "c", "bogus")


async def test_send_dm_without_forum_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_FORUM_DIR, raising=False)
    monkeypatch.setenv("AGENT_ID", "worker-1")
    with pytest.raises(ToolError):
        await bt.send_dm()("worker-2", "s", "c")


async def test_send_dm_to_a_roster_member_succeeds(env, monkeypatch):
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2,worker-3")
    mid = await bt.send_dm()("worker-2", "s", "c")
    assert env.read_dms("worker-2")[0].id == mid


async def test_send_dm_to_an_unknown_recipient_is_rejected_when_a_roster_is_set(env, monkeypatch):
    # A swarm run always injects the roster; a `to` outside it is a typo that would otherwise land
    # in a phantom inbox nobody reads.
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2,worker-3")
    with pytest.raises(ToolError):
        await bt.send_dm()("worker-99", "s", "c")
    assert env.read_dms("worker-99") == []  # nothing was delivered


async def test_send_dm_is_permissive_when_no_roster_is_injected(env, monkeypatch):
    # A bare run (no SWARM_WORKER_IDS) skips roster validation — the substrate stays usable.
    monkeypatch.delenv(ENV_WORKER_IDS, raising=False)
    mid = await bt.send_dm()("some-peer", "s", "c")
    assert env.read_dms("some-peer")[0].id == mid


# ---- read_inbox ----------------------------------------------------------------------------

async def test_read_inbox_returns_dms_and_status(env):
    env.send_dm(sender="worker-2", to="worker-1", subject="hi", content="the body")
    env.set_status("worker-1", "on task")
    out = json.loads(await bt.read_inbox()())
    assert out["status"] == "on task"
    assert [m["content"] for m in out["messages"]] == ["the body"]
    assert out["messages"][0]["author"] == "worker-2"


async def test_read_inbox_since_returns_deltas(env):
    first = env.send_dm(sender="worker-2", to="worker-1", subject="m0", content="c")
    env.send_dm(sender="worker-2", to="worker-1", subject="m1", content="c")
    out = json.loads(await bt.read_inbox()(since=first.id))
    assert [m["subject"] for m in out["messages"]] == ["m1"]


async def test_read_inbox_reads_my_own_inbox_only(env):
    env.send_dm(sender="worker-2", to="worker-3", subject="not for me", content="c")
    out = json.loads(await bt.read_inbox()())
    assert out["messages"] == [] and out["status"] is None


# ---- set_status ----------------------------------------------------------------------------

async def test_set_status_writes_my_status(env):
    await bt.set_status()("decompiling the APK")
    assert env.get_status("worker-1") == "decompiling the APK"


async def test_set_status_overwrites(env):
    await bt.set_status()("first")
    await bt.set_status()("second")
    assert env.get_status("worker-1") == "second"


# ---- read_statuses (ticket 03: peer-visibility, the coordinator's status read) --------------

async def test_read_statuses_returns_every_peers_status(env, monkeypatch):
    # A coordinator needs to see the WHOLE team's status, not just its own (read_inbox's).
    monkeypatch.setenv(ENV_WORKER_IDS, "worker-1,worker-2,worker-3")
    env.set_status("worker-1", "coordinating")
    env.set_status("worker-2", "hooking RaspEngine")
    # worker-3 has set no status yet.
    out = json.loads(await bt.read_statuses()())
    assert out == {
        "worker-1": "coordinating",
        "worker-2": "hooking RaspEngine",
        "worker-3": None,
    }


async def test_read_statuses_needs_a_forum(monkeypatch):
    # It is forum-only (like the other DM/status tools): no FORUM_DIR → a clear ToolError.
    monkeypatch.delenv(ENV_FORUM_DIR, raising=False)
    monkeypatch.setenv("AGENT_ID", "worker-1")
    with pytest.raises(ToolError):
        await bt.read_statuses()()


# ---- spec wiring ---------------------------------------------------------------------------

def test_forum_tools_spec_exposes_all_seven_tools(env):
    spec = bt.forum_tools_spec()
    assert spec.name == bt.BOARD_MCP_NAME
    # 3 board + send_dm + read_inbox + set_status + read_statuses (ticket 03 peer-status read)
    assert len(spec.tools) == 7


def test_board_tools_spec_still_exposes_only_the_three_board_tools(env):
    # The standalone board demo keeps the lean 3-tool spec (no DM layer).
    assert len(bt.board_tools_spec().tools) == 3
