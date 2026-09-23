# 04: Migrate the remaining specs + retire the legacy path + README

**What to build:** Finish the refactor (contract step). Convert the other 10 targets into
`configs/{devices,apps,evals}/` entries (device provisioning file + app file + a default eval that
references them with a single `dynamic` worker), matching the rasp_dummy reference conversion. Remove the
legacy combined-device-yaml code path and its tests so `configs/evals/<name>.yaml` is the only way to
launch a run. Strip any remaining `frida_mode:` lines from the migrated yamls. Rewrite the README
"Running custom evals (YAML)" section to describe the new `configs/` shape (resolving the inline WIP note
the seed anticipated).

**Blocked by:** 03.

**Status:** done

- [x] All 11 targets run from `configs/evals/<name>.yaml`; no target still relies on a combined device-yaml. The 10 corpus targets each got a `configs/apps/<name>.yaml` (owns `target_apk` + `package`/`label`, `prompt: get-running-disable-rasp`), a provisioning-only `configs/devices/<name>.yaml`, and a `configs/evals/<name>.yaml` (app + device + `workers: [{dynamic, 1}]` + model/limits defaults). `package`/`label`/`target_apk` carried over verbatim from the deleted `devices/*.yaml`; parking_sg's `objective_append` preserved. The whole `devices/` tree (11 combined yamls + `devices/prompts/`) was deleted.
- [x] The legacy combined-device-yaml code path and its tests are removed; nothing reads an `app:` block out of a device file anymore. `target.py` lost `_load_device_yaml` + `LEGACY_PROMPTS_DIR`; `load_target`/`load_run_config` now REJECT any config without a top-level `device:` key (shared `_read_eval_config` guard). `_mission_fields`/`_target_from_app` dropped their `prompts_dir` param (one prompts dir now). `broker_client.DEFAULT_SPEC` → the eval config; a new `DEFAULT_DEVICE_SPEC` backs `acquire`. The legacy-only tests were deleted and replaced with rejection tests; all fixture specs repointed to `configs/`.
- [x] No `frida_mode:` key remains in any config yaml. Guarded by `test_no_config_yaml_carries_frida_mode` (parses every `configs/**/*.yaml`). Remaining grep hits are comment prose documenting the deliberate absence.
- [x] The README "Running custom evals (YAML)" section documents the `configs/{devices,apps,workers,evals}/` model (a table + the 3-source prompt order), the CLI-override rule (CLI > config > built-in default), and the device-override whitelist (`writable_system`/`headless` only). The seed's inline `<WIP>` note is resolved.
- [x] Both integration commands pass from the migrated `configs/evals/rasp_dummy.yaml` (verified in the `.eval`, with `--model openai-api/litellm/bedrock-claude-opus-4.8` since this env has no `ANTHROPIC_API_KEY`): single-agent status success, self_report accuracy 1.0, 30 tool calls, 0 tool errors, `RASP_BYPASS: SUCCESS`; swarm (N=3) acquired 3 devices (all `configs/devices/rasp_dummy.yaml`), verdict SUCCESS (worker-3), 0 tool errors across workers, all 3 devices released. 178 unit tests green.

**Implementation notes (contract complete):**
- The bash device layer needed no change: `spec_target_apk` (ticket 01, apk-agnostic) returns empty for the provisioning-only device specs, and the launchers always forward the app's APK via `--target-apk`, so the broker/pool path is unaffected.
- Out-of-AC tidy-up done alongside: `bin/README.md` + the `bin/*` script header examples, `swarm-eval/README.md`, `CONTEXT.md`, and the launcher/task docstrings all repointed off the deleted `devices/` to `configs/`.
