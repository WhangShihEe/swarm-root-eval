# Seed: yaml-config-extension

Context-seed for a future grilling session. **Not a ticket yet.** Downstream: the README's
"Running custom evals (YAML)" section is written against current state with an inline `<WIP>`
that this workstream resolves.

## Goal

Extend the YAML so an eval is **fully replicable from config**: currently the device + app + prompt
live in YAML, but the **model, number of models/workers, and run settings** (time limit, budget,
caps) are **CLI flags**, not config. Fold them into YAML. Likely split the YAML into 2+ files
**separated by permission** — exact refactor still to be designed.

## Why

Replicability + a clean permission boundary (what a user may change vs what is fixed harness policy).

## Facts found (this session)

- Device specs live in `devices/*.yaml` and are already **two-tier**:
  - top-level scalars consumed by the bash device layer (`name`, `system_image`, `api`,
    `target_apk`, `provision`, `frida`, `writable_system`, ...);
  - a nested `app:` block consumed only by the Python harness (`target.py::load_target`):
    `package`, `launch_activity`, `frida_mode`, and mission slots `objective`/`success_signal`/
    `details` — or `prompt: <name>` inheriting shared slots from `devices/prompts/*.yaml`.
- Run knobs are CLI-only today: `single_agent.py`/`swarm.py` take `--model`, `--workers`,
  `--time-limit`, `--budget`, `--cap`.
- There is **no** permission-split mechanism yet; the only capability split is the
  `writable_system` launch-profile boolean and the static-vs-dynamic agent distinction.

## Open design questions (for the grill)

- What are the permission tiers, and where does the cut line go (per-file? per-block?)?
- Which run knobs become YAML vs stay CLI overrides?
- Backward-compat / migration for the 11 existing specs.

## Downstream effect on docs

The README YAML section documents current shape now; the split + replicability knobs land here
and then the `<WIP>` note is replaced.
