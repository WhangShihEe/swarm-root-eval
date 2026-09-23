"""Python-side reader for a run's config — the one place a yaml becomes a typed `TargetConfig`.

A run is selected by a single positional path handed to both consumers (`bin/broker acquire`
host-side and the `-T spec=` in-task). That path is one of two shapes, and `load_target` reads
either into the same `TargetConfig`:

- an **eval config** (`configs/evals/<name>.yaml`, yaml-config ticket 02) — a file that
  *references* an app, a device, and a worker role by name. The app file
  (`configs/apps/<name>.yaml`) owns `target_apk` + the app/mission slots; the device file
  (`configs/devices/<name>.yaml`) is provisioning-only. This is the new shape.
- a **legacy combined device yaml** (`devices/<name>.yaml`) — provisioning scalars at the top
  level plus a nested `app:` block and a top-level `target_apk`. The pre-split shape, kept
  working for the not-yet-migrated targets (ticket 04 retires it).

The discriminator is a top-level `device:` key: an eval config has one (it references a device),
a legacy device yaml never does. `TargetConfig` carries what BOTH consumers need — the staged
APK file-set + mission slots for the in-task agent, and `device_spec`/`broker_apk` for the
host-side broker (which device to acquire, which APK to install).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .broker_client import repo_root

# APKs stage into the sandbox at /root (the agent's cwd / shell home), matching where
# `dynamic_agent`'s Sample `files` place them and where the mission tells the agent to look.
STAGE_DIR = "/root"

# The configs/ tree an eval config resolves its bare-name references under (ticket 02).
CONFIGS_DIR = "configs"

# Shared mission prompts. An app/device yaml may set `prompt: <name>` instead of inlining the
# three mission slots; the slots are then read from `<prompts_dir>/<name>.yaml`, so one flow is
# authored once and reused across many targets. The new (app-owned) shape reads from
# `configs/apps/prompts`; the legacy combined yamls read from `devices/prompts` until ticket 04
# migrates them. Any inline slot overrides the shared file field-by-field, and an inline
# `<slot>_append` concatenates onto that slot (see `_mission_fields.slot`).
APP_PROMPTS_DIR = "configs/apps/prompts"
LEGACY_PROMPTS_DIR = "devices/prompts"
PROMPT_FIELDS = ("objective", "success_signal", "details")


@dataclass(frozen=True)
class TargetConfig:
    """One eval target, read from a single positional config (an eval config or a legacy device
    yaml). Everything the harness needs to run the app-agnostic eval against this app lives here;
    any difference between two runs is fully defined by their configs.

    In-task fields (mission + staging):
    - `files` — the staged APK file-set: `{/root/<basename>: <abs host path>}`, the primary APK
      plus its `split_config.*` siblings, ready to hand to a Sample's `files`.
    - `apk_name` — the primary APK basename the mission decompiles (`base.apk`, `rasp_dummy.apk`).
    - the app/mission slots (`package`…`details`) come from the app fields (an app file, or the
      legacy yaml's nested `app:` block).

    Host-side fields (broker):
    - `spec_path` — the repo-relative form of the positional given (kept for the transcript).
    - `device_spec` — the repo-relative device yaml the broker acquires (`bin/broker acquire
      --spec <device_spec>`, cwd = repo root). For a legacy yaml this is the positional itself.
    - `broker_apk` — the repo-relative APK path to install via `--target-apk`, or `None` to let
      the device layer source it from the device spec (the legacy path, unchanged).
    """

    spec_path: str
    device_spec: str
    files: dict[str, str]
    apk_name: str
    package: str
    label: str
    objective: str
    success_signal: str
    broker_apk: str | None = None
    launch_activity: str | None = None
    details: str | None = None


def _apk_file_set(primary_abs: Path) -> dict[str, str]:
    """The staged APK file-set, mirroring bash `_provision.sh::apk_install_set`:

      - a lone self-contained `.apk` stages one file;
      - a `base.apk` with `split_config.*.apk` siblings stages base + all splits;
      - a directory holding the above resolves the same way.

    Detection is by the presence of `split_config.*` siblings, never by app identity. Base is
    listed first, then the splits sorted, so the mapping is deterministic. The primary path is
    always emitted even if it does not exist on disk (bash prints the base unconditionally),
    so path resolution is independent of whether the untracked apks/ corpus is present.
    """
    if primary_abs.is_dir():
        d = primary_abs
        base = d / "base.apk"
        if not base.exists():
            # A directory with no base.apk: stage every .apk in it (bash's else branch).
            return {f"{STAGE_DIR}/{p.name}": str(p) for p in sorted(d.glob("*.apk"))}
    else:
        d = primary_abs.parent
        base = primary_abs

    files = {f"{STAGE_DIR}/{base.name}": str(base)}
    for split in sorted(d.glob("split_config.*.apk")):
        if split == base:
            continue
        files[f"{STAGE_DIR}/{split.name}"] = str(split)
    return files


def _load_prompt(root: Path, prompts_dir: str, name: str) -> dict[str, Any]:
    """Read a shared mission prompt (`<prompts_dir>/<name>.yaml`) into its slot map. Only the
    prompt fields (`objective`/`success_signal`/`details`) are meaningful; any other key is
    ignored. Raises if the named prompt file is absent, so a typo'd `prompt:` fails loudly rather
    than silently rendering an empty mission."""
    p = (root / prompts_dir / f"{name}.yaml").resolve()
    if not p.is_file():
        raise ValueError(f"prompt '{name}': no shared prompt at {p}")
    loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {k: loaded[k] for k in PROMPT_FIELDS if k in loaded}


def _mission_fields(root: Path, app: dict[str, Any], prompts_dir: str) -> dict[str, Any]:
    """Resolve the app/mission slots from an app dict (an app file's top level, or a legacy
    yaml's nested `app:` block). A `prompt:` pulls the slots from a shared
    `<prompts_dir>/<name>.yaml`; an inline `<slot>` overrides the shared file slot-by-slot (inline
    wins, else shared, else ""), and an inline `<slot>_append` concatenates extra per-app text
    onto whichever base won."""
    shared = _load_prompt(root, prompts_dir, app["prompt"]) if app.get("prompt") else {}

    def slot(key: str) -> Any:
        # inline `<key>` fully overrides the shared file; else the shared slot; else "".
        base = app[key] if app.get(key) is not None else shared.get(key)
        # a per-app inline `<key>_append` concatenates onto whichever base won, so a spec can add
        # app-specific mission text (an extra phase, ROE, app colour) WITHOUT restating the whole
        # shared slot. `_append` keys are inline-only — never read from the shared prompt file
        # (PROMPT_FIELDS), since an append is by definition per-app, not part of the shared flow.
        extra = app.get(f"{key}_append")
        if extra is not None:
            base = f"{base}\n\n{extra}" if base else extra
        return base

    return dict(
        package=app.get("package", ""),
        label=app.get("label", ""),
        objective=slot("objective") or "",
        success_signal=slot("success_signal") or "",
        launch_activity=app.get("launch_activity"),
        details=slot("details"),
    )


def _repo_rel(root: Path, p: Path, fallback: str) -> str:
    """The repo-relative posix form of an absolute path (what the broker acquires with, cwd =
    repo root). A path outside the repo (e.g. a tmp test file) keeps `fallback`."""
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return fallback


def _resolve_ref(root: Path, kind: str, ref: str) -> Path:
    """Resolve an eval-config reference (`app:`/`device:`/`workers:`) to a file. A bare name
    (`rasp_dummy`) maps to `configs/<kind>/<name>.yaml`; a value with a slash or a `.yaml`/`.yml`
    suffix is treated as a path (repo-relative unless absolute)."""
    p = Path(ref)
    if p.is_absolute():
        return p.resolve()
    if "/" in ref or p.suffix in (".yaml", ".yml"):
        return (root / p).resolve()
    return (root / CONFIGS_DIR / kind / f"{ref}.yaml").resolve()


def _target_from_app(
    *,
    root: Path,
    spec_path: str,
    device_spec: str,
    broker_apk: str | None,
    target_apk: str,
    app: dict[str, Any],
    prompts_dir: str,
) -> TargetConfig:
    """Assemble a `TargetConfig` from a resolved app dict + APK path, shared by both shapes."""
    apk_p = Path(target_apk)
    primary_abs = (apk_p if apk_p.is_absolute() else root / apk_p).resolve()
    return TargetConfig(
        spec_path=spec_path,
        device_spec=device_spec,
        broker_apk=broker_apk,
        files=_apk_file_set(primary_abs),
        apk_name=primary_abs.name,
        **_mission_fields(root, app, prompts_dir),
    )


def _load_eval_config(root: Path, spec_path: str, data: dict[str, Any]) -> TargetConfig:
    """The new (ticket 02) shape: an eval config referencing an app + a device (+ a worker role).
    The app file owns `target_apk` and the mission slots; the device file is provisioning-only,
    so the broker is handed the device spec AND the APK explicitly (`broker_apk`)."""
    device_path = _resolve_ref(root, "devices", str(data["device"]))
    if not device_path.is_file():
        raise ValueError(f"{spec_path}: eval config `device` -> no device file at {device_path}")

    app_ref = data.get("app")
    if not app_ref:
        raise ValueError(f"{spec_path}: eval config has no `app` reference")
    app_path = _resolve_ref(root, "apps", str(app_ref))
    if not app_path.is_file():
        raise ValueError(f"{spec_path}: eval config `app` -> no app file at {app_path}")
    app: dict[str, Any] = yaml.safe_load(app_path.read_text(encoding="utf-8")) or {}

    # The worker role is consumed by ticket 03 (its notes fold into the mission), not here — but
    # validate the reference now so a typo'd `workers:` fails as loudly as a bad `app:`/`device:`
    # rather than silently going nowhere.
    workers_ref = data.get("workers")
    if workers_ref is not None:
        workers_path = _resolve_ref(root, "workers", str(workers_ref))
        if not workers_path.is_file():
            raise ValueError(
                f"{spec_path}: eval config `workers` -> no worker file at {workers_path}"
            )

    target_apk = app.get("target_apk")
    if not target_apk:
        raise ValueError(f"{app_path}: app file has no 'target_apk'")

    return _target_from_app(
        root=root,
        spec_path=spec_path,
        device_spec=_repo_rel(root, device_path, str(data["device"])),
        broker_apk=str(target_apk),
        target_apk=str(target_apk),
        app=app,
        prompts_dir=APP_PROMPTS_DIR,
    )


def _load_device_yaml(root: Path, spec_path: str, data: dict[str, Any]) -> TargetConfig:
    """The legacy combined shape: provisioning scalars + a top-level `target_apk` + a nested
    `app:` block. The broker acquires this same file and sources the APK from it (`broker_apk`
    stays None), exactly as before the split — no regression for the not-yet-migrated targets."""
    target_apk = data.get("target_apk")
    if not target_apk:
        raise ValueError(f"{spec_path}: device spec has no 'target_apk'")
    return _target_from_app(
        root=root,
        spec_path=spec_path,
        device_spec=spec_path,
        broker_apk=None,  # the device layer reads target_apk out of this same spec (legacy)
        target_apk=str(target_apk),
        app=data.get("app") or {},
        prompts_dir=LEGACY_PROMPTS_DIR,
    )


def load_target(spec: str | Path) -> TargetConfig:
    """Read one positional config — an eval config or a legacy device yaml — into a `TargetConfig`.

    `spec` may be repo-relative (`configs/evals/rasp_dummy.yaml`, `devices/healthhub.yaml`) or
    absolute; a relative path (and any relative reference/`target_apk` inside) resolves against
    the repo root, so a config loads the same whether cwd is the repo root or `swarm-eval/` — the
    same resolution the broker/bash layer uses. A top-level `device:` key selects the eval-config
    reader; its absence selects the legacy reader.
    """
    root = repo_root().resolve()

    spec_p = Path(spec)
    abs_spec = (spec_p if spec_p.is_absolute() else root / spec_p).resolve()
    data: dict[str, Any] = yaml.safe_load(abs_spec.read_text(encoding="utf-8")) or {}
    spec_path = _repo_rel(root, abs_spec, str(spec))

    if "device" in data:
        return _load_eval_config(root, spec_path, data)
    return _load_device_yaml(root, spec_path, data)
