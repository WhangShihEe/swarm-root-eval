"""`bridged_tools` over the messageboard — the swarm's comms tools (ticket 05a).

Each agent-run exposes these to its bridged Claude Code agent via `inspect_swe`'s
`bridged_tools`. They run **host-side**, in the run's own process, against the shared board dir
(`Board.from_env`) — so a worker sandbox needs no network for the board (adb still does, 04).

Two-tier read keeps agent context clean: `list_messages` hands back the subject index only,
`read_message` pulls full bodies on demand. **`author` is stamped host-side** from the run's
injected `AGENT_ID` — the tools take no author input, so one run cannot forge another's author.
`done` is reserved for the arbiter (05b): the worker `post_message` forbids it; the arbiter
builds its tools with `allow_done=True`.
"""

from __future__ import annotations

import json
import os

from inspect_ai.agent import BridgedToolsSpec
from inspect_ai.tool import Tool, ToolError, tool

from .messageboard import Board, BoardError

# MCP server name — the agent sees the tools as `mcp__board_post_message`, etc.
BOARD_MCP_NAME = "board"

# The launcher (05b) injects this per run; the tool stamps it as the message author.
ENV_AGENT_ID = "AGENT_ID"


def _agent_id() -> str:
    author = os.environ.get(ENV_AGENT_ID)
    if not author:
        # A run with no AGENT_ID would post anonymously and break author integrity — refuse.
        raise ToolError(
            f"{ENV_AGENT_ID} is not set for this run; cannot attribute a message (launcher "
            f"misconfiguration)"
        )
    return author


def _board() -> Board:
    try:
        return Board.from_env()
    except BoardError as e:
        raise ToolError(str(e)) from e


@tool
def post_message(allow_done: bool = False) -> Tool:
    async def execute(subject: str, content: str, type: str = "note") -> str:
        """Post a message to the shared swarm messageboard.

        Use this to coordinate with the other agents: share notes, findings, or announce that
        you succeeded or are giving up. Your author identity is stamped automatically — you
        cannot post as anyone else.

        Args:
            subject: A short one-line summary (shown to every agent in the board index).
            content: The full message body (other agents read this on demand).
            type: One of "note" (default), "finding", "success" (you achieved the objective),
                or "giveup" (you cannot make further progress).

        Returns:
            The id of the posted message.
        """
        if type == "done" and not allow_done:
            raise ToolError('message type "done" is reserved for the arbiter')
        try:
            msg = _board().post(
                author=_agent_id(), subject=subject, content=content, type=type
            )
        except BoardError as e:
            raise ToolError(str(e)) from e
        return msg.id

    return execute


@tool
def list_messages() -> Tool:
    async def execute(since: str | None = None) -> str:
        """List the swarm messageboard index (subjects only — not the full bodies).

        This is the cheap tier: it returns one line per message so you can scan what the swarm
        has said without pulling every body into your context. Read the bodies you care about
        with `read_message`.

        Args:
            since: Optional message id cursor. When given, only messages posted after it are
                returned — pass the id of the last message you saw to poll for what's new.

        Returns:
            A JSON array of `{id, subject, author, ts, type}`, oldest first.
        """
        return json.dumps(_board().list(since=since), ensure_ascii=False)

    return execute


@tool
def read_message() -> Tool:
    async def execute(ids: list[str]) -> str:
        """Read the full body of one or more messageboard messages by id.

        This is the second tier of the read: after scanning the index with `list_messages`,
        pull just the bodies you want.

        Args:
            ids: The message ids to read (from `list_messages`).

        Returns:
            A JSON array of full messages `{id, ts, author, subject, type, content}`, in the
            order requested. Ids that no longer exist are silently skipped.
        """
        msgs = _board().read(ids)
        return json.dumps([m.to_dict() for m in msgs], ensure_ascii=False)

    return execute


def board_tools(*, allow_done: bool = False) -> list[Tool]:
    """The three board tools for one run. `allow_done=True` for the arbiter run (05b), which is
    the only participant permitted to post the reserved `done` verdict."""
    return [post_message(allow_done=allow_done), list_messages(), read_message()]


def board_tools_spec(*, allow_done: bool = False) -> BridgedToolsSpec:
    """The `bridged_tools` entry a solver hands to `inspect_swe.claude_code(bridged_tools=[...])`
    — one MCP server (`BOARD_MCP_NAME`) exposing the three board tools to the sandboxed agent."""
    return BridgedToolsSpec(name=BOARD_MCP_NAME, tools=board_tools(allow_done=allow_done))
