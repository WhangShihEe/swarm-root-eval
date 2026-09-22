# 02: Public README + visual assets (android-swarm)

**What to build:** The public GitHub README for **android-swarm** — a compact, quickstart-first
page whose showcase weight is carried by visuals — plus the visual assets it embeds. A new user
can copy-paste their way to a working RASP-dummy run from the fold; a resume reader gets the hook,
the logo, and one diagram that explains the whole experiment.

**Blocked by:** 01 (the README links into `bin/README.md` and `swarm-eval/README.md` and points
coding agents at the refreshed `CLAUDE.md`).

**Status:** ready-for-agent

- [ ] Green-ant **SVG** logo in `docs/assets/` (clean icon, android-green; reusable as favicon +
      GitHub social preview).
- [ ] **Excalidraw** architecture diagram in `docs/assets/` (agent scaffolds the `.excalidraw` JSON
      and exports SVG/PNG; author does the taste pass). Depicts: one APK in -> broker leases rooted
      emulator(s) -> N workers, each a bridged Claude Code agent in its own Inspect env -> linked only
      by the shared message board -> host-side arbiter reads the board -> verdict.
- [ ] README: hero logo + `android-swarm` title + 2-3 sentence capability-probe hook.
- [ ] README: architecture diagram + a few sentences on *why the Inspect wiring is unusual*
      (full version lives in `swarm-eval/README.md`).
- [ ] README: **Quickstart** that runs the RASP-dummy target out of the box —
      `source bin/env.sh` -> `bin/doctor` -> `bin/broker start` ->
      `bin/broker acquire --spec devices/rasp_dummy.yaml` ->
      `uv run python single_agent.py devices/rasp_dummy.yaml`.
- [ ] README: **Running custom evals (YAML)** — documents the current two-tier device-spec (top-level
      scalars for the bash device layer vs the nested `app:` block for the Python harness) and how to
      swap APKs. Mark inline `<WIP>` with a context note: the replicability goal is to fold
      `--model/--workers/--time-limit/--budget` (currently CLI flags) into YAML, and the open design is
      how to split the YAML by permission. (See `.scratch/yaml-config-extension/`.)
- [ ] README: one-line **"For coding agents"** pointer to `CLAUDE.md`, `CONTEXT.md`, `docs/agents/`.
- [ ] README: terse **Architecture** section linking to `bin/README.md` and `swarm-eval/README.md`.
- [ ] README: inline `<WIP>` **demo GIF** placeholder with a caption-spec of what it should show
      (agent driving a live emulator + the board updating live). Produced later via
      `.scratch/demo-app-gif/`.
- [ ] Public surface branded **android-swarm**; internal package `swarm_eval` and paths left
      unchanged (rename deferred — see `.scratch/codebase-cleanup/`).
