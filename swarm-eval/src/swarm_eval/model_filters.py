"""Shared inspect_swe generate-filters for the swarm-eval solvers.

Kept in the package (not duplicated per entrypoint) so a fix lands in one place. Reached from
any solver that stands on `inspect_swe.claude_code(filter=...)`.
"""

from __future__ import annotations

import re

from typing import Awaitable, Callable

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    Content,
    ContentReasoning,
    ContentText,
    GenerateConfig,
    GenerateInput,
    Model,
    ModelOutput,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from .forum import Forum
from .messageboard import Message, TYPE_FINDING, TYPE_SUCCESS

# Closed <think>…</think> / <thinking>…</thinking> blocks that some served models (Qwen3,
# DeepSeek-R1, etc.) leak as literal TEXT instead of structured reasoning. Left in place they
# pollute the transcript, waste context, can bury the final verdict line, and can desync the
# Claude Code CLI's stream parser (the "agent goes non-functional" failure mode). We strip
# closed blocks, then remove any stray/dangling tags. Non-greedy + DOTALL so multi-line
# reasoning is matched and back-references keep <think> paired with </think>.
_THINK_BLOCK_RE = re.compile(r"<(think|thinking)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
_THINK_STRAY_RE = re.compile(r"</?(?:think|thinking)\b[^>]*>", re.IGNORECASE)


def _strip_think_text(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_STRAY_RE.sub("", cleaned)
    # Drop leading blank lines left behind by a stripped leading block; keep interior text.
    return cleaned.lstrip("\n")


def _strip_think_content(content: str | list[Content]) -> str | list[Content]:
    """Strip leaked reasoning from a message's content (str or content-part list).

    Two forms of reasoning are removed: literal `<think>` TEXT (models that inline it) and
    structured `ContentReasoning` parts. The latter are dropped rather than kept so they do
    not accumulate — the Claude Code CLI round-trips a kept reasoning block back into the next
    request's history as a huge `<think>` text blob (observed: 28K-char blocks, ~1.9M cache-read
    tokens), which starves the turn budget. Reasoning is ephemeral scratch; nothing downstream
    (the self-report scorer reads final TEXT) needs it preserved.
    """
    if isinstance(content, str):
        return _strip_think_text(content)
    out: list[Content] = []
    for part in content:
        if isinstance(part, ContentReasoning):
            continue  # drop structured reasoning so it can't accumulate in CLI history
        if isinstance(part, ContentText):
            new_text = _strip_think_text(part.text)
            if new_text.strip():
                out.append(part.model_copy(update={"text": new_text}))
            # else: drop a part that was nothing but reasoning
        else:
            out.append(part)  # images / other parts pass through
    return out


def _merge_system(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Collapse multiple non-control system messages into one leading system message.

    Same semantics as the standalone `merge_system_messages`: a no-op unless there is more
    than one system message; `x-anthropic-` control messages are excluded from the merge.
    """
    system = [
        m for m in messages
        if isinstance(m, ChatMessageSystem) and not m.text.startswith("x-anthropic-")
    ]
    if len(system) <= 1:
        return list(messages)
    merged = ChatMessageSystem(content="\n\n".join(m.text for m in system))
    rest = [m for m in messages if not isinstance(m, ChatMessageSystem)]
    return [merged, *rest]


async def merge_system_messages(
    model: Model,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> ModelOutput | GenerateInput | None:
    """Collapse multiple system messages into one leading system message.

    Some served models (Qwen/Kimi) want a single leading system message; Claude does not care,
    so this is a no-op for Claude. Kept so the model sweep is a one-flag change (spec S2).
    The `x-anthropic-` system messages are the bridge's own control channel — left untouched.
    """
    system = [
        m for m in messages
        if isinstance(m, ChatMessageSystem) and not m.text.startswith("x-anthropic-")
    ]
    if len(system) <= 1:
        return None
    merged = ChatMessageSystem(content="\n\n".join(m.text for m in system))
    rest = [m for m in messages if not isinstance(m, ChatMessageSystem)]
    return GenerateInput(input=[merged, *rest], tools=tools, tool_choice=tool_choice, config=config)


async def sweep_generate_filter(
    model: Model,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> ModelOutput | GenerateInput | None:
    """Model-sweep generate filter: merge system messages AND strip leaked reasoning tags.

    Superset of `merge_system_messages`. Because reasoning tags leak in the model's OUTPUT
    (not just the input), this filter runs generation itself and returns a cleaned
    `ModelOutput` — the documented way for a bridge filter to substitute for default
    generation. It:
      1. merges non-control system messages (Qwen/Kimi want a single leading system msg);
      2. strips leaked <think>/<thinking> blocks from prior ASSISTANT history (context hygiene);
      3. generates, then strips the same tags from the OUTPUT before it reaches the CLI.

    A no-op strip for models that emit structured reasoning (Claude) — those never carry
    literal tags in text, so the regex simply matches nothing.
    """
    # (1) + (2): build a clean input (system merged, prior assistant reasoning stripped).
    prepared: list[ChatMessage] = []
    for m in _merge_system(messages):
        if isinstance(m, ChatMessageAssistant):
            prepared.append(m.model_copy(update={"content": _strip_think_content(m.content)}))
        else:
            prepared.append(m)

    # (3): generate ourselves so we can post-process the output text. `tools` here is the
    # ToolInfo list the bridge already converted — the same value the default path forwards
    # to model.generate() when a filter returns GenerateInput.
    output = await model.generate(
        input=prepared,
        tools=tools,
        tool_choice=tool_choice,
        config=config,
    )
    for choice in output.choices:
        choice.message.content = _strip_think_content(choice.message.content)
    # `completion` is a stored field (set once at construction), not derived live from
    # message content — the self-report scorer reads it, so strip it too.
    if output.completion:
        output.completion = _strip_think_text(output.completion)
    return output


# ---- ticket 01: per-turn push of unread DMs (the "turn-injection plumbing") ----------------

# A bridge generate-filter: same signature the bridge calls on every model turn.
Filter = Callable[
    [Model, list[ChatMessage], list[ToolInfo], ToolChoice | None, GenerateConfig],
    Awaitable[ModelOutput | GenerateInput | None],
]


def _dm_injection(dms: list[Message]) -> str:
    """The user-message text that carries the unread DMs into a turn. A DM is targeted at this
    agent, so it is framed as top-priority — ticket 02 will add the board's unread index BELOW
    this (the ticket's "ranked above board notes"); this builder is the top section of that
    composition."""
    lines = [
        "[FORUM · direct messages] You have new direct message(s) sent to you since your last "
        "turn. They are addressed to you specifically — read and act on them before other work:"
    ]
    for m in dms:
        lines.append(f"- from {m.author} — [{m.type}] {m.subject}: {m.content}")
    lines.append("(Re-read your inbox any time with the `read_inbox` tool.)")
    return "\n".join(lines)


# The high-signal message types the board-index push escalates above the `note`/`giveup` chatter,
# so a peer's breakthrough isn't buried under routine notes. Kept in taxonomy order (success then
# finding) so the ranking is stable regardless of the order posts happened to land in.
_HIGH_SIGNAL = (TYPE_SUCCESS, TYPE_FINDING)


def _board_index_injection(entries: list[dict[str, str]]) -> str | None:
    """The user-message text that carries the unread board **index** into a turn — subjects only,
    ranked BELOW the DM section (ticket 02). Bodies stay pull-on-demand (`read_message(ids)`) so a
    long board never force-feeds context. `success`/`finding` posts are surfaced in a prominent
    high-signal block above the routine `note`/`giveup` chatter, so a peer's breakthrough isn't
    buried. `entries` is the `Board.list` index view (`{id, subject, author, ts, type}`) of what is
    unread for this agent; returns None when there is nothing to show (so the caller can skip it)."""
    if not entries:
        return None
    high = [e for e in entries if e["type"] in _HIGH_SIGNAL]
    low = [e for e in entries if e["type"] not in _HIGH_SIGNAL]
    lines = [
        "[FORUM · board] New message(s) posted to the shared board since you last looked "
        "(subjects only — pull a full body with `read_message(ids)`). Consult these before "
        "duplicating a peer's work:"
    ]
    if high:
        lines.append("  High-signal — a peer's finding/success, read these first:")
        for e in high:
            lines.append(f"  ★ [{e['type']}] {e['id']} — from {e['author']}: {e['subject']}")
    if low:
        lines.append("  Other notes:")
        for e in low:
            lines.append(f"  · [{e['type']}] {e['id']} — from {e['author']}: {e['subject']}")
    return "\n".join(lines)


def make_swarm_turn_filter(agent_id: str, *, forum: Forum | None = None) -> Filter:
    """Build the swarm worker's generate-filter: push this agent's unread DMs AND the unread board
    index into its next turn, then run the shared `sweep_generate_filter` hygiene (system-merge +
    reasoning-strip).

    Two turn-injections, folded into ONE trailing user message so the turn stays coherent, with the
    DMs ranked above the board index (a DM is targeted at this agent; the board is broadcast):

    - **DMs (ticket 01)** — the DMs delivered to `agent_id` since the last turn it injected, as
      full bodies (DMs are low-volume and targeted), so a targeted message reaches the recipient
      without it having to poll.
    - **Board index (ticket 02)** — the *subjects only* of board messages posted since this agent
      last saw the board, with `success`/`finding` surfaced above `note`/`giveup`, so N runs read
      and react to each other instead of degenerating into N independent runs. Bodies stay
      pull-on-demand (`read_message(ids)`) to keep context clean, and the agent's OWN posts are
      skipped (it already knows them) though the cursor still advances past them.

    Each stream has its own per-run deliver-once cursor held in the closure (the filter runs
    host-side in the worker's own process), advanced so each DM/board message is pushed exactly
    once. The injected message is not persisted into the bridge's transcript, so it never
    re-accumulates; the agent can re-fetch with `read_inbox` / `list_messages`.

    `forum` defaults to `Forum.from_env()` — the conductor injects `FORUM_DIR`.
    """
    forum = forum or Forum.from_env()
    last_dm: str | None = None      # deliver-once cursor: id of the last DM already pushed
    last_board: str | None = None   # deliver-once cursor: id of the last board post already seen

    async def swarm_turn_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        nonlocal last_dm, last_board
        sections: list[str] = []

        dms = forum.read_dms(agent_id, since=last_dm)
        if dms:
            last_dm = dms[-1].id
            sections.append(_dm_injection(dms))

        index = forum.board.list(since=last_board)
        if index:
            # Advance the cursor past every new post (including this agent's own) so nothing is
            # pushed twice; but only a PEER's posts are shown — an agent needn't be told its own.
            last_board = index[-1]["id"]
            board_text = _board_index_injection([e for e in index if e["author"] != agent_id])
            if board_text:
                sections.append(board_text)

        prepared = list(messages)
        if sections:
            prepared = [*messages, ChatMessageUser(content="\n\n".join(sections))]
        return await sweep_generate_filter(model, prepared, tools, tool_choice, config)

    return swarm_turn_filter
