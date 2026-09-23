"""APK-agnostic refactor, ticket 02 — ONE generic mission built from a `TargetConfig`.

Proves the two shipped targets render through a single template: the target-agnostic boilerplate
(device connect + exact toolchain + verdict format) is byte-identical across them, while the app
slots differ. Attach-vs-spawn never enters the prompt (it is the agent's runtime choice). Plus
the (unchanged) self-report verdict extraction. Pure — no broker, no corpus: `load_target` reads
only the yaml (the split file-set is not needed to render a mission).
"""

from swarm_eval.mission import (
    VERDICT_TOKEN,
    _device_and_tools,
    _verdict_block,
    build_mission,
    extract_self_report,
)
from swarm_eval.target import load_target

CONTRACT = "/root/device-contract.env"
RASP = load_target("configs/evals/rasp_dummy.yaml")        # single APK
HEALTHHUB = load_target("configs/evals/healthhub.yaml")    # split set


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


def test_eval_config_mission_folds_in_worker_role_notes():
    # yaml-config ticket 03: the eval-config mission opens the 3-source prompt with the worker
    # role file's notes, ahead of the app detail (source order: role → app). The rasp eval config
    # references the `dynamic` role, so its notes land in the mission before the app's `details`.
    ev = build_mission(RASP, contract_path=CONTRACT)
    assert RASP.objective in ev and RASP.success_signal in ev
    assert RASP.details is not None and RASP.details in ev
    role_notes = RASP.worker_notes
    assert role_notes and "dynamic-analysis agent" in role_notes
    assert role_notes in ev
    assert ev.index(role_notes) < ev.index(RASP.details)


def test_build_mission_appends_the_three_note_sources_in_order():
    # yaml-config ticket 03: the mission opens with the researcher line, then the worker-role
    # notes, then the app notes (details), then the device notes — in that order. Each source is
    # skipped when blank, so this asserts the full ordering with all three present.
    from swarm_eval.target import TargetConfig

    t = TargetConfig(
        spec_path="e", device_spec="d", files={}, apk_name="a.apk",
        package="p", label="L", objective="OBJ", success_signal="s",
        worker_notes="ROLE-NOTES", details="APP-NOTES", device_notes="DEVICE-NOTES",
    )
    m = build_mission(t, contract_path=CONTRACT)
    assert m.index("ROLE-NOTES") < m.index("APP-NOTES") < m.index("DEVICE-NOTES")
    # the objective still follows the notes block
    assert m.index("DEVICE-NOTES") < m.index("OBJ")


def test_build_mission_skips_absent_note_sources():
    # A target with only app notes (the legacy shape: no worker/device files) renders with just
    # that source — no empty gaps from the missing worker/device notes.
    from swarm_eval.target import TargetConfig

    t = TargetConfig(
        spec_path="e", device_spec="d", files={}, apk_name="a.apk",
        package="p", label="L", objective="OBJ", success_signal="s", details="ONLY-APP",
    )
    m = build_mission(t, contract_path=CONTRACT)
    assert "ONLY-APP" in m
    assert "\n\n\n" not in m  # no doubled blank line from a skipped source
