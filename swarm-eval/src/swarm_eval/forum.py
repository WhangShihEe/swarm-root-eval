"""The forum — the swarm's coordination substrate (swarm-improvements ticket 01).

One directory tree per swarm run, living **under the run's own log dir** so the coordination
record ships with the transcripts as one artifact (no post-run copy step):

    logs/<swarm-id>/forum/
      messageboard/            # the broadcast board (a `Board`) — every agent reads/writes it
      dms/<worker-id>/         # one inbox per worker: DMs *to* it (a `Board`) + its status.txt

Both the board and every inbox reuse the messageboard's file-per-message + atomic-rename
mechanics (`Board`), so a concurrent read never sees a half-written message and two runs never
contend on a single file. Author is host-stamped from the injected `AGENT_ID` (the tool layer
does the stamping, exactly as for the board) — a sender cannot forge another's identity, and a
recipient is addressed by *which inbox* a message lands in, not by any field it could spoof.

This module is the pure substrate (no Inspect dependency), like `messageboard`/`broker_client`:
a `Forum` over a directory, provable in isolation. The bridged agent tools that expose it
(`send_dm`/`read_inbox`/`set_status` alongside the board tools) live in `board_tools`; the
per-turn push of unread DMs into an agent's next turn lives in `model_filters`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from .messageboard import Board, BoardError, Message, safe_slug

# The launcher (conductor) injects the absolute forum root per run; `from_env` reads it. Unlike
# the legacy board's `BOARD_DIR`+`SWARM_ID` pair (root + a swarm subdir, still used by the
# standalone board demo), the forum path is fully resolved by the launcher — one var, no joining.
ENV_FORUM_DIR = "FORUM_DIR"
# The swarm roster (this run's peers, comma-separated), injected by the conductor. Lives here — a
# low-level forum coordinate — so the board tools can validate a DM recipient without importing the
# conductor (which imports them); the conductor re-exports it for its own callers.
ENV_WORKER_IDS = "SWARM_WORKER_IDS"

MESSAGEBOARD_DIRNAME = "messageboard"
DMS_DIRNAME = "dms"
# The status lives inside the worker's inbox dir but is NOT a `.json` message file, so `Board`'s
# `*.json` glob never mistakes it for a DM. Plain text: a short "currently working on …" line.
STATUS_FILENAME = "status.txt"


class Forum:
    """A handle onto one swarm's forum directory. Cheap to construct; several handles may point at
    the same tree (N runs sharing a forum). Not a cache — every read hits the filesystem, so a
    handle always sees other runs' latest posts, DMs, and statuses."""

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self.root = Path(root)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Forum:
        """Build the forum a run belongs to from its injected env (`FORUM_DIR`). Raises BoardError
        (the substrate's error type) if it is missing, so a misconfigured run fails loudly instead
        of silently coordinating into a phantom directory."""
        env = os.environ if environ is None else environ
        root = env.get(ENV_FORUM_DIR)
        if not root:
            raise BoardError(
                f"forum needs {ENV_FORUM_DIR} in the environment (got {ENV_FORUM_DIR}={root!r})"
            )
        return cls(root)

    @classmethod
    def from_env_or_none(cls, environ: Mapping[str, str] | None = None) -> Forum | None:
        """The forum from `FORUM_DIR`, or None when it is unset — so a caller shared with the
        legacy board path (e.g. the board tools, also used by the standalone `board_agent` demo)
        can prefer the forum when present and fall back otherwise, without catching an exception."""
        env = os.environ if environ is None else environ
        return cls(env[ENV_FORUM_DIR]) if env.get(ENV_FORUM_DIR) else None

    # ---- the broadcast board ---------------------------------------------------------------

    @property
    def board(self) -> Board:
        """The shared broadcast board — a `Board` at `forum/messageboard/`. Every agent posts and
        reads here; the arbiter posts its `done` verdict here (`conductor`)."""
        return Board(self.root / MESSAGEBOARD_DIRNAME)

    # ---- per-worker inboxes (DMs) ----------------------------------------------------------

    def _inbox_path(self, worker_id: str) -> Path:
        return self.root / DMS_DIRNAME / safe_slug(worker_id)

    def inbox(self, worker_id: str) -> Board:
        """The inbox of `worker_id` — a `Board` at `forum/dms/<worker-id>/` holding the DMs *sent
        to* it. Reused board mechanics: a DM is one message file whose `author` is the sender
        (host-stamped) and whose location (this dir) is the recipient."""
        return Board(self._inbox_path(worker_id))

    def send_dm(
        self, *, sender: str, to: str, subject: str, content: str, type: str = "note"
    ) -> Message:
        """Deliver a DM into `to`'s inbox, authored by `sender`. `sender` is stamped by the caller
        (the tool layer takes it from `AGENT_ID`, never from agent input — same integrity as the
        board). Returns the posted `Message`. Raises BoardError on an unknown message type."""
        return self.inbox(to).post(author=sender, subject=subject, content=content, type=type)

    def read_dms(self, worker_id: str, since: str | None = None) -> list[Message]:
        """The full DMs in `worker_id`'s inbox, oldest first — the whole body of each (DMs are
        low-volume and targeted, so unlike the broadcast board there is no two-tier index tax).
        `since` is a message-id cursor: pass the id of the last DM seen to get only newer ones —
        the same delta semantics the per-turn push uses to deliver each DM exactly once."""
        inbox = self.inbox(worker_id)
        return inbox.read([e["id"] for e in inbox.list(since=since)])

    # ---- per-worker status ------------------------------------------------------------------

    def set_status(self, worker_id: str, status: str) -> None:
        """Set `worker_id`'s short "currently working on …" status. Written to
        `forum/dms/<worker-id>/status.txt` via a temp file + atomic rename, so a concurrent reader
        (a peer or a coordinator) never sees a half-written status. Overwrites the previous one —
        a status is the *current* state, not an append-only log (the board is the log)."""
        path = self._inbox_path(worker_id) / STATUS_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{STATUS_FILENAME}.tmp"
        tmp.write_text(status, encoding="utf-8")
        os.replace(tmp, path)  # atomic on the same filesystem — no partial reads

    def get_status(self, worker_id: str) -> str | None:
        """`worker_id`'s current status, or None if it has set none yet."""
        path = self._inbox_path(worker_id) / STATUS_FILENAME
        return path.read_text(encoding="utf-8") if path.exists() else None

    # ---- lifecycle --------------------------------------------------------------------------

    def ensure(self, worker_ids: Iterable[str] = ()) -> None:
        """Create the forum tree up front (idempotent): the board dir and one inbox dir per worker
        in `worker_ids`. The launcher does this once per swarm so a worker's first DM has a home
        even before that worker has posted anything; a run may also call it defensively."""
        self.board.path.mkdir(parents=True, exist_ok=True)
        for worker_id in worker_ids:
            self._inbox_path(worker_id).mkdir(parents=True, exist_ok=True)
