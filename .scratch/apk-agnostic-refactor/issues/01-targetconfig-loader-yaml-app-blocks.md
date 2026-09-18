# 01: `TargetConfig` loader + yaml `app:` blocks

**What to build:** the Python-side reader for the device yaml — the one place that turns
`devices/<name>.yaml` into a typed `TargetConfig` the harness can use, plus the `app:` mission
block those yamls need. This is a prefactor: the new form is added beside the old (nothing
downstream consumes it yet), so the tree stays green. It sets up every later ticket, which take
a `TargetConfig` rather than reading a yaml or hardcoding an app.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `swarm_eval/target.py` exposes `TargetConfig` (frozen dataclass) and `load_target(spec) -> TargetConfig`, carrying: the repo-relative spec **path** (for the broker), the staged APK **file-set** (`{/root/<basename>: <abs host path>}` = the primary APK + its `split_config.*` siblings, staged at `/root`), the **primary APK** basename the mission decompiles, and the **app/mission** fields (`package`, `label`, `objective`, `success_signal`, `launch_activity?`, `frida_mode` (default `attach`), `details?`).
- [x] The APK file-set mirrors bash's split-detection rule (`_provision.sh::apk_install_set`): a lone `.apk` stages one file; a `base.apk` with `split_config.*.apk` siblings stages base + all splits. Detection is by sibling presence, never app identity.
- [x] Paths resolve the same way the broker/bash layer resolves them (against the repo root), so `devices/x.yaml` and its `target_apk` load whether cwd is the repo root or `swarm-eval/`.
- [x] Both `devices/rasp_dummy.yaml` and `devices/healthhub.yaml` gain an additive nested `app:` block (package, label, launch_activity, frida_mode, objective, success_signal, details); all existing device/provision keys are kept. rasp uses `frida_mode: attach`, healthhub `frida_mode: spawn`. The app-specific detail currently living in the two hardcoded prompts (rasp: detector classes, `RaspEngine` flow, logcat tag, FLAG, `--es checks` extra; healthhub: expected protection categories, native `.so` split note, the reproduce/reverse/neutralize/confirm order) is carried verbatim into these slots so nothing regresses in ticket 02.
- [x] PyYAML is declared in `swarm-eval/pyproject.toml` (installed but currently undeclared).
- [x] The bash bring-up layer still reads the extended yamls unchanged: `bin/_spec.sh` validation and `bin/_provision.sh` both tolerate the new nested `app:` block (confirmed, e.g. `yq 'type'` is still `!!map` and the required top-level keys still read). The bash yaml-parse test suite stays green.
- [x] `test_target.py` proves `load_target` on both yamls: rasp → single-APK file-set + its app fields; healthhub → split-set file-set (base + 3 splits) + its app fields + `frida_mode: spawn`.
