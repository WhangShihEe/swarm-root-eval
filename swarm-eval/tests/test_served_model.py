"""Env-hardening ticket 03 — the served-model self-label. A run must record the TRUE served
model (what Inspect bills) so a transcript reader is not misled by the sandboxed CLI's built-in
identity (Sonnet 4.5). These cover the shared primitives: reading the launcher-injected served
model, the CLI-identity alignment rule, and the runtime metadata-stamp solver."""

import types

import pytest

from swarm_eval.served_model import (
    DEFAULT_CLI_IDENTITY,
    ENV_SERVED_MODEL,
    METADATA_KEY,
    cli_identity_for,
    served_model,
    stamp_served_model,
)


def test_served_model_reads_the_injected_env(monkeypatch):
    monkeypatch.setenv(ENV_SERVED_MODEL, "openai-api/azure/qwen-2.5-72b-instruct")
    assert served_model() == "openai-api/azure/qwen-2.5-72b-instruct"


def test_served_model_is_none_when_unset(monkeypatch):
    # Unset (a direct `inspect eval` with no launcher) → None, so the caller omits the build-time
    # stamp rather than asserting a wrong model.
    monkeypatch.delenv(ENV_SERVED_MODEL, raising=False)
    assert served_model() is None


def test_cli_identity_tracks_a_claude_served_model():
    # Criterion 3: when the served model IS a Claude id, the CLI self-identifies as it (bare id, no
    # provider prefix) instead of a wrong Claude id.
    assert cli_identity_for("anthropic/claude-opus-4-8") == "claude-opus-4-8"


def test_cli_identity_falls_back_for_a_non_claude_served_model():
    # A non-Claude served model has no valid Claude id to hand the CLI → keep the default and rely
    # on the metadata stamp for the truth.
    assert cli_identity_for("openai-api/azure/qwen-2.5-72b-instruct") == DEFAULT_CLI_IDENTITY


def test_cli_identity_falls_back_when_unknown():
    assert cli_identity_for(None) == DEFAULT_CLI_IDENTITY


def _state(model: str):
    # The solver only touches state.metadata and reads state.model (a str-able ModelName; a plain
    # str stands in fine here).
    return types.SimpleNamespace(metadata={}, model=model)


@pytest.mark.asyncio
async def test_stamp_solver_records_the_bound_model():
    # The runtime safety net: mirror what Inspect binds/bills, incl. a non-Claude model, for any
    # invocation path (even a direct `inspect eval` with no launcher-injected SERVED_MODEL).
    state = _state("openai-api/azure/qwen-2.5-72b-instruct")
    await stamp_served_model()(state, generate=None)
    assert state.metadata[METADATA_KEY] == "openai-api/azure/qwen-2.5-72b-instruct"


@pytest.mark.asyncio
async def test_stamp_solver_does_not_override_the_build_time_stamp():
    # The launcher's build-time value is authoritative; the solver only fills a missing one.
    state = _state("anthropic/claude-sonnet-4-5-20250929")
    state.metadata[METADATA_KEY] = "anthropic/claude-opus-4-8"
    await stamp_served_model()(state, generate=None)
    assert state.metadata[METADATA_KEY] == "anthropic/claude-opus-4-8"
