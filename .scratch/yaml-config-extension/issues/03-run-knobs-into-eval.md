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

**Status:** done

- [x] An eval config with `model`, `workers: [{role: dynamic, count: N}]`, and caps/budget runs with **no** CLI run-flags and reproduces the intended run. `load_run_config` reads `model`, the `workers` roster (`worker_count` sums the entries' counts), and a `limits:` block (`time_limit`/`working_limit`/`message_limit`/`budget`/`cap`); both launchers' `build_config` consume them. `configs/evals/rasp_dummy.yaml` carries all three.
- [x] A CLI `--model` / `--workers` (and the other run flags) overrides the eval-config value for that run; the config value stands when the flag is absent. All run-knob flags default to `None`; `_pick(cli, cfg, default)` applies CLI > config > built-in default. Smoke-verified: `single_agent … --model <proxy>` ran with the override while `time_limit: 1800` came from the config.
- [x] An eval config may set `writable_system` and/or `headless` and it overrides the device file's value (eval > device > default); other device scalars are not overridable from the eval config. `_load_eval_config` reads ONLY those two keys off the eval top level; `TargetConfig.env_up_args()` emits `--writable-system`/`--frida-only` and `--window`/`--no-window` (which win over the device spec in `bin/env-up`), forwarded through `broker acquire` by both launchers.
- [x] The worker mission prompt is the concatenation of worker-role notes, then app notes, then device notes, in that order. `mission._briefing` appends `(worker_notes, details, device_notes)`, skipping any blank source; the worker notes come from the (first) role file's `notes`, the device notes from the device file's `notes`.
- [x] Both integration commands pass from `configs/evals/rasp_dummy.yaml` both with and without CLI overrides (verified in the `.eval`). Bounded smoke of all four shapes: single/no-flags (config path OK; agent can't auth — this env has no `ANTHROPIC_API_KEY` for the config's default model, an environment limit not a harness defect), single/`--model` override (clean scored `.eval`), swarm/no-`--workers` (config count 1 → full launch→arbitrate→release), swarm/`--workers 2` (2 devices acquired → override + acquire-forwarding). A full uncapped SUCCESS-level run (as ticket 02 did) needs a model this env can auth.

**Implementation notes (for ticket 04):**
- Run knobs live on `RunConfig` (`swarm_eval/target.py`), read by `load_run_config` — separate from
  `load_target` (target/device/mission), since they steer scheduling, not the APK. A legacy device
  yaml (no top-level `device:` key) yields an empty `RunConfig`, so the launchers' built-in defaults
  stand — no regression for the not-yet-migrated 10.
- The eval-config schema ticket 04's README documents: `model:` (str), `workers:` (a
  `[{role, count}]` list; `worker_count` = Σcount), `limits:` (nested block), and the device-override
  whitelist `writable_system:`/`headless:` at the top level (exactly those two).
- The `workers` shape is decoded in ONE place (`_worker_entries` → `(role, count)` pairs); the role
  roster and the count roster both derive from it (no drift). One role ships (`dynamic`); a per-role
  mission (each worker carrying its own role's notes) is a later ticket — today all workers share the
  first role's notes.
