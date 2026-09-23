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

**Status:** ready-for-agent

- [ ] `configs/{devices,apps,workers,evals}/` exist; shared prompts live under `configs/apps/prompts/`.
- [ ] rasp_dummy is fully split: `configs/apps/rasp_dummy.yaml` owns `target_apk` and the app/mission fields (no `frida_mode`); `configs/devices/rasp_dummy.yaml` is provisioning-only; `configs/workers/dynamic.yaml` and `configs/evals/rasp_dummy.yaml` exist, the eval referencing app + device + a `dynamic` worker.
- [ ] `single_agent.py configs/evals/rasp_dummy.yaml` and `swarm.py configs/evals/rasp_dummy.yaml --workers 3` both run and pass (verified in the `.eval`).
- [ ] The legacy combined device-yaml positional still works for the other 10 targets (no regression during the expand).
- [ ] The `frida_mode` field on the target/app config, the `DEFAULT_FRIDA_MODE` constant, and the two tests that assert its load/default and its non-leak into the mission are removed.
- [ ] The mission for rasp_dummy renders equivalently to before (no app-specific regression from the split).
