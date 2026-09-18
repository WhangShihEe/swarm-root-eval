# 02: One generic mission + yaml-selected target through `dynamic_agent`

**What to build:** collapse the two near-duplicate mission prompts into ONE generic template
filled from a `TargetConfig`, and make `dynamic_agent`'s task select its target purely from the
yaml (`-T spec=devices/<name>.yaml`). After this, rasp and healthhub run through exactly one
code path — the only difference between them is their yaml. No app-specific text or APK constants
remain in Python. Device acquire/release is left in-task for now (unchanged); the host-side move
is ticket 03.

**Blocked by:** 01.

**Status:** done

- [x] `mission.py` has ONE `build_mission(target: TargetConfig) -> str`; `build_healthhub_mission` is gone. All target-agnostic boilerplate is preserved and factored so it renders byte-identically across targets: the device-contract/connect instructions, the exact tool list, the `adb logcat -d`/watchdog note, the frida-17 `require('frida-java-bridge').default` requirement, the `frida-run` non-interactive note, the `Java.scheduleOnMainThread` main-thread note, the "act, don't over-deliberate" nudge, and the exact verdict-line format.
- [x] The app-specific slots come only from `TargetConfig` (label, package, launch_activity, objective, success_signal, details); the spawn-vs-attach guidance (and any "reproduce the crash first" step) is chosen by `target.frida_mode`, so that structural difference too is yaml-defined.
- [x] `VERDICT_TOKEN` (a generic token is fine), `extract_self_report`, and the self-report scorer contract are kept intact.
- [x] `dynamic_agent`'s `@task` is `dynamic_agent(spec)` → `build_dynamic_task(load_target(spec))`; the `TARGETS`/`TargetSpec` registry, the `DEFAULT_TARGET`/APK path constants, and `_stage_all` are removed. The staged files and the decompile target come from the `TargetConfig`.
- [x] The conductor's worker launch passes `-T spec=<yaml>` so the spawned `dynamic_agent` knows its target (the swarm still runs).
- [x] Verifiable without a live emulator: render `build_mission` for both targets and confirm the boilerplate block is identical while the app slots differ; construct the `dynamic_agent` task for both yamls (standalone and with the swarm board env set).
- [x] Tests updated and green: `test_mission.py` (build via `TargetConfig`; boilerplate-identical + slots-differ + `frida_mode` drives spawn/attach), `test_dynamic_agent.py` and `test_swarm_worker.py` (task built via the new path), and the conductor argv assertions that now carry `-T spec=`.
