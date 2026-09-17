"""Ticket 04 — mission prompt + self-report oracle extraction (pure)."""

from swarm_eval.mission import build_mission, extract_self_report, VERDICT_TOKEN


def test_build_mission_mentions_apk_contract_and_toolchain():
    m = build_mission(apk_name="rasp_dummy.apk", contract_path="/root/device-contract.env")
    assert "rasp_dummy.apk" in m
    assert "/root/device-contract.env" in m
    # the agent must be pointed at the live-device data plane and the toolchain
    assert "adb" in m.lower()
    assert "frida" in m.lower()
    # and told how to self-report so the oracle can read a verdict
    assert VERDICT_TOKEN in m


def test_build_mission_lists_exact_ticket07_toolchain():
    # Ticket 07: the prompt must NAME every baked tool (dynamic + static + the frida-17 bridge
    # workflow) and the non-interactive runner — not hand-wave "static tools may also be present".
    m = build_mission(apk_name="rasp_dummy.apk", contract_path="/root/device-contract.env")
    for tool in ("frida-compile", "frida-java-bridge", "frida-run", "objection",
                 "jadx", "apktool", "androguard"):
        assert tool in m, f"mission prompt should name {tool}"
    # the frida-17 gotcha (no built-in Java global) must be called out, and the scaffold pointed to
    assert "frida-java-bridge" in m and "/opt/frida-agent" in m
    # the over-promising hedge is gone
    assert "may also be present" not in m


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
