"""Self-label the TRUE served model in a run's metadata (env-hardening ticket 03).

The sandboxed Claude Code CLI self-identifies as a fixed Claude id (its built-in "You are powered
by …" line), regardless of which provider model Inspect actually serves and bills for this run.
So an Opus (or a cross-vendor Qwen) sweep run's transcript still claims to be Sonnet 4.5, and a
transcript reader is misled about who did the work. The Inspect log header already records the
served model correctly (`eval.model`); this module mirrors that truth into the run's metadata so a
reader never has to trust the CLI's self-identity — and, when the served model *is* a Claude id,
aligns the CLI's own self-identity to it.

Two cooperating mechanisms, one source of truth (the launcher's `--model`, i.e. what Inspect
bills):

- **Build-time stamp** — the launcher injects the served model it also hands `inspect eval
  --model` as `SERVED_MODEL`; the task reads it (`served_model`) and stamps `metadata`. Same
  string, one source (the launcher's `config.model`), so it cannot drift from `--model`. This is
  the path a unit test drives with a configured (incl. non-Claude) served model.
- **Runtime stamp** — `stamp_served_model` records `state.model` (Inspect's bound model, the
  ground truth it bills) into sample metadata for ANY invocation path, including a direct
  `inspect eval …` with no launcher (where `SERVED_MODEL` is unset). It only fills a value not
  already stamped, so the launcher's build-time value stays authoritative.
"""

from __future__ import annotations

import os

from inspect_ai.model import ModelName
from inspect_ai.solver import Generate, Solver, TaskState, solver

# The launcher injects the served provider model it also passes to `inspect eval --model`, so a
# run knows what Inspect bills without depending on the CLI's self-identity. Same string, one
# source (the launcher's `config.model`) — it cannot drift from `--model`.
ENV_SERVED_MODEL = "SERVED_MODEL"

# The metadata key every run stamps with the true served model (mirrors Inspect's `eval.model`).
METADATA_KEY = "served_model"

# The sandboxed CLI's built-in Claude identity — kept as the fallback for a non-Claude (or unknown)
# served model: there is no valid Claude id to hand the CLI, so it keeps this and the metadata
# stamp carries the truth. Matches the previously-hardcoded literal, so default behaviour is
# unchanged when no served model is known.
DEFAULT_CLI_IDENTITY = "claude-sonnet-4-5-20250929"


def served_model() -> str | None:
    """The provider model Inspect serves/bills this run, as the launcher injected it
    (`SERVED_MODEL`, mirroring the `--model` it also passes to `inspect eval`). `None` when unset
    (e.g. a direct `inspect eval` with no launcher) — the caller then omits the build-time stamp
    rather than asserting a wrong model, and the runtime `stamp_served_model` solver fills it from
    the bound model instead."""
    return os.environ.get(ENV_SERVED_MODEL) or None


def cli_identity_for(model: str | None) -> str:
    """The Claude id the sandboxed CC should self-identify as (`model_config`). When the served
    model is a Claude model, adopt its bare id so the CLI's "You are powered by …" line stops
    asserting a wrong Claude identity (ticket 03 criterion 3). For a non-Claude served model there
    is no valid Claude id to hand the CLI, so keep the built-in default and rely on the metadata
    stamp for the truth. `None`/unknown also keeps the default (behaviour unchanged)."""
    if model and ModelName(model).api == "anthropic":
        return ModelName(model).name
    return DEFAULT_CLI_IDENTITY


@solver
def stamp_served_model() -> Solver:
    """Record the model Inspect actually serves/bills this run (`state.model`, the ground truth) in
    `state.metadata['served_model']`, unless a truthful value is already present (the launcher's
    build-time stamp). Runs for every role/entrypoint, so no transcript is misled by the CLI's
    built-in identity even on a direct `inspect eval` with no launcher."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.metadata.setdefault(METADATA_KEY, str(state.model))
        return state

    return solve
