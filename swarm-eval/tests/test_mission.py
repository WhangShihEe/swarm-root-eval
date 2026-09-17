"""Ticket 04 — mission prompt + self-report oracle extraction (pure)."""

from swarm_eval.mission import build_mission, extract_self_report, VERDICT_TOKEN


def test_build_mission_mentions_apk_contract_and_toolchain():
    m = build_mission(apk_name="rootbeer.apk", contract_path="/root/device-contract.env")
    assert "rootbeer.apk" in m
    assert "/root/device-contract.env" in m
    # the agent must be pointed at the live-device data plane and the toolchain
    assert "adb" in m.lower()
    assert "frida" in m.lower()
    # and told how to self-report so the oracle can read a verdict
    assert VERDICT_TOKEN in m


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
