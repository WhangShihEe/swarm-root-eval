"""`bridged_tools` over the forum — the swarm's comms tools (ticket 05a; forum/DMs from
swarm-improvements 01).

Each agent-run exposes these to its bridged Claude Code agent via `inspect_swe`'s
`bridged_tools`. They run **host-side**, in the run's own process — so a worker sandbox needs no
network for coordination (adb still does, 04). Two families, one `board` MCP server:

- **Board (broadcast):** `post_message`/`list_messages`/`read_message`. Two-tier read keeps agent
  context clean — `list_messages` hands back the subject index only, `read_message` pulls full
  bodies on demand. The board resolves the forum's `messageboard/` when a forum is injected
  (`FORUM_DIR`), falling back to the legacy `BOARD_DIR`/`SWARM_ID` board for the standalone
  `board_agent` demo.
- **DMs (targeted, ticket 01):** `send_dm`/`read_inbox`/`set_status` over the forum's
  `dms/<worker-id>/` inboxes — forum-only (they require `FORUM_DIR`).

**`author` is stamped host-side** from the run's injected `AGENT_ID` — the tools take no author
input, so one run cannot forge another's author (a DM's recipient is likewise the inbox it lands
in, not a spoofable field). `done` is reserved for the arbiter (05b): `post_message`/`send_dm`
forbid it; the arbiter builds its board tools with `allow_done=True`.
"""

from __future__ import annotations

import json
import os

from inspect_ai.agent import BridgedToolsSpec
from inspect_ai.tool import Tool, ToolError, tool

from .forum import ENV_WORKER_IDS, Forum
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


def _or_tool_error(build):
    """Run a `from_env` constructor, turning the substrate's `BoardError` (missing/invalid config)
    into a `ToolError` the agent sees — one place, so `_board`/`_forum` don't each repeat it."""
    try:
        return build()
    except BoardError as e:
        raise ToolError(str(e)) from e


def _board() -> Board:
    # Prefer the forum (the swarm path, ticket 01): its board is `forum/messageboard/`. Fall back
    # to the legacy `BOARD_DIR`/`SWARM_ID` board when no forum is injected — the standalone
    # `board_agent` demo still runs on that pair.
    forum = Forum.from_env_or_none()
    if forum is not None:
        return forum.board
    return _or_tool_error(Board.from_env)


def _forum() -> Forum:
    """The forum this run belongs to. Unlike the board (which has a legacy fallback for the demo),
    the DM/status tools are swarm-only — they require `FORUM_DIR` and error clearly without it."""
    return _or_tool_error(Forum.from_env)


def _roster() -> set[str] | None:
    """This run's known peers (from the injected `SWARM_WORKER_IDS`), or None when no roster was
    injected. Used to validate a DM recipient: a swarm run always has one, so an unknown `to` is a
    typo, not a valid address; a run without a roster (a bare test) skips the check."""
    raw = os.environ.get(ENV_WORKER_IDS)
    if not raw:
        return None
    return {w for w in raw.split(",") if w}


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


@tool
def send_dm() -> Tool:
    async def execute(to: str, subject: str, content: str, type: str = "note") -> str:
        """Send a DIRECT message to one specific agent's inbox (not the whole board).

        Use this for targeted coordination — nudging one peer's direction, handing off a lead —
        instead of broadcasting to everyone on the board. The recipient sees it pushed into its
        next turn (ranked above the board) and can also pull it with `read_inbox`. Your author
        identity is stamped automatically — you cannot send as anyone else.

        Args:
            to: The recipient agent id (e.g. "worker-2"), exactly as it appears in the roster.
            subject: A short one-line summary.
            content: The full message body.
            type: One of "note" (default), "finding", or "success". ("done" is reserved for the
                arbiter and cannot be sent.)

        Returns:
            The id of the delivered message.
        """
        if type == "done":
            raise ToolError('message type "done" is reserved for the arbiter')
        if not to or not to.strip():
            raise ToolError("send_dm needs a recipient agent id (`to`)")
        roster = _roster()
        if roster is not None and to not in roster:
            # A DM to an unknown id would land in a phantom inbox nobody reads (the message lost
            # silently); fail loudly with the valid recipients instead.
            raise ToolError(
                f"unknown DM recipient {to!r}; the swarm's agents are: "
                f"{', '.join(sorted(roster))}"
            )
        try:
            msg = _forum().send_dm(
                sender=_agent_id(), to=to, subject=subject, content=content, type=type
            )
        except BoardError as e:
            raise ToolError(str(e)) from e
        return msg.id

    return execute


@tool
def read_inbox() -> Tool:
    async def execute(since: str | None = None) -> str:
        """Read your DM inbox: the direct messages sent to you, plus your own current status.

        DMs are also pushed into your turn automatically as they arrive; use this to re-check or
        to page through them. Full bodies are returned (DMs are targeted and low-volume, so there
        is no subject-only index tier like the board's).

        Args:
            since: Optional message-id cursor. When given, only DMs delivered after it are
                returned — pass the id of the last DM you saw to poll for what's new.

        Returns:
            A JSON object `{"status": <your current status or null>, "messages": [full DMs]}`,
            messages oldest first, each `{id, ts, author, subject, type, content}`.
        """
        forum = _forum()
        me = _agent_id()
        dms = forum.read_dms(me, since=since)
        return json.dumps(
            {"status": forum.get_status(me), "messages": [m.to_dict() for m in dms]},
            ensure_ascii=False,
        )

    return execute


@tool
def set_status() -> Tool:
    async def execute(status: str) -> str:
        """Set your short "currently working on …" status, visible to your peers and coordinators.

        Keep it to one line describing your current focus (e.g. "hooking RootBeer.isRooted via
        frida"). It overwrites your previous status — it reflects what you are doing NOW, not a
        log (post durable findings to the board).

        Args:
            status: The one-line status text.

        Returns:
            A short confirmation.
        """
        _forum().set_status(_agent_id(), status)
        return "status set"

    return execute


@tool
def read_statuses() -> Tool:
    async def execute() -> str:
        """Read EVERY agent's current one-line status — who on the swarm is working on what.

        Unlike `read_inbox` (which returns only your own status), this reports every peer's latest
        `set_status` line, so you can see the whole team's focus at a glance and spot stuck or
        duplicated work. Especially useful as a coordinator directing the others. Statuses are the
        CURRENT state, not a log — durable findings live on the board.

        Returns:
            A JSON object mapping each agent id to its current status string (or null if it has
            not set one yet).
        """
        forum = _forum()
        roster = _roster()
        # Report the injected roster (every known peer, even one that has set no status yet) when we
        # have it; otherwise let the forum discover whoever has an inbox (a bare test/demo).
        ids = sorted(roster) if roster is not None else None
        return json.dumps(forum.statuses(ids), ensure_ascii=False)

    return execute


def board_tools(*, allow_done: bool = False) -> list[Tool]:
    """The three board tools for one run. `allow_done=True` for the arbiter run (05b), which is
    the only participant permitted to post the reserved `done` verdict."""
    return [post_message(allow_done=allow_done), list_messages(), read_message()]


def forum_tools(*, allow_done: bool = False) -> list[Tool]:
    """The full forum toolset a swarm worker gets (ticket 01): the three board tools plus the
    direct-messaging + status layer (`send_dm`/`read_inbox`/`set_status`/`read_statuses`). The
    board tools fall back to the legacy board when no forum is injected; the DM/status tools are
    forum-only. `read_statuses` (ticket 03) exposes every PEER's status so a coordinator can see
    who is doing what — `read_inbox` only returns the caller's own."""
    return [
        *board_tools(allow_done=allow_done),
        send_dm(), read_inbox(), set_status(), read_statuses(),
    ]


def board_tools_spec(*, allow_done: bool = False) -> BridgedToolsSpec:
    """The `bridged_tools` entry a solver hands to `inspect_swe.claude_code(bridged_tools=[...])`
    — one MCP server (`BOARD_MCP_NAME`) exposing the three board tools to the sandboxed agent.
    Used by the standalone `board_agent` demo; swarm workers use `forum_tools_spec`."""
    return BridgedToolsSpec(name=BOARD_MCP_NAME, tools=board_tools(allow_done=allow_done))


def forum_tools_spec(*, allow_done: bool = False) -> BridgedToolsSpec:
    """The `bridged_tools` entry for a swarm worker: one MCP server (`BOARD_MCP_NAME`) exposing
    the board tools AND the DM/status tools (ticket 01). Kept under the same server name so the
    agent reaches everything as `mcp__board_*`."""
    return BridgedToolsSpec(name=BOARD_MCP_NAME, tools=forum_tools(allow_done=allow_done))
