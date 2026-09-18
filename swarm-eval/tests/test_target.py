"""APK-agnostic refactor, ticket 01 — the device-yaml -> TargetConfig loader (pure).

Proves `load_target` on both shipped device yamls: rasp -> single-APK file-set + its app
fields; healthhub -> split-set file-set (base + splits) + its app fields + frida_mode spawn.
The healthhub split-count assertions read the untracked apks/ corpus; they skip cleanly when
it is absent (CI without the corpus), while path/field assertions run regardless.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from swarm_eval.broker_client import repo_root
from swarm_eval.target import DEFAULT_FRIDA_MODE, load_target

RASP_SPEC = "devices/rasp_dummy.yaml"
HEALTHHUB_SPEC = "devices/healthhub.yaml"

_ROOT = repo_root().resolve()
_HEALTHHUB_CORPUS = _ROOT / "apks" / "healthhub"
_healthhub_corpus = pytest.mark.skipif(
    not (_HEALTHHUB_CORPUS / "base.apk").exists(),
    reason="untracked apks/healthhub corpus not present",
)


def test_load_target_rasp_single_apk():
    t = load_target(RASP_SPEC)

    # primary APK + a single-file file-set staged at /root
    assert t.apk_name == "rasp_dummy.apk"
    assert list(t.files) == ["/root/rasp_dummy.apk"]
    (staged,) = t.files.values()
    assert Path(staged).is_absolute()
    assert staged.endswith("apks/rasp_dummy/rasp_dummy.apk")

    # app/mission fields from the yaml app: block
    assert t.package == "com.example.rasptarget"
    assert t.label == "RASP Target"
    assert t.launch_activity == "com.example.rasptarget.MainActivity"
    assert t.frida_mode == "attach"
    assert t.objective and "PASS" in t.objective
    assert t.success_signal and "FLAG{rasp-bypassed}" in t.success_signal
    # the app-specific detail carried verbatim from the old hardcoded prompt
    assert t.details is not None
    for token in ("RaspEngine", "RASPTARGET", "com.example.rasptarget.detectors", "--es checks"):
        assert token in t.details, f"details should carry {token!r}"


def test_load_target_rasp_spec_path_is_repo_relative():
    # The broker acquires by repo-relative spec path (cwd = repo root), so that is what we store.
    assert load_target(RASP_SPEC).spec_path == RASP_SPEC


@_healthhub_corpus
def test_load_target_healthhub_split_set():
    t = load_target(HEALTHHUB_SPEC)

    # split set: base.apk is the primary/decompile target; base + its split siblings are staged
    assert t.apk_name == "base.apk"
    names = sorted(Path(p).name for p in t.files)
    assert names == [
        "base.apk",
        "split_config.arm64_v8a.apk",
        "split_config.en.apk",
        "split_config.xxhdpi.apk",
    ]
    assert set(t.files) == {f"/root/{n}" for n in names}
    assert all(Path(p).is_absolute() for p in t.files.values())

    # app fields — spawn mode, and the split/native detail carried verbatim
    assert t.package == "sg.gov.hpb.healthhub"
    assert t.frida_mode == "spawn"
    assert t.launch_activity is None
    assert t.objective and "launch" in t.objective.lower()
    assert t.details is not None and ".so" in t.details
    assert "NO planted flag" in t.success_signal or "NO planted flag" in t.details


def test_load_target_is_cwd_independent(monkeypatch):
    # devices/x.yaml and its target_apk resolve against the repo root, so the same spec loads
    # whether cwd is the repo root or swarm-eval/ (matching the broker/bash resolution).
    from_root = load_target(RASP_SPEC)
    monkeypatch.chdir(_ROOT / "swarm-eval")
    from_subdir = load_target(RASP_SPEC)
    assert from_subdir == from_root


def test_load_target_absolute_spec_path(monkeypatch):
    # An absolute spec path also loads (the launchers may pass one), and stays repo-relative.
    monkeypatch.chdir(_ROOT / "swarm-eval")
    t = load_target(_ROOT / RASP_SPEC)
    assert t.spec_path == RASP_SPEC
    assert t.apk_name == "rasp_dummy.apk"


def test_frida_mode_defaults_to_attach(tmp_path):
    # An app block without frida_mode falls back to the conservative attach default.
    spec = tmp_path / "nomode.yaml"
    spec.write_text(
        "target_apk: apks/rasp_dummy/rasp_dummy.apk\n"
        "app:\n"
        "  package: com.example.x\n",
        encoding="utf-8",
    )
    t = load_target(spec)
    assert t.frida_mode == DEFAULT_FRIDA_MODE == "attach"
    assert t.package == "com.example.x"
    assert t.launch_activity is None and t.details is None


def _bash_install_set(primary_rel: str) -> list[str]:
    """Basenames bash `_provision.sh::apk_install_set` stages for a repo-relative APK path."""
    out = subprocess.run(
        ["bash", "-c", f". bin/_provision.sh; apk_install_set {primary_rel}"],
        cwd=str(_ROOT),
        env={**os.environ, "HARNESS_ROOT": str(_ROOT)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(Path(line).name for line in out.split() if line)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize(
    "spec, primary_rel",
    [
        (RASP_SPEC, "apks/rasp_dummy/rasp_dummy.apk"),
        (HEALTHHUB_SPEC, "apks/healthhub/base.apk"),
    ],
)
def test_file_set_matches_bash_apk_install_set(spec, primary_rel):
    # The Python file-set is a port of bash `apk_install_set` (they read the same corpus from
    # two languages). Guard the duplication: the two must stage the identical file-set, or a
    # split-naming change silently diverges them. Skips when the untracked corpus is absent.
    if not (_ROOT / primary_rel).exists():
        pytest.skip(f"untracked corpus not present: {primary_rel}")
    python_set = sorted(Path(p).name for p in load_target(spec).files)
    assert python_set == _bash_install_set(primary_rel)


def test_load_target_missing_target_apk_raises(tmp_path):
    spec = tmp_path / "empty.yaml"
    spec.write_text("app:\n  package: com.example.x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="target_apk"):
        load_target(spec)
