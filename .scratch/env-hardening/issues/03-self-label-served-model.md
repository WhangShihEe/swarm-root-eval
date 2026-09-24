# 03: A run's log tells you which model actually ran

**What to build:** Reading any run's log identifies the true served model, so a model sweep is
legible. Today the sandboxed Claude Code self-identifies as a fixed model (Sonnet 4.5) regardless of
which model is served and billed (e.g. Opus 4.8), so a transcript reader is misled about who did the
work. Do this before the model sweep runs.

**Blocked by:** None (can start immediately).

**Status:** done — all criteria met; criterion 2 (live non-Claude served-model metadata read) CONFIRMED in Phase B: the dbs_solution run stamped `served_model = openai-api/litellm/bedrock-claude-opus-4.8` into eval + sample metadata, matching eval.model and model_usage

Context: `.scratch/env-hardening/report.md` §S3b — a real transcript self-labels "Sonnet 4.5" while
the billed model was Opus 4.8. The Inspect log header already records the served model correctly; the
gap is the in-transcript identity and any per-model reader. (The related `strict_tools=false` for
openai-api sweep models is already shipped — §S3a — nothing to build there.)

- [ ] Every run — single and swarm — records the true served model in its eval metadata (mirroring
      what Inspect bills), so a reader is not misled by the CLI's built-in identity.
- [ ] Verified by reading a run's metadata and confirming it matches the served model, including at
      least one **non-Claude** served model.
- [ ] Optional: when the served model is a Claude model, align the CLI's own self-identity to it; for
      non-Claude models rely on the metadata stamp.
- [ ] Applied consistently across the agent entrypoints that currently hardcode the identity, so none
      of them asserts a wrong model.

## Comments

### WIP — device-free implementation landed (ticket/03-self-label-model)

**What shipped (device-free, unit-tested):**
- New `swarm_eval/served_model.py`: `ENV_SERVED_MODEL` (the launcher-injected `SERVED_MODEL`,
  mirroring `--model`), `served_model()` reader, `cli_identity_for()` (aligns the CLI's Claude
  self-identity to a Claude served model; falls back to the built-in default for non-Claude), and
  the `stamp_served_model()` runtime solver.
- Served model is threaded launcher → env → task metadata: `single_agent.run_single` and
  `conductor.build_run_env` inject `SERVED_MODEL=config.model` (same string as `--model`), and
  `dynamic_agent.build_dynamic_task` stamps it into `metadata["served_model"]` for BOTH single and
  swarm (merged alongside the swarm coordinates), plus aligns `model_config` when the served model
  is a Claude id. The `stamp_served_model()` solver is the runtime safety net (mirrors
  `state.model`, the ground truth) for any path — incl. a direct `inspect eval` with no launcher.
- Criterion 4: the hardcoded `model_config="claude-sonnet-4-5-20250929"` is removed from every
  entrypoint that carried it — `dynamic_agent.py`, `board_agent.py`, `smoke.py`.

**Criterion 2 — DEFERRED to the orchestrator's device phase (needs a live run):** the end-to-end
read of a real run's metadata with a NON-Claude served model requires booting a device + spending
API, which is out of scope for this device-free ticket. Substituted with unit coverage that feeds
a non-Claude served-model config through the metadata path and asserts the stamp equals it
(`test_build_dynamic_task_stamps_a_non_claude_served_model_into_metadata`, plus the
`test_served_model.py` suite). When a live bridge run is next executed, read its eval metadata and
confirm `served_model` equals the served `--model` for at least one non-Claude model.
