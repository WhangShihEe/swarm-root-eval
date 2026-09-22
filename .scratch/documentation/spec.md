# Documentation

Produce the public-facing and handover documentation for the project (public repo name:
**android-swarm**), as the internship wraps up. Two audiences: new users of the pipeline,
and a resume/showcase reader.

## Principles

- README is **quickstart-first** and **compact**. The showcase is carried by visuals
  (green-ant logo, Excalidraw architecture diagram, demo GIF), not by long prose. Assume
  almost no one reads past the fold.
- **Deep detail migrates out of the README** into area docs (`bin/README.md`,
  `swarm-eval/README.md`), which the README links to.
- Everything **unbuilt is marked inline `<WIP>`** with a short context note, so a *future
  agent* (not necessarily the author) can extend that section later. This applies to the
  YAML-replicability/permission-split section and the demo GIF.
- Docs describe **current, running state**. The multi-agent swarm already exists and runs
  (`swarm.py` -> `conductor.py`, message board, arbiter); planned enhancements are `<WIP>`.

## Tickets

1. Internal docs accuracy (no blockers)
2. Public README + visual assets (blocked by 1)
3. Private HOTO (blocked by 2)

## Related workstream seeds (not tickets)

Context-seeds for future grilling sessions live under sibling slugs:
`.scratch/swarm-improvements/`, `.scratch/yaml-config-extension/`, `.scratch/demo-app-gif/`,
`.scratch/llm-judge/`, `.scratch/codebase-cleanup/`. The already-scoped physical-device work
lives at `.scratch/physical-harness/` (spec + 5 tickets) and is referenced by the HOTO.
