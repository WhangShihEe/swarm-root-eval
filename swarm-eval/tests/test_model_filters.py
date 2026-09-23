"""swarm-improvements ticket 01 — the per-turn DM push (`make_swarm_turn_filter`), the
turn-injection plumbing ticket 02 reuses. Hermetic: the Model is a fake that just records the
input it is handed, and the forum is a tmp dir — no bridge, no provider, no sandbox."""

import pytest
from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)

from swarm_eval.forum import Forum
from swarm_eval.model_filters import make_swarm_turn_filter


class FakeModel:
    """Records the message list each `generate` is handed (what the model would actually see)."""

    def __init__(self) -> None:
        self.seen: list[list] = []

    async def generate(self, input, tools, tool_choice, config):
        self.seen.append(list(input))
        return ModelOutput.from_content(model="fake", content="ok")


@pytest.fixture
def forum(tmp_path):
    f = Forum(tmp_path / "forum")
    f.ensure(["worker-1", "worker-2"])
    return f


def _base_messages():
    return [ChatMessageSystem(content="sys"), ChatMessageUser(content="hi")]


async def _call(filt, model, messages):
    return await filt(model, messages, [], None, GenerateConfig())


async def test_unread_dm_is_pushed_as_a_trailing_user_message(forum):
    forum.send_dm(sender="worker-2", to="worker-1", subject="look here", content="the payload")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())

    seen = model.seen[-1]
    assert len(seen) == 3  # sys, user, injected user
    injected = seen[-1]
    assert isinstance(injected, ChatMessageUser)
    assert "look here" in injected.text and "the payload" in injected.text
    assert "worker-2" in injected.text  # names the sender


async def test_no_dms_means_no_injection(forum):
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()
    await _call(filt, model, _base_messages())
    assert len(model.seen[-1]) == 2  # unchanged: sys, user


async def test_each_dm_is_pushed_exactly_once(forum):
    forum.send_dm(sender="worker-2", to="worker-1", subject="first", content="c")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())      # turn 1: injects "first"
    assert "first" in model.seen[-1][-1].text

    await _call(filt, model, _base_messages())      # turn 2: nothing new
    assert len(model.seen[-1]) == 2

    forum.send_dm(sender="worker-2", to="worker-1", subject="second", content="c")
    await _call(filt, model, _base_messages())      # turn 3: injects only "second"
    injected = model.seen[-1][-1]
    assert "second" in injected.text and "first" not in injected.text


async def test_only_my_dms_are_pushed(forum):
    forum.send_dm(sender="worker-2", to="worker-2", subject="not mine", content="c")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()
    await _call(filt, model, _base_messages())
    assert len(model.seen[-1]) == 2  # worker-1 got nothing


async def test_filter_resolves_forum_from_env_when_not_passed(forum, monkeypatch):
    from swarm_eval.forum import ENV_FORUM_DIR

    monkeypatch.setenv(ENV_FORUM_DIR, str(forum.root))
    forum.send_dm(sender="worker-2", to="worker-1", subject="env-routed", content="c")
    filt = make_swarm_turn_filter("worker-1")  # no forum= → from_env
    model = FakeModel()
    await _call(filt, model, _base_messages())
    assert "env-routed" in model.seen[-1][-1].text


# ---- ticket 02: per-turn push of the unread board index (below DMs) -------------------------


def _board_post(forum, *, author, subject, content="body", type="note"):
    """Post directly to the shared board (bypass the agent tool) for a hermetic fixture."""
    return forum.board.post(author=author, subject=subject, content=content, type=type)


async def test_unread_board_index_is_pushed_as_a_trailing_user_message(forum):
    _board_post(forum, author="worker-2", subject="detector at checkRoot", content="the body")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())

    seen = model.seen[-1]
    assert len(seen) == 3  # sys, user, injected user
    injected = seen[-1]
    assert isinstance(injected, ChatMessageUser)
    assert "detector at checkRoot" in injected.text  # the subject
    assert "worker-2" in injected.text               # the author


async def test_board_injection_is_subject_index_only_not_bodies(forum):
    _board_post(forum, author="worker-2", subject="a subject", content="SECRET_BODY_TEXT")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())

    injected = model.seen[-1][-1].text
    assert "a subject" in injected
    assert "SECRET_BODY_TEXT" not in injected  # bodies stay pull-on-demand (read_message)


async def test_success_and_finding_are_surfaced_above_notes(forum):
    _board_post(forum, author="worker-2", subject="just-a-note", type="note")
    _board_post(forum, author="worker-3", subject="a-real-finding", type="finding")
    _board_post(forum, author="worker-2", subject="the-win", type="success")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())

    text = model.seen[-1][-1].text
    # high-signal posts (success/finding) rank above the note in the injected index
    assert text.index("the-win") < text.index("just-a-note")
    assert text.index("a-real-finding") < text.index("just-a-note")


async def test_each_board_message_is_pushed_exactly_once(forum):
    _board_post(forum, author="worker-2", subject="first-post")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())        # turn 1: injects first-post
    assert "first-post" in model.seen[-1][-1].text

    await _call(filt, model, _base_messages())        # turn 2: nothing new
    assert len(model.seen[-1]) == 2

    _board_post(forum, author="worker-2", subject="second-post")
    await _call(filt, model, _base_messages())        # turn 3: only second-post
    injected = model.seen[-1][-1].text
    assert "second-post" in injected and "first-post" not in injected


async def test_my_own_board_posts_are_not_pushed_back_to_me(forum):
    _board_post(forum, author="worker-1", subject="my-own-post")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())
    assert len(model.seen[-1]) == 2  # I already know my own post; no injection


async def test_my_own_post_still_advances_the_cursor(forum):
    """My own post is skipped for display but must not re-surface a peer's earlier post — the
    cursor still advances past it, so only genuinely-new peer posts appear next turn."""
    _board_post(forum, author="worker-1", subject="mine")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())        # skips my own; no injection
    assert len(model.seen[-1]) == 2

    _board_post(forum, author="worker-2", subject="peer-post")
    await _call(filt, model, _base_messages())        # only the peer's new post
    assert "peer-post" in model.seen[-1][-1].text


async def test_dms_rank_above_the_board_index_when_both_present(forum):
    forum.send_dm(sender="worker-2", to="worker-1", subject="dm-subject", content="dm-body")
    _board_post(forum, author="worker-3", subject="board-subject")
    filt = make_swarm_turn_filter("worker-1", forum=forum)
    model = FakeModel()

    await _call(filt, model, _base_messages())

    seen = model.seen[-1]
    assert len(seen) == 3  # both fold into one injected user message
    text = seen[-1].text
    assert text.index("dm-subject") < text.index("board-subject")  # DMs on top
