"""Shared inspect_swe generate-filters for the swarm-eval solvers.

Kept in the package (not duplicated per entrypoint) so a fix lands in one place. Reached from
any solver that stands on `inspect_swe.claude_code(filter=...)`.
"""

from __future__ import annotations

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    GenerateConfig,
    GenerateInput,
    Model,
    ModelOutput,
)
from inspect_ai.tool import ToolChoice, ToolInfo


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
