"""Ticket 05a — standalone messageboard demo (two hand-started bridged runs).

The proof that the board substrate + `bridged_tools` work end to end, before any launcher
(05b): start this task **twice**, with distinct `AGENT_ID`s but the same `BOARD_DIR`/`SWARM_ID`,
and each bridged Claude Code agent posts to and reads the other's messages on the shared board.
No launcher, no arbiter, no broker, no device.

    # terminal 1
    AGENT_ID=worker-1 inspect eval board_agent.py --model anthropic/claude-sonnet-4-5-...
    # terminal 2 (same BOARD_DIR + SWARM_ID → same board)
    AGENT_ID=worker-2 inspect eval board_agent.py --model anthropic/claude-sonnet-4-5-...

Then inspect the board: `ls "$BOARD_DIR/${SWARM_ID:-demo}"` shows one JSON file per message;
each carries `{ts, author, subject, type, content}` with the author stamped host-side.

`BOARD_DIR` defaults to `swarm-eval/board/`, `SWARM_ID` to `demo`, and `AGENT_ID` to a random
`agent-<hex>` if unset (so two runs still differ) — but set `AGENT_ID` explicitly for a legible
transcript. The board tools run **host-side**, so this needs no special sandbox toolchain (the
default docker image, as in the smoke slice, is enough)."""

import logging
import os
import uuid
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_swe import claude_code

from swarm_eval.board_tools import BOARD_MCP_NAME, ENV_AGENT_ID, board_tools_spec
from swarm_eval.messageboard import ENV_BOARD_DIR, ENV_SWARM_ID, Board
from swarm_eval.model_filters import merge_system_messages

logger = logging.getLogger(__name__)

# Demo defaults — the launcher (05b) injects these per run; hand-started, we fall back so the
# two runs land on one shared board with no ceremony.
DEFAULT_BOARD_DIR = str(Path(__file__).resolve().parent / "board")
DEFAULT_SWARM_ID = "demo"


def resolve_env() -> tuple[str, str, str]:
    """Resolve (and persist into `os.environ`) the board coordinates for this run.

    Persisting matters: the board `bridged_tools` run host-side and read these vars via
    `Board.from_env()`, so the values this entrypoint chooses must be visible there. A missing
    `AGENT_ID` gets a random `agent-<hex>` so two hand-started runs never collide on author."""
    board_root = os.environ.setdefault(ENV_BOARD_DIR, DEFAULT_BOARD_DIR)
    swarm_id = os.environ.setdefault(ENV_SWARM_ID, DEFAULT_SWARM_ID)
    agent_id = os.environ.get(ENV_AGENT_ID)
    if not agent_id:
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        os.environ[ENV_AGENT_ID] = agent_id
    return board_root, swarm_id, agent_id


def build_prompt(agent_id: str) -> str:
    return f"""You are agent **{agent_id}**, one of several agents collaborating on a shared
messageboard. You have three board tools (an MCP server named `{BOARD_MCP_NAME}`):
`post_message(subject, content, type)`, `list_messages(since)`, and `read_message(ids)`. Your
author identity is stamped automatically — you cannot post as anyone else.

Do this, in order:
1. Call `list_messages` to see what other agents have already said (subjects only).
2. Post a short `note` introducing yourself as {agent_id}.
3. If any messages from OTHER agents are in the index, `read_message` their bodies and post one
   more `note` acknowledging by name what one of them said.
4. Stop. In your final message, say who you saw on the board and what you posted."""


@scorer(metrics=[accuracy(), stderr()])
def posted_to_board():
    """Host-side machine check for the demo: green iff this run's `AGENT_ID` actually left a
    message on the shared board. (Whether it *read* others is proven by inspecting the board /
    transcript — reads leave no board trace.)"""

    async def score(state: TaskState, target: Target) -> Score:
        agent_id = os.environ.get(ENV_AGENT_ID)
        board = Board.from_env()
        mine = [e for e in board.list() if e["author"] == agent_id]
        if mine:
            return Score(
                value=CORRECT,
                answer=f"{len(mine)} message(s)",
                explanation=f"{agent_id} posted {len(mine)} message(s) to the board",
            )
        return Score(value=INCORRECT, explanation=f"{agent_id} posted nothing to the board")

    return score


@task
def board_agent():
    board_root, swarm_id, agent_id = resolve_env()
    Board.from_env().ensure()
    logger.info("board demo: agent=%s swarm=%s board=%s", agent_id, swarm_id, board_root)
    return Task(
        dataset=MemoryDataset([Sample(input=build_prompt(agent_id), target="posted")]),
        solver=claude_code(
            model_config="claude-sonnet-4-5-20250929",
            filter=merge_system_messages,
            bridged_tools=[board_tools_spec()],
        ),
        scorer=posted_to_board(),
        sandbox="docker",
    )
