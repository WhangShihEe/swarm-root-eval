"""The eval-config -> TargetConfig loader (pure). Covers the eval-config split (yaml-config
ticket 02), the run knobs / 3-source notes / device-override whitelist (ticket 03), and the
ticket-04 contract: an eval config (`configs/evals/<name>.yaml`) is the ONLY launch shape — a
config without a top-level `device:` reference (e.g. the retired combined device yaml) is rejected.

Proves `load_target` on both shipped shapes: rasp -> single-APK file-set + its inline app fields;
healthhub -> split-set file-set (base + splits) + the shared-prompt app fields. The healthhub
split-count assertions read the untracked apks/ corpus; they skip cleanly when it is absent (CI
without the corpus), while path/field assertions run regardless.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from swarm_eval.broker_client import repo_root
from swarm_eval.target import (
    RunConfig,
    TargetConfig,
    WorkerRequest,
    load_run_config,
    load_target,
)

RASP_EVAL = "configs/evals/rasp_dummy.yaml"
HEALTHHUB_EVAL = "configs/evals/healthhub.yaml"

_ROOT = repo_root().resolve()
_HEALTHHUB_CORPUS = _ROOT / "apks" / "healthhub"
_healthhub_corpus = pytest.mark.skipif(
    not (_HEALTHHUB_CORPUS / "base.apk").exists(),
    reason="untracked apks/healthhub corpus not present",
)


def _write_eval(tmp_path: Path, app_body: str, *, device: str = "pixel",
                workers: str = "dynamic") -> Path:
    """Write a tmp app file (`app_body`) + an eval config referencing it, and return the eval
    path. The device/workers references resolve to the shipped `configs/{devices,workers}` files
    unless overridden. Used to exercise `_mission_fields`/`slot` through the eval-config shape (the
    only loader path now)."""
    app = tmp_path / "app.yaml"
    app.write_text(app_body, encoding="utf-8")
    ev = tmp_path / "eval.yaml"
    ev.write_text(f"app: {app}\ndevice: {device}\nworkers: {workers}\n", encoding="utf-8")
    return ev


def test_load_target_rasp_single_apk():
    t = load_target(RASP_EVAL)

    # primary APK + a single-file file-set staged at /root
    assert t.apk_name == "rasp_dummy.apk"
    assert list(t.files) == ["/root/rasp_dummy.apk"]
    (staged,) = t.files.values()
    assert Path(staged).is_absolute()
    assert staged.endswith("apks/rasp_dummy/rasp_dummy.apk")

    # app/mission fields from the app file (rasp inlines its own slots)
    assert t.package == "com.example.rasptarget"
    assert t.label == "RASP Target"
    assert t.launch_activity == "com.example.rasptarget.MainActivity"
    assert t.objective and "PASS" in t.objective
    assert t.success_signal and "FLAG{rasp-bypassed}" in t.success_signal
    # the app-specific detail carried verbatim from the app file
    assert t.details is not None
    for token in ("RaspEngine", "RASPTARGET", "com.example.rasptarget.detectors", "--es checks"):
        assert token in t.details, f"details should carry {token!r}"


def test_load_target_rasp_spec_path_is_repo_relative():
    # The `-T spec=` and the transcript store the positional in repo-relative form (cwd = root).
    assert load_target(RASP_EVAL).spec_path == RASP_EVAL


@_healthhub_corpus
def test_load_target_healthhub_split_set():
    t = load_target(HEALTHHUB_EVAL)

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

    # app fields — healthhub references the shared prompt, so assert shape, not verbatim text
    assert t.package == "sg.gov.hpb.healthhub"
    assert t.launch_activity is None
    assert t.objective and "launch" in t.objective.lower()
    assert t.details is not None and t.details.strip()
    assert t.success_signal and "dumpsys" in t.success_signal


def test_load_target_is_cwd_independent(monkeypatch):
    # configs/evals/x.yaml and its references/target_apk resolve against the repo root, so the same
    # spec loads whether cwd is the repo root or swarm-eval/ (matching the broker/bash resolution).
    from_root = load_target(RASP_EVAL)
    monkeypatch.chdir(_ROOT / "swarm-eval")
    from_subdir = load_target(RASP_EVAL)
    assert from_subdir == from_root


def test_load_target_absolute_spec_path(monkeypatch):
    # An absolute spec path also loads (the launchers may pass one), and stays repo-relative.
    monkeypatch.chdir(_ROOT / "swarm-eval")
    t = load_target(_ROOT / RASP_EVAL)
    assert t.spec_path == RASP_EVAL
    assert t.apk_name == "rasp_dummy.apk"


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
        (RASP_EVAL, "apks/rasp_dummy/rasp_dummy.apk"),
        (HEALTHHUB_EVAL, "apks/healthhub/base.apk"),
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


def test_load_target_rejects_non_eval_config(tmp_path):
    # A config with no top-level `device:` reference is not an eval config; the retired combined
    # device-yaml shape (app: block + target_apk, no device ref) is rejected loudly.
    spec = tmp_path / "legacy.yaml"
    spec.write_text(
        "target_apk: apks/x/base.apk\napp:\n  package: com.example.x\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not an eval config"):
        load_target(spec)


def test_load_target_missing_target_apk_raises(tmp_path):
    # An eval config whose app file omits target_apk fails on the app file, not the eval.
    ev = _write_eval(tmp_path, "package: com.example.x\n")
    with pytest.raises(ValueError, match="target_apk"):
        load_target(ev)


def test_slot_append_concatenates_onto_shared(tmp_path):
    # A per-app `<slot>_append` adds text onto the SHARED prompt's slot without restating it:
    # the shared base survives and the extra lands after it, separated by a blank line.
    ev = _write_eval(
        tmp_path,
        "target_apk: apks/rasp_dummy/rasp_dummy.apk\n"
        "package: com.example.x\n"
        "prompt: get-running-disable-rasp\n"
        "objective_append: |-\n"
        "  EXTRA-PHASE-3 marker.\n",
    )
    t = load_target(ev)
    assert "phases" in t.objective.lower()          # shared base still present (append, not override)
    assert t.objective.rstrip().endswith("EXTRA-PHASE-3 marker.")
    assert "\n\nEXTRA-PHASE-3 marker." in t.objective   # appended after base, blank-line separated


def test_slot_append_stacks_on_inline_override(tmp_path):
    # `_append` concatenates onto whichever base won — including an inline full override.
    ev = _write_eval(
        tmp_path,
        "target_apk: apks/rasp_dummy/rasp_dummy.apk\n"
        "package: com.example.x\n"
        "objective: BASE-OBJ\n"
        "objective_append: ADDED\n",
    )
    assert load_target(ev).objective == "BASE-OBJ\n\nADDED"


def test_parking_sg_inherits_phase3_and_appends_colour():
    # The real parking eval: phase 3 + ROE come from the SHARED prompt; the app file only appends
    # app-specific colour. Both must be present and coherent.
    t = load_target("configs/evals/parking_sg.yaml")
    assert "phases" in t.objective.lower()                 # shared phased flow
    assert "Rules of engagement" in t.objective            # ROE from the shared prompt
    assert "PROVE" in t.objective                          # phase 3 is in the shared flow
    assert "motorist" in t.objective                       # parking-specific append landed
    assert t.objective.rstrip().endswith("finding to prove.")
    # success bar comes wholly from the shared prompt (no per-app success append)
    assert "success_signal_append" not in (_ROOT / "configs/apps/parking_sg.yaml").read_text()
    assert "reproducible" in t.success_signal and "dumpsys" in t.success_signal


# ---- yaml-config ticket 02: the eval-config split -----------------------------------------


def test_eval_config_resolves_app_and_device_references():
    # The eval config references an app + a device by bare name. The broker acquires the
    # provisioning-only device and is handed the app's APK explicitly.
    t = load_target(RASP_EVAL)
    assert t.spec_path == RASP_EVAL
    assert t.device_spec == "configs/devices/pixel.yaml"
    assert t.broker_apk == "apks/rasp_dummy/rasp_dummy.apk"
    # the APK file-set comes from the app file's target_apk
    assert t.apk_name == "rasp_dummy.apk"
    assert list(t.files) == ["/root/rasp_dummy.apk"]
    (staged,) = t.files.values()
    assert staged.endswith("apks/rasp_dummy/rasp_dummy.apk")


def test_eval_config_is_cwd_independent(monkeypatch):
    from_root = load_target(RASP_EVAL)
    monkeypatch.chdir(_ROOT / "swarm-eval")
    assert load_target(RASP_EVAL) == from_root


def test_eval_config_accepts_path_style_references(tmp_path):
    # A reference may be a path/`*.yaml` value, not only a bare name.
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: configs/apps/rasp_dummy.yaml\n"
        "device: configs/devices/pixel.yaml\n"
        "workers: dynamic\n",
        encoding="utf-8",
    )
    t = load_target(ev)
    assert t.device_spec == "configs/devices/pixel.yaml"
    assert t.broker_apk == "apks/rasp_dummy/rasp_dummy.apk"


def test_eval_config_missing_device_file_raises(tmp_path):
    ev = tmp_path / "eval.yaml"
    ev.write_text("app: rasp_dummy\ndevice: nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="device"):
        load_target(ev)


def test_eval_config_missing_app_file_raises(tmp_path):
    ev = tmp_path / "eval.yaml"
    ev.write_text("app: nope\ndevice: pixel\n", encoding="utf-8")
    with pytest.raises(ValueError, match="app"):
        load_target(ev)


def test_eval_config_bad_workers_ref_raises(tmp_path):
    # A typo'd `workers:` fails as loudly as a bad app/device ref (the role file must exist).
    ev = tmp_path / "eval.yaml"
    ev.write_text("app: rasp_dummy\ndevice: pixel\nworkers: nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="workers"):
        load_target(ev)


def test_eval_config_app_owns_target_apk_no_frida_mode():
    # The app file owns target_apk and carries NO frida_mode key.
    app = yaml.safe_load((_ROOT / "configs/apps/rasp_dummy.yaml").read_text())
    assert app["target_apk"] == "apks/rasp_dummy/rasp_dummy.apk"
    assert "frida_mode" not in app
    # and the device file is provisioning-only (no app block, no APK)
    dev = yaml.safe_load((_ROOT / "configs/devices/pixel.yaml").read_text())
    assert "app" not in dev and "target_apk" not in dev
    assert dev["name"] == "pixel" and dev["system_image"]


def test_no_config_yaml_carries_frida_mode():
    # yaml-config ticket 04: no `frida_mode:` key survives in any config yaml (apps/devices/evals).
    for p in (_ROOT / "configs").rglob("*.yaml"):
        assert "frida_mode" not in yaml.safe_load(p.read_text(encoding="utf-8") or "{}"), p


# ---- yaml-config ticket 03: 3-source notes, device-override whitelist, run knobs ------------


def _t(**kw) -> TargetConfig:
    base = dict(
        spec_path="e.yaml", device_spec="d.yaml", files={}, apk_name="a.apk",
        package="p", label="L", objective="o", success_signal="s",
    )
    base.update(kw)
    return TargetConfig(**base)


def test_env_up_args_target_apk_only_when_no_overrides():
    # No whitelist override set (both None) → only the --target-apk pair.
    assert _t(broker_apk="apks/x/base.apk").env_up_args() == (
        "--target-apk", "apks/x/base.apk",
    )
    # a target with no broker_apk and no overrides forwards nothing
    assert _t().env_up_args() == ()


def test_env_up_args_emits_whitelisted_overrides_after_the_apk():
    # An eval override becomes the env-up flag that wins over the device spec (eval > device).
    assert _t(broker_apk="a.apk", writable_system=True, headless=False).env_up_args() == (
        "--target-apk", "a.apk", "--writable-system", "--window",
    )
    assert _t(writable_system=False, headless=True).env_up_args() == (
        "--frida-only", "--no-window",
    )


def test_eval_config_reads_worker_and_device_notes_and_overrides(tmp_path):
    # The eval config folds in the worker role file's notes + the device file's notes (the 3-source
    # mission) and may override ONLY writable_system/headless. Custom worker+device files carry
    # marker notes so we can assert they were read; the app is the real rasp app file.
    (tmp_path / "role.yaml").write_text("role: r\nnotes: WORKER-NOTE-MARK\n", encoding="utf-8")
    (tmp_path / "dev.yaml").write_text(
        "name: d\nsystem_image: img\nnotes: DEVICE-NOTE-MARK\n", encoding="utf-8"
    )
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: configs/apps/rasp_dummy.yaml\n"
        f"device: {tmp_path / 'dev.yaml'}\n"
        f"workers:\n  - role: {tmp_path / 'role.yaml'}\n    count: 2\n"
        "writable_system: true\n"
        "headless: false\n",
        encoding="utf-8",
    )
    t = load_target(ev)
    assert t.worker_notes == "WORKER-NOTE-MARK"
    assert t.device_notes == "DEVICE-NOTE-MARK"
    assert t.writable_system is True and t.headless is False
    # the whitelist rides through env_up_args (device spec split out → --target-apk + overrides)
    assert t.env_up_args() == (
        "--target-apk", "apks/rasp_dummy/rasp_dummy.apk", "--writable-system", "--window",
    )


def test_eval_config_without_overrides_leaves_them_none():
    # The shipped reference eval sets no writable_system/headless → both None (device file's values
    # stand), and no device notes yet → None. The dynamic role's notes are read.
    t = load_target(RASP_EVAL)
    assert t.writable_system is None and t.headless is None
    assert t.device_notes is None
    assert t.worker_notes and "dynamic-analysis agent" in t.worker_notes


def test_load_target_role_selects_that_roles_notes(tmp_path):
    # swarm-improvements ticket 03: a swarm worker loads its OWN role's notes, so a mixed roster
    # yields a different mission opener per role. Custom role files carry marker notes.
    (tmp_path / "dyn.yaml").write_text("role: dynamic\nnotes: DYN-MARK\n", encoding="utf-8")
    (tmp_path / "sta.yaml").write_text("role: static\nnotes: STATIC-MARK\n", encoding="utf-8")
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: configs/apps/rasp_dummy.yaml\ndevice: pixel\n"
        f"workers:\n  - role: {tmp_path / 'dyn.yaml'}\n    count: 1\n"
        f"  - role: {tmp_path / 'sta.yaml'}\n    count: 1\n",
        encoding="utf-8",
    )
    # role=None keeps the FIRST role's notes (the role-agnostic host/single path).
    assert load_target(ev).worker_notes == "DYN-MARK"
    # each role loads its own notes.
    assert load_target(ev, role=str(tmp_path / "dyn.yaml")).worker_notes == "DYN-MARK"
    assert load_target(ev, role=str(tmp_path / "sta.yaml")).worker_notes == "STATIC-MARK"


def test_load_target_shipped_static_and_coordinator_roles():
    # The two device-less roles ship as configs/workers/{static,coordinator}.yaml, selected by name.
    assert "STATIC-ANALYSIS" in (load_target(RASP_EVAL, role="static").worker_notes or "")
    assert "COORDINATOR" in (load_target(RASP_EVAL, role="coordinator").worker_notes or "")


def test_load_target_unknown_role_raises():
    with pytest.raises(ValueError, match="worker role 'nope'"):
        load_target(RASP_EVAL, role="nope")


def test_eval_config_workers_list_validates_every_role(tmp_path):
    # The list shape validates each referenced role file, as loudly as a bare-name ref.
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: rasp_dummy\ndevice: pixel\n"
        "workers:\n  - role: dynamic\n    count: 1\n  - role: nope\n    count: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="workers"):
        load_target(ev)


# ---- load_run_config: the run knobs an eval config carries ----------------------------------

def test_load_run_config_reads_model_workers_and_limits():
    rc = load_run_config(RASP_EVAL)
    assert rc.model == "anthropic/claude-sonnet-4-5-20250929"
    assert rc.workers == (WorkerRequest(role="dynamic", count=1),)
    assert rc.worker_count == 1
    assert rc.time_limit == 1800
    assert rc.budget == 3600.0
    assert rc.cap == 6


def test_load_run_config_sums_worker_counts(tmp_path):
    ev = tmp_path / "eval.yaml"
    ev.write_text(
        "app: rasp_dummy\ndevice: pixel\n"
        "workers:\n  - role: dynamic\n    count: 2\n  - role: dynamic\n    count: 3\n",
        encoding="utf-8",
    )
    assert load_run_config(ev).worker_count == 5


def test_load_run_config_bare_name_workers_has_no_count(tmp_path):
    # A bare-name `workers:` names a role but no count → worker_count None (CLI/default wins).
    ev = tmp_path / "eval.yaml"
    ev.write_text("app: rasp_dummy\ndevice: pixel\nworkers: dynamic\n", encoding="utf-8")
    assert load_run_config(ev).worker_count is None


def test_load_run_config_rejects_non_eval_config(tmp_path):
    # A config with no `device:` reference is not an eval config; run knobs can't be read from it.
    spec = tmp_path / "legacy.yaml"
    spec.write_text("target_apk: apks/x/base.apk\napp:\n  package: com.example.x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an eval config"):
        load_run_config(spec)


def test_load_run_config_omitted_knobs_are_unset(tmp_path):
    # An eval config that sets no run knobs → an all-unset RunConfig (launcher defaults stand).
    ev = tmp_path / "eval.yaml"
    ev.write_text("app: rasp_dummy\ndevice: pixel\n", encoding="utf-8")
    rc = load_run_config(ev)
    assert rc == RunConfig()
    assert rc.worker_count is None and rc.model is None


def test_load_target_reads_top_level_prompt_append_solution_eval():
    # env-hardening ticket 02 — an eval config's TOP-LEVEL `prompt_append:` is read into the
    # TargetConfig (the throwaway "solution" oracle), while the cold discovery config leaves it None.
    solution = load_target("configs/evals/dbs_solution.yaml")
    assert solution.prompt_append is not None
    assert "YOU ARE HANDED THE SOLUTION" in solution.prompt_append
    cold = load_target("configs/evals/dbs.yaml")
    assert cold.prompt_append is None, "the cold discovery eval must NOT carry the answer"
    # the app spec is the SAME for both — the answer rides only on the eval config, not the spec
    assert solution.package == cold.package == "com.dbs.sg.dbsmbanking"
# ---- backend block: a target's host companion server (mytelco integration) ---------------------

def test_backend_parsed_from_app_list_command(tmp_path):
    ev = _write_eval(
        tmp_path,
        "package: com.eval.x\n"
        "target_apk: apks/x/app.apk\n"
        "backend:\n"
        '  command: ["npm", "start"]\n'
        "  cwd: apks/x/backend\n"
        "  health_url: http://127.0.0.1:8090/health\n"
        "  ready_timeout: 40\n"
        "  port: 8090\n",
    )
    b = load_target(ev).backend
    assert b is not None
    assert b.command == ("npm", "start")
    assert b.health_url == "http://127.0.0.1:8090/health"
    assert b.ready_timeout == 40.0 and b.port == 8090
    # a relative cwd resolves against the repo root (absolute), like target_apk
    assert Path(b.cwd).is_absolute() and b.cwd.endswith("apks/x/backend")


def test_backend_command_string_is_shlex_split_and_health_optional(tmp_path):
    ev = _write_eval(
        tmp_path,
        "package: com.eval.x\ntarget_apk: apks/x/app.apk\n"
        "backend:\n  command: npm start\n  cwd: apks/x/backend\n",
    )
    b = load_target(ev).backend
    assert b.command == ("npm", "start")
    assert b.health_url is None          # optional — no readiness gate
    assert b.ready_timeout == 30.0       # DEFAULT_BACKEND_READY_TIMEOUT


def test_no_backend_block_leaves_backend_none(tmp_path):
    ev = _write_eval(tmp_path, "package: com.eval.x\ntarget_apk: apks/x/app.apk\n")
    assert load_target(ev).backend is None


def test_backend_without_cwd_is_a_loud_error(tmp_path):
    ev = _write_eval(
        tmp_path,
        "package: com.eval.x\ntarget_apk: apks/x/app.apk\n"
        "backend:\n  command: npm start\n",
    )
    with pytest.raises(ValueError, match="cwd"):
        load_target(ev)


def test_shipped_mytelco_rungs_declare_the_8090_backend():
    for spec in ("configs/evals/mytelco.yaml", "configs/evals/mytelco-packed.yaml"):
        b = load_target(spec).backend
        assert b is not None and b.port == 8090
        assert b.command == ("npm", "start")
        assert b.cwd.endswith("apks/mytelco/backend")
