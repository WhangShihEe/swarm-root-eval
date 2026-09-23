# 03: Run-knobs into the eval config + CLI override + device-override + 3-source prompt

**What to build:** Make an eval config the single source that fully specifies a replicable run. Fold the
run knobs — `model`, `workers` as a `[{role: dynamic, count: N}]` list, and the caps/budget/limits —
into the eval config as **defaults**, with any CLI flag **overriding** the config value for that run (so
`--model` and `--workers` still drive the model sweep and swarm sizing without editing the file). Add a
device-setting **override whitelist**: an eval config may override only `writable_system` and `headless`
(precedence eval > device > built-in default), applied at the run level (not per-worker). Assemble the
worker's mission prompt by **appending three sources in order**: the worker role file (role instructions +
default objective) → the app file (app-specific instructions/notes) → the device file (device notes).

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] An eval config with `model`, `workers: [{role: dynamic, count: N}]`, and caps/budget runs with **no** CLI run-flags and reproduces the intended run.
- [ ] A CLI `--model` / `--workers` (and the other run flags) overrides the eval-config value for that run; the config value stands when the flag is absent.
- [ ] An eval config may set `writable_system` and/or `headless` and it overrides the device file's value (eval > device > default); other device scalars are not overridable from the eval config.
- [ ] The worker mission prompt is the concatenation of worker-role notes, then app notes, then device notes, in that order.
- [ ] Both integration commands pass from `configs/evals/rasp_dummy.yaml` both with and without CLI overrides (verified in the `.eval`).
