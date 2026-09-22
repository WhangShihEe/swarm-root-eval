# Seed: codebase-cleanup

Context-seed for a future grilling session. **Not a ticket yet.** Low priority — do before sending
the repo out publicly.

## Goal

A general cleanup pass before the codebase is public:
1. **Linting** — add and run linters (see primer below).
2. **De-bloat comments** — a lot of the codebase references internal "tickets" in comments; strip
   the ones that are noise to an outside reader.
3. **Rename to android-swarm** — the public surface is branded `android-swarm`, but the directory
   (`swarm-root-eval`) and the Python package (`swarm_eval`) still use the old name. Decide whether
   to rename internally (churn) and, if so, do it as an expand/contract or one-shot rename.

## Why

First impressions for a public repo + a resume showcase. Linting catches sloppiness cheaply;
ticket-comment bloat leaks internal process; the name mismatch is confusing.

## Linting primer (author is new to linting)

Linters are tools that read your code (without running it) and flag style issues, likely bugs, and
inconsistencies, so you don't fix them by hand or in review. For this repo:
- **Python** (`swarm-eval/`): `ruff` — fast, does both linting and formatting; run `ruff check` and
  `ruff format`. Configure in `pyproject.toml`.
- **Bash** (`bin/`, scripts): `shellcheck` — catches quoting bugs, unset vars, portability issues.
Optionally wire both into a pre-commit hook and/or CI (there is no CI config today).

## Facts found (this session)

- Two language surfaces: Python package under `swarm-eval/src/swarm_eval/`; bash under `bin/`
  (`broker`, `_*.sh` libs, `env-up`/`env-down`, `verify`, `doctor`).
- No CI config exists yet. Tests: bash under `tests/`, Python under `swarm-eval/tests/`.
- Public branding = android-swarm; internal `swarm_eval` intentionally left as-is for now
  (rename tracked here).

## Downstream effect on docs

None blocking. If the internal rename happens, docs and paths update accordingly.
