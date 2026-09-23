# 04: Migrate the remaining specs + retire the legacy path + README

**What to build:** Finish the refactor (contract step). Convert the other 10 targets into
`configs/{devices,apps,evals}/` entries (device provisioning file + app file + a default eval that
references them with a single `dynamic` worker), matching the rasp_dummy reference conversion. Remove the
legacy combined-device-yaml code path and its tests so `configs/evals/<name>.yaml` is the only way to
launch a run. Strip any remaining `frida_mode:` lines from the migrated yamls. Rewrite the README
"Running custom evals (YAML)" section to describe the new `configs/` shape (resolving the inline WIP note
the seed anticipated).

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] All 11 targets run from `configs/evals/<name>.yaml`; no target still relies on a combined device-yaml.
- [ ] The legacy combined-device-yaml code path and its tests are removed; nothing reads an `app:` block out of a device file anymore.
- [ ] No `frida_mode:` key remains in any config yaml.
- [ ] The README "Running custom evals (YAML)" section documents the `configs/{devices,apps,workers,evals}/` model, the CLI-override rule, and the device-override whitelist.
- [ ] Both integration commands pass from the migrated `configs/evals/rasp_dummy.yaml` (verified in the `.eval`).
