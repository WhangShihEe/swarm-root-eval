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
