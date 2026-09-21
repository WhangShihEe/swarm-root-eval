"""APK-agnostic refactor, ticket 02 — ONE generic mission built from a `TargetConfig`.

Proves the two shipped targets render through a single template: the target-agnostic boilerplate
(device connect + exact toolchain + verdict format) is byte-identical across them, while the app
slots differ. `frida_mode` is a runtime device knob only — after the mode guidance was dropped
from the prompt, it no longer changes the rendered mission. Plus the (unchanged) self-report
verdict extraction. Pure — no broker, no corpus: `load_target` reads only the yaml (the split
file-set is not needed to render a mission).
"""

import dataclasses

from swarm_eval.mission import (
    VERDICT_TOKEN,
    _device_and_tools,
    _verdict_block,
    build_mission,
    extract_self_report,
)
from swarm_eval.target import load_target

CONTRACT = "/root/device-contract.env"
RASP = load_target("devices/rasp_dummy.yaml")        # frida_mode: attach, single APK
HEALTHHUB = load_target("devices/healthhub.yaml")    # frida_mode: spawn, split set


def test_build_mission_fills_app_slots_from_target():
    m = build_mission(RASP, contract_path=CONTRACT)
    # the app slots all come from the TargetConfig (yaml app: block)
    assert "rasp_dummy.apk" in m                 # primary APK staged name
    assert "com.example.rasptarget" in m         # package
    assert "RASP Target" in m                    # label
    assert "com.example.rasptarget.MainActivity" in m  # launch_activity
    assert CONTRACT in m                         # injected contract path
    assert VERDICT_TOKEN in m                    # self-report contract
    # the app-specific detail is carried verbatim from the yaml (no regression vs the old prompt)
    for token in ("RaspEngine", "RASPTARGET", "com.example.rasptarget.detectors", "--es checks"):
        assert token in m, f"mission should carry app detail {token!r}"


def test_build_mission_lists_exact_toolchain():
    # The prompt must NAME every baked tool (dynamic + static + the frida-17 bridge workflow) and
    # the non-interactive runner — not hand-wave "static tools may also be present".
    m = build_mission(RASP, contract_path=CONTRACT)
    for tool in ("frida-compile", "frida-java-bridge", "frida-run", "objection",
                 "jadx", "apktool", "androguard"):
        assert tool in m, f"mission prompt should name {tool}"
    # the frida-17 gotcha (no built-in Java global) + the scaffold pointer, and the over-promise gone
    assert "frida-java-bridge" in m and "/opt/frida-agent" in m
    assert "may also be present" not in m
    # the load-bearing operational notes ticket 02 requires in the shared block
    assert "adb logcat -d" in m                  # watchdog / one-shot note
    assert "Java.scheduleOnMainThread" in m      # main-thread hooking note


def test_boilerplate_is_byte_identical_across_targets():
    # The target-agnostic operating manual renders identically and appears verbatim in BOTH
    # missions — the whole point of the refactor: the only difference is the yaml.
    rasp = build_mission(RASP, contract_path=CONTRACT)
    hh = build_mission(HEALTHHUB, contract_path=CONTRACT)
    for block in (_device_and_tools(CONTRACT), _verdict_block()):
        assert block in rasp
        assert block in hh


def test_app_slots_differ_across_targets():
    rasp = build_mission(RASP, contract_path=CONTRACT)
    hh = build_mission(HEALTHHUB, contract_path=CONTRACT)
    assert rasp != hh
    assert "RASP Target" in rasp and "RASP Target" not in hh
    assert "HealthHub" in hh and "HealthHub" not in rasp
    # the objective slot is the target's own, not shared boilerplate
    assert RASP.objective in rasp and RASP.objective not in hh
    assert HEALTHHUB.objective in hh and HEALTHHUB.objective not in rasp


def test_frida_mode_does_not_leak_into_mission():
    # The mode guidance was removed from the prompt: frida_mode is now a runtime device knob only
    # and MUST NOT change the rendered mission. This guards the cold design — two targets differing
    # ONLY in frida_mode render byte-for-byte identically, and the removed spawn-only guidance
    # ("reproduce the crash first") no longer appears. (Tool-manual examples like `frida-run -f`
    # remain — those are usage of the baked runner, not spawn-vs-attach method guidance.)
    spawn = dataclasses.replace(RASP, frida_mode="spawn")
    attach = dataclasses.replace(RASP, frida_mode="attach")
    m_spawn = build_mission(spawn, contract_path=CONTRACT)
    assert m_spawn == build_mission(attach, contract_path=CONTRACT)
    assert "Reproduce the failure FIRST" not in m_spawn


def test_extract_self_report_success():
    out = "I bypassed the check.\n" + VERDICT_TOKEN + ": SUCCESS\nevidence: ...\n"
    assert extract_self_report(out) == "SUCCESS"


def test_extract_self_report_failure():
    out = VERDICT_TOKEN + ": FAILURE"
    assert extract_self_report(out) == "FAILURE"


def test_extract_self_report_case_and_space_insensitive():
    assert extract_self_report(f"{VERDICT_TOKEN}:success") == "SUCCESS"
    assert extract_self_report(f"  {VERDICT_TOKEN}  :  Success ") == "SUCCESS"


def test_extract_self_report_absent_is_none():
    assert extract_self_report("no verdict here") is None
