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

# The default worker count when an eval config names a role without a `count:` (or names it by a
# bare string, the ticket-02 shape). A CLI `--workers` still overrides whatever the config yields.
DEFAULT_WORKER_COUNT = 1


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
    # yaml-config ticket 03 — the 3-source mission prompt: the worker role file's notes and the
    # device file's notes, concatenated by `mission.build_mission` in the order (worker role → app
    # → device). `None` for the legacy combined yaml (no worker/device notes there) and whenever a
    # file omits `notes`, so the legacy mission renders unchanged.
    worker_notes: str | None = None
    device_notes: str | None = None
    # yaml-config ticket 03 — the device-setting override whitelist. An eval config may override
    # ONLY these two device scalars; both `None` means "no eval override" (env-up reads the value
    # from the device spec, else its built-in default — precedence eval > device > default). Legacy
    # yamls never set them (their own spec scalars are read by env-up directly, as before).
    writable_system: bool | None = None
    headless: bool | None = None

    def env_up_args(self) -> tuple[str, ...]:
        """The env-up args the launcher forwards through `broker acquire` for this target: the APK
        to install (`--target-apk`, when the config splits it out of the device file) followed by
        any device-override-whitelist flags. A `None` override emits no flag, so the device spec's
        own value (or env-up's default) stands; a set override emits the flag that wins over the
        spec (eval > device > default). Both launchers call `acquire(device_spec, *env_up_args())`
        so the two paths forward identical args."""
        args: list[str] = []
        if self.broker_apk:
            args += ["--target-apk", self.broker_apk]
        if self.writable_system is not None:
            args.append("--writable-system" if self.writable_system else "--frida-only")
        if self.headless is not None:
            args.append("--no-window" if self.headless else "--window")
        return tuple(args)


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


def _read_notes(path: Path) -> str | None:
    """The `notes` string from a worker/device yaml, stripped, or `None` when absent/blank. A
    file that carries no `notes` contributes nothing to the 3-source mission (the source is just
    skipped), so an app with no device notes renders exactly as before."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    notes = data.get("notes")
    if notes is None:
        return None
    text = str(notes).strip()
    return text or None


def _worker_entries(workers_ref: Any) -> list[tuple[str, int | None]]:
    """Parse an eval config's `workers` into `(role, count)` pairs — the ONE place the `workers`
    shape is decoded, so the role roster (`_worker_roles`) and the count roster (`_parse_workers`)
    can't drift. Accepts the ticket-02 bare-name shape (`workers: dynamic`) or the ticket-03 list
    shape (`workers: [{role: dynamic, count: N}]`, a list entry may also be a bare string).

    `count` is `None` only for a TOP-LEVEL bare name (the ticket-02 shape names a role but no
    count, so the CLI/built-in default decides how many); a list entry is an explicit roster
    request, so a missing `count:` there defaults to `DEFAULT_WORKER_COUNT`."""
    if not workers_ref:
        return []
    if isinstance(workers_ref, str):
        return [(workers_ref, None)]
    if not isinstance(workers_ref, list):
        return [(str(workers_ref), None)]
    out: list[tuple[str, int | None]] = []
    for entry in workers_ref:
        if isinstance(entry, dict):
            role = entry.get("role")
            if not role:
                continue
            count = entry.get("count", DEFAULT_WORKER_COUNT)
            out.append((str(role), int(count)))
        elif entry:
            out.append((str(entry), DEFAULT_WORKER_COUNT))
    return out


def _worker_roles(workers_ref: Any) -> list[str]:
    """The role name(s) an eval config's `workers` names, in order — the roster to resolve +
    validate + read the mission notes from. Derived from `_worker_entries` (the shared parser)."""
    return [role for role, _ in _worker_entries(workers_ref)]


def _target_from_app(
    *,
    root: Path,
    spec_path: str,
    device_spec: str,
    broker_apk: str | None,
    target_apk: str,
    app: dict[str, Any],
    prompts_dir: str,
    worker_notes: str | None = None,
    device_notes: str | None = None,
    writable_system: bool | None = None,
    headless: bool | None = None,
) -> TargetConfig:
    """Assemble a `TargetConfig` from a resolved app dict + APK path, shared by both shapes. The
    3-source mission notes (worker role, device) and the device-override whitelist ride through as
    keyword args — only the eval-config path sets them; the legacy path leaves them `None`."""
    apk_p = Path(target_apk)
    primary_abs = (apk_p if apk_p.is_absolute() else root / apk_p).resolve()
    return TargetConfig(
        spec_path=spec_path,
        device_spec=device_spec,
        broker_apk=broker_apk,
        files=_apk_file_set(primary_abs),
        apk_name=primary_abs.name,
        worker_notes=worker_notes,
        device_notes=device_notes,
        writable_system=writable_system,
        headless=headless,
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

    # Resolve + validate every worker role the eval references (a typo'd `workers:` fails as loudly
    # as a bad `app:`/`device:`). The mission's worker-role notes come from the FIRST role (ticket
    # 03 ships one role, `dynamic`); a future per-role mission is a later ticket.
    roles = _worker_roles(data.get("workers"))
    role_paths: list[Path] = []
    for role in roles:
        wp = _resolve_ref(root, "workers", role)
        if not wp.is_file():
            raise ValueError(f"{spec_path}: eval config `workers` -> no worker file at {wp}")
        role_paths.append(wp)
    worker_notes = _read_notes(role_paths[0]) if role_paths else None

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
        # The 3-source mission notes: worker role (first role) → app (`details`, via _mission_fields)
        # → device. And the device-override whitelist: only `writable_system`/`headless` are read
        # off the eval config top level; any other device scalar there is ignored (not overridable).
        worker_notes=worker_notes,
        device_notes=_read_notes(device_path),
        writable_system=data.get("writable_system"),
        headless=data.get("headless"),
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


# ---- yaml-config ticket 03: run knobs folded into the eval config --------------------------
#
# An eval config carries the run's DEFAULTS (model, worker roster, caps/budget/limits) so a run is
# fully replicable from the file alone; a CLI flag still OVERRIDES the config value for that run
# (the launchers apply CLI > config > built-in default). These knobs are read separately from the
# target/device concern (`load_target`): they steer scheduling, not the APK/mission. A legacy
# combined device yaml carries none of them, so `load_run_config` returns an all-unset `RunConfig`
# for it and the launchers fall back to their built-in defaults (no regression).


@dataclass(frozen=True)
class WorkerRequest:
    """One `{role: <name>, count: <N>}` entry from an eval config's `workers` list: how many of a
    role to launch. The role names a `configs/workers/<role>.yaml` file (resolved by `load_target`)."""

    role: str
    count: int = DEFAULT_WORKER_COUNT


@dataclass(frozen=True)
class RunConfig:
    """The run knobs an eval config may set as defaults (ticket 03). Every field is `None`/empty
    when the config does not set it, so a launcher can apply CLI > config > built-in-default
    precedence uniformly. `workers` is the `[{role, count}]` roster; `worker_count` sums it (the
    number of workers to launch), or `None` when the config names no count."""

    model: str | None = None
    workers: tuple[WorkerRequest, ...] = ()
    time_limit: int | None = None
    working_limit: int | None = None
    message_limit: int | None = None
    budget: float | None = None
    cap: int | None = None

    @property
    def worker_count(self) -> int | None:
        return sum(w.count for w in self.workers) if self.workers else None


def _parse_workers(workers_ref: Any) -> tuple[WorkerRequest, ...]:
    """The `WorkerRequest` roster (role + count) an eval config's `workers` requests, derived from
    the shared `_worker_entries` parser. A count-less entry (only the ticket-02 top-level bare name)
    is dropped here, so it contributes no count and `worker_count` stays `None` — the CLI/built-in
    default then decides how many, while `load_target` still resolves that role for the mission."""
    return tuple(
        WorkerRequest(role=role, count=count)
        for role, count in _worker_entries(workers_ref)
        if count is not None
    )


def load_run_config(spec: str | Path) -> RunConfig:
    """Read the run knobs from a positional config. An eval config (top-level `device:` key) may
    set `model`, a `workers: [{role, count}]` roster, and a `limits:` block
    (`time_limit`/`working_limit`/`message_limit`/`budget`/`cap`); each is optional. A legacy
    combined device yaml sets none of these, so an empty `RunConfig` is returned and the launcher's
    built-in defaults stand — no behaviour change for the not-yet-migrated targets."""
    root = repo_root().resolve()
    spec_p = Path(spec)
    abs_spec = (spec_p if spec_p.is_absolute() else root / spec_p).resolve()
    data: dict[str, Any] = yaml.safe_load(abs_spec.read_text(encoding="utf-8")) or {}
    if "device" not in data:
        return RunConfig()

    limits = data.get("limits") or {}

    def _int(v: Any) -> int | None:
        return int(v) if v is not None else None

    model = data.get("model")
    return RunConfig(
        model=str(model) if model is not None else None,
        workers=_parse_workers(data.get("workers")),
        time_limit=_int(limits.get("time_limit")),
        working_limit=_int(limits.get("working_limit")),
        message_limit=_int(limits.get("message_limit")),
        budget=float(limits["budget"]) if limits.get("budget") is not None else None,
        cap=_int(limits.get("cap")),
    )
