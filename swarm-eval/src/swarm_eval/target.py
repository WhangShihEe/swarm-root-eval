"""Python-side reader for the device yaml — the APK-agnostic refactor's `TargetConfig`.

One target = one `devices/<name>.yaml`. Two consumers read that same file: the bash bring-up
layer (`bin/_spec.sh`, `bin/_provision.sh`) parses specific top-level scalars with `yq`; this
module parses the same file for the **APK file-set** the sandbox stages plus the **app/mission**
fields (an additive nested `app:` block the bash layer ignores). It is the Python-side
counterpart to bash's `_spec.sh` — the one place a yaml becomes a typed harness value, so no
later ticket reads a yaml or hardcodes an app.

Ticket 02 switched the mission + `dynamic_agent` @task over to this (the old in-`dynamic_agent`
`TargetSpec` registry is gone); ticket 03 moves the launchers onto it.
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

# Default runtime frida mode when a spec's app block doesn't name one. `attach` (attach to the
# already-running app) is the conservative default: spawn (`-f`) can crash an app during early
# init. A hardened app that dies on launch overrides this to `spawn` so hooks land first.
DEFAULT_FRIDA_MODE = "attach"

# Shared mission prompts live here (repo-relative). Instead of inlining the three mission slots,
# a spec's app: block may set `prompt: <name>`; the slots are then read from
# `devices/prompts/<name>.yaml`, so one flow is authored once and reused across many specs. Any
# inline app: key still overrides the shared file field-by-field.
PROMPTS_DIR = "devices/prompts"
PROMPT_FIELDS = ("objective", "success_signal", "details")


@dataclass(frozen=True)
class TargetConfig:
    """One eval target, read from a single device yaml. Everything the harness needs to run
    the app-agnostic eval against this app lives here; any difference between two runs is fully
    defined by their two yamls.

    - `spec_path` — the repo-relative yaml path, as the broker wants it (`bin/broker acquire
      --spec <spec_path>`, run with cwd = repo root).
    - `files` — the staged APK file-set: `{/root/<basename>: <abs host path>}`, the primary APK
      plus its `split_config.*` siblings (see `load_target`), ready to hand to a Sample's `files`.
    - `apk_name` — the primary APK basename the mission decompiles (`base.apk`, `rasp_dummy.apk`).
    - the app/mission fields (`package`…`details`) come from the yaml `app:` block.
    """

    spec_path: str
    files: dict[str, str]
    apk_name: str
    package: str
    label: str
    objective: str
    success_signal: str
    launch_activity: str | None = None
    frida_mode: str = DEFAULT_FRIDA_MODE
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


def _load_prompt(root: Path, name: str) -> dict[str, Any]:
    """Read a shared mission prompt (`devices/prompts/<name>.yaml`) into its slot map. Only the
    prompt fields (`objective`/`success_signal`/`details`) are meaningful; any other key is
    ignored. Raises if the named prompt file is absent, so a typo'd `prompt:` fails loudly rather
    than silently rendering an empty mission."""
    p = (root / PROMPTS_DIR / f"{name}.yaml").resolve()
    if not p.is_file():
        raise ValueError(f"app.prompt '{name}': no shared prompt at {p}")
    loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {k: loaded[k] for k in PROMPT_FIELDS if k in loaded}


def load_target(spec: str | Path) -> TargetConfig:
    """Read one `devices/<name>.yaml` into a `TargetConfig`.

    `spec` may be repo-relative (`devices/rasp_dummy.yaml`) or absolute; a relative path (and the
    yaml's relative `target_apk`) resolves against the repo root, so a spec loads the same whether
    cwd is the repo root or `swarm-eval/` — the same resolution the broker/bash layer uses.
    """
    root = repo_root().resolve()

    spec_p = Path(spec)
    abs_spec = (spec_p if spec_p.is_absolute() else root / spec_p).resolve()
    data: dict[str, Any] = yaml.safe_load(abs_spec.read_text(encoding="utf-8")) or {}

    target_apk = data.get("target_apk")
    if not target_apk:
        raise ValueError(f"{spec}: device spec has no 'target_apk'")
    apk_p = Path(target_apk)
    primary_abs = (apk_p if apk_p.is_absolute() else root / apk_p).resolve()

    # The repo-relative spec path the broker acquires with. A spec outside the repo (e.g. a tmp
    # test file) keeps the path as given.
    try:
        spec_path = abs_spec.relative_to(root).as_posix()
    except ValueError:
        spec_path = str(spec)

    app: dict[str, Any] = data.get("app") or {}

    # A spec may pull the mission slots from a shared `devices/prompts/<name>.yaml` via `prompt:`;
    # an inline app: key overrides the shared file slot-by-slot (inline wins, else shared, else "").
    shared = _load_prompt(root, app["prompt"]) if app.get("prompt") else {}

    def slot(key: str) -> Any:
        v = app.get(key)
        return v if v is not None else shared.get(key)

    return TargetConfig(
        spec_path=spec_path,
        files=_apk_file_set(primary_abs),
        apk_name=primary_abs.name,
        package=app.get("package", ""),
        label=app.get("label", ""),
        objective=slot("objective") or "",
        success_signal=slot("success_signal") or "",
        launch_activity=app.get("launch_activity"),
        frida_mode=app.get("frida_mode") or DEFAULT_FRIDA_MODE,
        details=slot("details"),
    )
