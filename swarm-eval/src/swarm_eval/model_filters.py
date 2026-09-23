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
from .messageboard import Message

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


def make_swarm_turn_filter(agent_id: str, *, forum: Forum | None = None) -> Filter:
    """Build the swarm worker's generate-filter: push this agent's unread DMs into its next turn,
    then run the shared `sweep_generate_filter` hygiene (system-merge + reasoning-strip).

    This is the ticket-01 "turn-injection plumbing" ticket 02 reuses: each turn it reads the DMs
    delivered to `agent_id` since the last one it injected (a per-run cursor held in the closure —
    the filter runs host-side in the worker's own process), appends them as a fresh user message
    so a targeted DM reaches the recipient without it having to poll, and advances the cursor so
    each DM is pushed exactly once. The injected message is not persisted into the bridge's
    transcript, so it never re-accumulates; the agent can re-fetch with `read_inbox`.

    `forum` defaults to `Forum.from_env()` — the conductor injects `FORUM_DIR`.
    """
    forum = forum or Forum.from_env()
    last: str | None = None  # deliver-once cursor: the id of the last DM already pushed

    async def swarm_turn_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        nonlocal last
        dms = forum.read_dms(agent_id, since=last)
        prepared = list(messages)
        if dms:
            last = dms[-1].id
            prepared = [*messages, ChatMessageUser(content=_dm_injection(dms))]
        return await sweep_generate_filter(model, prepared, tools, tool_choice, config)

    return swarm_turn_filter
