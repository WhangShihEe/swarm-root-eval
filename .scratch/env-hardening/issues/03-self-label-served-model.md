# 03: A run's log tells you which model actually ran

**What to build:** Reading any run's log identifies the true served model, so a model sweep is
legible. Today the sandboxed Claude Code self-identifies as a fixed model (Sonnet 4.5) regardless of
which model is served and billed (e.g. Opus 4.8), so a transcript reader is misled about who did the
work. Do this before the model sweep runs.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

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
