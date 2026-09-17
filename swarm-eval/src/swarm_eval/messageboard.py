"""Host-side shared messageboard — the swarm's comms substrate (ticket 05a).

The swarm is N separate Inspect runs that collaborate through this **external, host-side,
append-only, one-file-per-message directory** (ADR-0002). One file per message is the broker's
no-append-races idiom: concurrent runs never contend on a single file, and a reader either sees
a whole message or not at all (writes land via an atomic rename). Reached from each run through
`inspect_swe` `bridged_tools` (see `board_tools.py`) — never Inspect's per-sample `store`, never
raw `host.docker.internal`.

This module is the pure substrate: a `Board` over a directory, with no Inspect dependency, so
it is provable in isolation (like `broker_client` on the device side). The board doubles as the
swarm's **shared memory**; the subject-line index (`list`) is what keeps a long board from
blowing up each agent's context — bodies are pulled on demand (`read`).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# The message taxonomy — named so downstream (the 05b arbiter rubric) matches on these tokens
# by constant, not by re-typing the string (one taxonomy change here reaches every reader).
# `done` is reserved for the arbiter (05b) — the board accepts it (the arbiter posts through the
# same substrate), but the worker-facing `post_message` tool forbids it so a worker can't fake
# termination. See `board_tools.py`.
TYPE_NOTE = "note"
TYPE_FINDING = "finding"
TYPE_SUCCESS = "success"
TYPE_GIVEUP = "giveup"
TYPE_DONE = "done"
MESSAGE_TYPES = (TYPE_NOTE, TYPE_FINDING, TYPE_SUCCESS, TYPE_GIVEUP, TYPE_DONE)

# Env vars the launcher (05b) injects per run; `from_env` reads them to locate the board.
ENV_BOARD_DIR = "BOARD_DIR"
ENV_SWARM_ID = "SWARM_ID"

# Filename-safe author slug — everything else collapses to '_'. The JSON `author` stays exact.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class BoardError(RuntimeError):
    """A board operation was invalid (e.g. an unknown message type) or its config was missing."""


@dataclass(frozen=True)
class Message:
    """One posted message. `id` is the filename stem (a sortable handle); the on-disk JSON body
    is the other five fields (`body()`). `index_entry()` is the light view `list` returns."""

    id: str
    ts: str
    author: str
    subject: str
    type: str
    content: str

    def body(self) -> dict[str, str]:
        """The five fields written to disk — `id` is carried by the filename, not the body."""
        return {
            "ts": self.ts,
            "author": self.author,
            "subject": self.subject,
            "type": self.type,
            "content": self.content,
        }

    def index_entry(self) -> dict[str, str]:
        """The subject-line index view: everything but the (potentially large) `content`."""
        return {
            "id": self.id,
            "subject": self.subject,
            "author": self.author,
            "ts": self.ts,
            "type": self.type,
        }

    def to_dict(self) -> dict[str, str]:
        """Full view (index fields + `content`) — what `read` hands back to an agent."""
        return {"id": self.id, **self.body()}


def board_dir(root: os.PathLike[str] | str, swarm_id: str) -> Path:
    """The per-swarm board directory: `BOARD_DIR/<swarm-id>/`."""
    return Path(root) / swarm_id


def _safe_author(author: str) -> str:
    return _UNSAFE.sub("_", author) or "anon"


class Board:
    """A handle onto one swarm's board directory. Cheap to construct; several handles may point
    at the same dir (that is exactly N runs sharing a board). Not a cache — every `list`/`read`
    hits the filesystem, so a handle always sees other runs' latest posts."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = Path(path)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Board:
        """Build the board a run belongs to from its injected env: `BOARD_DIR/<SWARM_ID>/`.

        Raises BoardError if either var is missing so a misconfigured run fails loudly instead
        of silently posting into the wrong (or a phantom) directory."""
        env = os.environ if environ is None else environ
        root = env.get(ENV_BOARD_DIR)
        swarm_id = env.get(ENV_SWARM_ID)
        if not root or not swarm_id:
            raise BoardError(
                f"messageboard needs {ENV_BOARD_DIR} and {ENV_SWARM_ID} in the environment "
                f"(got {ENV_BOARD_DIR}={root!r}, {ENV_SWARM_ID}={swarm_id!r})"
            )
        return cls(board_dir(root, swarm_id))

    def ensure(self) -> None:
        """Create the board dir (idempotent). The launcher does this once per swarm; a run may
        call it defensively."""
        self.path.mkdir(parents=True, exist_ok=True)

    def post(self, *, author: str, subject: str, content: str, type: str = "note") -> Message:
        """Append one message and return it. `author` is passed by the caller (the tool stamps
        it host-side from AGENT_ID — never from agent input). Written to a temp file then
        atomically renamed, so a concurrent `list`/`read` never observes a half-written file."""
        if type not in MESSAGE_TYPES:
            raise BoardError(f"unknown message type {type!r}; expected one of {MESSAGE_TYPES}")

        # Filename = `<ts>-<author>-<shortid>.json` (the ticket's format). The ts token is a
        # compact, colon-free, fixed-width UTC stamp — human-legible under `ls` yet lexically
        # sortable, so ids sort chronologically; the uuid shortid breaks any sub-microsecond
        # ties. The body keeps the full ISO-8601 ts.
        now = datetime.now(timezone.utc)
        stamp = f"{now:%Y%m%dT%H%M%S}.{now.microsecond:06d}Z"
        msg = Message(
            id=f"{stamp}-{_safe_author(author)}-{uuid.uuid4().hex[:8]}",
            ts=now.isoformat(),
            author=author,
            subject=subject,
            type=type,
            content=content,
        )
        self.ensure()
        payload = json.dumps(msg.body(), ensure_ascii=False, indent=2)
        final = self.path / f"{msg.id}.json"
        tmp = self.path / f".{msg.id}.json.tmp"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, final)  # atomic on the same filesystem — no partial reads
        return msg

    def _entries(self) -> list[tuple[str, Path]]:
        """(id, path) for every message file, sorted by id (== chronological). Skips the
        in-flight `.*.tmp` files a concurrent post may be writing."""
        files = [p for p in self.path.glob("*.json") if not p.name.startswith(".")]
        return sorted(((p.stem, p) for p in files), key=lambda t: t[0])

    def _load(self, id: str, path: Path) -> Message:
        body = json.loads(path.read_text(encoding="utf-8"))
        return Message(id=id, **body)

    def list(self, since: str | None = None) -> list[dict[str, str]]:
        """The index only — `{id, subject, author, ts, type}` per message, chronological. This
        is the two-tier read's cheap tier: the whole board is never force-fed into context.
        `since` is a message id cursor; only messages posted after it are returned (deltas)."""
        return [
            self._load(id, path).index_entry()
            for id, path in self._entries()
            if since is None or id > since
        ]

    def read(self, ids: Iterable[str] | str) -> list[Message]:
        """Full bodies for the named messages, in the requested order. Missing ids are skipped
        (a stale id from another run is not fatal). Accepts a single id or an iterable of ids."""
        want = [ids] if isinstance(ids, str) else list(ids)
        out: list[Message] = []
        for id in want:
            path = self.path / f"{id}.json"
            if path.exists():
                out.append(self._load(id, path))
        return out
