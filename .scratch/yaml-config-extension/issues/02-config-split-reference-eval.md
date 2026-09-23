# 02: Config split + one reference eval end-to-end

**What to build:** Introduce the `configs/` tree (`configs/{devices,apps,workers,evals}/`, with shared
mission prompts under `configs/apps/prompts/`) and prove the whole new shape end-to-end for the
**rasp_dummy** reference target, while every other target keeps working through the existing combined
device-yaml path (expand step). For rasp_dummy: the `app:` block is extracted into
`configs/apps/rasp_dummy.yaml` (which now **owns `target_apk`** and has **no `frida_mode`**), the device
file holds provisioning only, and a `configs/workers/dynamic.yaml` role file plus a
`configs/evals/rasp_dummy.yaml` (which references the app, the device, and `workers`) exist. Both
entrypoints accept an eval-config path as their positional argument (alongside the legacy device-yaml
positional, which still works for the other 10). The dormant `frida_mode` field and its two dedicated
tests are deleted here (the attach-vs-spawn guidance lives in the app's prose notes, which is what
actually reaches the agent; the agent chooses per `frida-run` call regardless).

**Blocked by:** 01.

**Status:** done

- [x] `configs/{devices,apps,workers,evals}/` exist; shared prompts live under `configs/apps/prompts/`.
- [x] rasp_dummy is fully split: `configs/apps/rasp_dummy.yaml` owns `target_apk` and the app/mission fields (no `frida_mode`); `configs/devices/rasp_dummy.yaml` is provisioning-only; `configs/workers/dynamic.yaml` and `configs/evals/rasp_dummy.yaml` exist, the eval referencing app + device + a `dynamic` worker.
- [x] `single_agent.py configs/evals/rasp_dummy.yaml` and `swarm.py configs/evals/rasp_dummy.yaml --workers 3` both run and pass (verified in the `.eval`): single-agent status success, self_report accuracy 1.0, 29 tool calls, `RASP_BYPASS: SUCCESS`; swarm SUCCESS verdict, worker-3 status success with 23 tool calls, all 3 devices released; no bridge/tool errors in either.
- [x] The legacy combined device-yaml positional still works for the other 10 targets (no regression during the expand): `load_target` keeps the legacy reader (top-level `target_apk` + nested `app:`), broker acquires the positional with no `--target-apk`; the legacy `devices/rasp_dummy.yaml` / `healthhub.yaml` loader + mission tests still pass, and `bin/_spec.sh spec_load` still reads a legacy spec's `target_apk` via `spec_target_apk`.
- [x] The `frida_mode` field on the target/app config, the `DEFAULT_FRIDA_MODE` constant, and the two tests that assert its load/default and its non-leak into the mission are removed.
- [x] The mission for rasp_dummy renders equivalently to before (no app-specific regression from the split): `test_eval_config_mission_matches_legacy` asserts byte-equality with the legacy render.

**Implementation notes (for ticket 03/04):**
- The positional path (eval config *or* legacy device yaml) is passed unchanged to `-T spec=`; the
  in-task `load_target` resolves either shape. `TargetConfig` gained `device_spec` (which device
  the broker acquires) and `broker_apk` (the APK to install via `--target-apk`, `None` for legacy
  so the device layer sources it from the spec itself). The launchers resolve the config once and
  acquire `device_spec` + optional `--target-apk`.
- The eval-config discriminator is a top-level `device:` key. References (`app`/`device`/`workers`)
  resolve as bare names under `configs/{apps,devices,workers}/<name>.yaml`, or as a path/`*.yaml`.
- `configs/apps/prompts/` holds a copy of the shared prompt; the legacy `devices/prompts/` copy
  still serves the un-migrated combined yamls until ticket 04 (which retires the legacy path).
- `configs/workers/dynamic.yaml` exists and is referenced but its `notes` are not yet folded into
  the prompt — that is ticket 03's 3-source concatenation.
