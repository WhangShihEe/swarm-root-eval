"""Ticket 05a — the `bridged_tools` layer over the board. These are the host-side tools each
run exposes to its bridged agent. Hermetic: BOARD_DIR/SWARM_ID/AGENT_ID are set in the env
(exactly as the 05b launcher injects them), a tmp dir stands in for BOARD_DIR — no sandbox."""

import json

import pytest
from inspect_ai.tool import ToolError

from swarm_eval import board_tools as bt
from swarm_eval.messageboard import Board, board_dir


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Inject the per-run env the launcher provides, pointing the board at a tmp dir."""
    monkeypatch.setenv("BOARD_DIR", str(tmp_path))
    monkeypatch.setenv("SWARM_ID", "swarm-test")
    monkeypatch.setenv("AGENT_ID", "worker-1")
    return tmp_path


async def test_post_message_writes_and_returns_id(env):
    post = bt.post_message()
    mid = await post("hello", "the body", "note")
    board = Board(board_dir(env, "swarm-test"))
    (msg,) = board.read([mid])
    assert msg.subject == "hello"
    assert msg.content == "the body"
    assert msg.type == "note"


async def test_post_message_stamps_author_from_agent_id_not_input(env):
    # The execute signature has no `author` param — it is stamped host-side from AGENT_ID.
    post = bt.post_message()
    mid = await post("s", "c")
    board = Board(board_dir(env, "swarm-test"))
    assert board.read([mid])[0].author == "worker-1"


async def test_post_message_author_cannot_be_forged_by_a_second_run(env, monkeypatch):
    # Author integrity: two runs with distinct AGENT_IDs each stamp their own id, and neither
    # can post as the other — there is no author input to forge.
    board = Board(board_dir(env, "swarm-test"))
    a = await bt.post_message()("from one", "c1")
    monkeypatch.setenv("AGENT_ID", "worker-2")
    b = await bt.post_message()("from two", "c2")
    got = {m.subject: m.author for m in board.read([a, b])}
    assert got == {"from one": "worker-1", "from two": "worker-2"}


async def test_post_message_forbids_done_for_workers(env):
    with pytest.raises(ToolError):
        await bt.post_message()("s", "c", "done")


async def test_post_message_allows_done_when_arbiter(env):
    # The arbiter (05b) builds its post tool with allow_done=True.
    mid = await bt.post_message(allow_done=True)("verdict", "success", "done")
    board = Board(board_dir(env, "swarm-test"))
    assert board.read([mid])[0].type == "done"


async def test_post_message_rejects_unknown_type(env):
    with pytest.raises(ToolError):
        await bt.post_message()("s", "c", "bogus")


async def test_post_message_without_agent_id_is_an_error(tmp_path, monkeypatch):
    # A misconfigured run must not post anonymously — no author, no post.
    monkeypatch.setenv("BOARD_DIR", str(tmp_path))
    monkeypatch.setenv("SWARM_ID", "swarm-test")
    monkeypatch.delenv("AGENT_ID", raising=False)
    with pytest.raises(ToolError):
        await bt.post_message()("s", "c")


async def test_list_messages_returns_index_only(env):
    await bt.post_message()("hello", "the secret body")
    out = json.loads(await bt.list_messages()())
    assert len(out) == 1
    assert set(out[0]) == {"id", "subject", "author", "ts", "type"}
    assert "content" not in out[0]


async def test_list_messages_since_returns_deltas(env):
    first = await bt.post_message()("m0", "c")
    await bt.post_message()("m1", "c")
    delta = json.loads(await bt.list_messages()(since=first))
    assert [e["subject"] for e in delta] == ["m1"]


async def test_read_message_returns_full_bodies(env):
    a = await bt.post_message()("sa", "body A")
    b = await bt.post_message()("sb", "body B")
    out = json.loads(await bt.read_message()([a, b]))
    assert {m["subject"]: m["content"] for m in out} == {"sa": "body A", "sb": "body B"}
    assert all("id" in m for m in out)


async def test_read_message_accepts_a_single_id_string(env):
    a = await bt.post_message()("sa", "body A")
    out = json.loads(await bt.read_message()(a))
    assert out[0]["content"] == "body A"


async def test_two_tier_read_list_then_read_only_wanted_bodies(env, monkeypatch):
    # The headline acceptance: an agent sees all subjects, then pulls only the bodies it wants.
    await bt.post_message()("boring", "ignore me")
    monkeypatch.setenv("AGENT_ID", "worker-2")
    await bt.post_message()("interesting", "the payload")

    index = json.loads(await bt.list_messages()())
    assert {e["subject"] for e in index} == {"boring", "interesting"}
    wanted = [e["id"] for e in index if e["subject"] == "interesting"]
    bodies = json.loads(await bt.read_message()(wanted))
    assert [m["content"] for m in bodies] == ["the payload"]


def test_board_tools_spec_exposes_the_three_tools(env):
    spec = bt.board_tools_spec()
    assert spec.name == bt.BOARD_MCP_NAME
    assert len(spec.tools) == 3


def test_board_tools_spec_arbiter_variant_allows_done(env):
    # Smoke: the arbiter spec is a distinct, valid spec (allow_done wired through the builder).
    spec = bt.board_tools_spec(allow_done=True)
    assert len(spec.tools) == 3
