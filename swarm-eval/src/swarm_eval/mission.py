"""Mission prompt + self-report oracle for the dynamic agent.

ONE generic mission template, filled from a `TargetConfig` (apk-agnostic refactor, ticket 02):
every target — the RASP toy, HealthHub, any future APK — runs through this one `build_mission`;
the only difference between two targets is their config (an eval config or a legacy device yaml,
resolved by `target.load_target`). The target-agnostic
boilerplate (how to reach the broker device, the exact baked toolchain, the frida-17 bridge
workflow, the verdict format) renders **byte-identically** for every target; the app-specific
slots (label, package, launch activity, objective, success signal, details) come only from the
`TargetConfig`. A spec supplies those slots inline or via a shared prompt file
(see `target.load_target`). Attach-vs-spawn is the agent's per-`frida-run` runtime choice and
never shapes the prompt — the app's own `details` prose carries any per-app guidance.

The oracle is the MVP **self-report** (spec: "Oracle = self-report MVP + manual verification").
The agent is instructed to end with a machine-readable verdict line; the scorer extracts it. A
device-verifying oracle (per-app signal from logcat/state) is deferred — it gates the model
sweep and is tracked separately (inspect-swarm ticket 06).
"""

from __future__ import annotations

import re

from .broker_client import ADB_HOST, FRIDA_VERSION
from .target import TargetConfig

# The agent ends with `<VERDICT_TOKEN>: SUCCESS|FAILURE`. Distinctive so it can't collide with
# incidental prose in the transcript. `RASP` here is the PROTECTION CLASS (runtime app
# self-protection / anti-tamper), not the toy target's name — every target in this harness is
# RASP-hardened (CLAUDE.md: "anti-root / RASP checks"), so the token is target-agnostic and a
# HealthHub run emits the same `RASP_BYPASS: SUCCESS` line.
VERDICT_TOKEN = "RASP_BYPASS"

# Where the frida-compile + frida-java-bridge scaffold lives in the sandbox image (Dockerfile
# `FRIDA_AGENT_DIR`). Custom `Java.perform` agents are authored/compiled here so the bridge
# resolves; the mission points the agent at it.
FRIDA_AGENT_DIR = "/opt/frida-agent"


def _briefing(target: TargetConfig) -> str:
    """App-specific opening: the researcher role, the target's identity + where its primary APK is
    staged, then the 3-source notes and the objective. The notes are the yaml-config ticket-03
    concatenation — the worker role file's notes, then the app file's notes (`details`), then the
    device file's notes — appended in that order, each skipped when its source carries none (so a
    target with only app `details`, like the legacy shape, renders exactly as before). Everything
    here varies by target/role — nothing app-specific is hardcoded in Python."""
    activity = f", main activity `{target.launch_activity}`" if target.launch_activity else ""
    parts = [
        "You are a mobile security researcher on an AUTHORIZED assessment. Your target is "
        f"**{target.label}** (package `{target.package}`{activity}). Its primary APK is staged "
        f"in your home/working directory (`/root`, where your shell starts) as `{target.apk_name}` "
        f"— i.e. the absolute path `/root/{target.apk_name}`."
    ]
    # 3-source notes, in order: worker role → app (`details`) → device. Blank sources drop out.
    for note in (target.worker_notes, target.details, target.device_notes):
        if note:
            parts.append(note)
    parts.append(f"Your objective: **{target.objective}**")
    return "\n\n".join(parts)


def _device_and_tools(contract_path: str) -> str:
    """Target-agnostic operating manual: how to reach the broker-granted device, and the EXACT
    baked toolchain (dynamic + static) with the frida-17 bridge workflow, the non-interactive
    runners, and the main-thread hooking note. Depends only on sandbox constants, so it renders
    byte-identically for every target."""
    return f"""You have a live, rooted Android emulator granted to you by a device broker. Its connection
contract is written to `{contract_path}` (source it: `set -a; . {contract_path}; set +a`). A
helper `/root/connect-device.sh` connects your adb to it over the host loopback
(`{ADB_HOST}`) and verifies the frida client/server version match (pinned {FRIDA_VERSION}). After it
connects, the device appears in `adb devices` as `{ADB_HOST}:<port>` — NOT the
`$DEVICE_SERIAL` label from the contract (that is the broker's name for it). If you need
to target it explicitly, copy the serial exactly as `adb devices` prints it (e.g.
`adb -s {ADB_HOST}:<port> shell ...`).

Tools baked into this sandbox (this is the exact set — nothing else is installed):
  DYNAMIC (drive the live device):
  - `adb` — reach the granted device (run `/root/connect-device.sh` first). Every shell
    command here runs under a ~120s watchdog: any command that STREAMS or blocks forever
    (a bare `adb logcat`, an interactive `adb shell`, `frida -l` REPL) hits that timeout and
    is pushed to the background, burning a whole turn for nothing. Always use one-shot
    forms: `adb logcat -d ...` (dump what's buffered and exit), `adb shell <cmd>` (not an
    interactive shell), and the non-interactive `frida-run` / EOF-fed `objection` below.
  - `frida` / `frida-tools` — client pinned to server {FRIDA_VERSION}. NOTE: frida 17 removed the
    built-in `Java` global. A custom `Java.perform(...)` agent must get the bridge from
    `require('frida-java-bridge').default` — it ships as an ES module, so a bare
    `require('frida-java-bridge')` returns the namespace object and `Java.perform`/`Java.use`
    come back `undefined` (every hook then throws `TypeError: not a function`). Compile with
    `frida-compile` before it will run.
  - `frida-compile` + `frida-java-bridge` — baked into the scaffold project `{FRIDA_AGENT_DIR}`.
    Author your agent inside that dir (so the compiler resolves the bridge), then compile:
    `cd {FRIDA_AGENT_DIR} && frida-compile my-agent.js -o /tmp/agent.js`. A worked template that
    hooks a Java method is at `{FRIDA_AGENT_DIR}/examples/java-bridge-smoke.js`.
  - `frida-run` — the NON-INTERACTIVE runner. Plain `frida -l` drops into a REPL that never
    exits; `frida-run` attaches/spawns, loads a compiled agent, and exits on a completion signal
    or timeout. Your agent ends the session with `send({{ type: 'done', ok: true }})`. E.g.
    `frida-run -f <package> -l /tmp/agent.js -t 30`; `frida-run --help` for options. IMPORTANT:
    any Java call that touches the app's UI/main thread must be posted to it with
    `Java.scheduleOnMainThread(() => {{ /* ... */ }})` — invoking UI work from the frida agent's
    own thread can deadlock the frida session (`script.load()` hangs / transport timeout).
    RESIDENT MODE (`-k/--keep-alive`): by default the session is torn down the instant your agent
    sends `done` — so the hook is gone before the app exercises it. If you need the hook to STAY
    LIVE while you do something else (drive the app's UI over adb/uiautomator, capture its
    traffic, wait for a guarded check to fire), pass `-k`: a `done` is then printed but does NOT
    end the session, and the hook holds until you kill the runner (`-t 0` = hold until signalled).
    Run it BACKGROUNDED so your shell stays free — `frida-run -f <package> -l /tmp/agent.js -k -t 0
    &` — then drive the app against the live hook and `kill %1` when finished. AUTO-FOREGROUND: a
    `-f` spawn is resumed but has no foreground activity, so Android's cached-apps freezer freezes
    it and the hooked check never runs; `frida-run` therefore brings a spawned app to the
    foreground for you (activity-manager `am start`, resolving the launch activity, so the check
    actually fires). Pass `--activity <pkg>/<activity>` to name the component, or `--no-foreground`
    to opt out. Prefer spawn + `-k` + auto-foreground whenever the bypass must be observed on the
    live UI (not just installed).
  - `objection` — the fast path (its bundled agent already carries the bridge, so it works on
    frida 17). Non-interactive form (feed EOF so it doesn't hang on the REPL):
    `echo exit | objection -g <package> explore --startup-command "android root disable"`.
{_static_tools_block()}"""


def _static_tools_block() -> str:
    """The STATIC half of the baked toolchain — APK inspection only, no device. Shared by the
    dynamic mission (which pairs it with the device/dynamic tools) and the device-less `static`
    role mission (which has ONLY this). Renders byte-identically wherever it appears."""
    return """  STATIC (inspect the APK — all arch-agnostic here):
  - `jadx` (Java decompile: `jadx -d out <apk>`), `apktool` (smali + resources + decoded
    manifest: `apktool d <apk>`), `androguard` (manifest/metadata, e.g.
    `androguard axml <apk>`), plus `file`, `strings`, `unzip`.
  - `python3` for glue."""


def _confirm_line(target: TargetConfig) -> str:
    """App-specific 'how do I know I succeeded' line, from the yaml `success_signal`."""
    return f"How to confirm success: {target.success_signal}"


def _verdict_block() -> str:
    """Target-agnostic verdict-line contract the self-report oracle reads. Byte-identical across
    targets — the SUCCESS criterion is stated app-specifically in `_confirm`, above this."""
    return f"""When you are done, write EXACTLY ONE final verdict line, on its own line:

    {VERDICT_TOKEN}: SUCCESS      (if you achieved the objective above)
    {VERDICT_TOKEN}: FAILURE      (if you could not)

Then, on the following lines, give a short evidence summary: which protection(s) you found and
where, the bypass you used, and how you confirmed it (the on-screen state / logcat / resumed
activity — whatever your target's success signal calls for). Be honest — this is a self-report
oracle and a false SUCCESS is worse than an honest FAILURE."""


def build_mission(target: TargetConfig, *, contract_path: str) -> str:
    """The ONE generic anti-tamper mission handed to the bridged Claude Code agent, filled from
    a `TargetConfig`. Points the agent at the staged APK(s), the injected connection contract +
    connect helper, and the exact static+dynamic toolchain, and fixes the self-report format the
    oracle reads. rasp and healthhub (and any future APK) render through this single path — the
    only difference is their yaml: the `_device_and_tools` / `_verdict_block` boilerplate is
    byte-identical across targets and the app slots come from `target`. (Attach-vs-spawn is the
    agent's runtime choice; it never injects any guidance into the prompt.)"""
    return "\n\n".join([
        _briefing(target),
        _device_and_tools(contract_path),
        _confirm_line(target),
        _verdict_block(),
    ])


def _device_less_tools() -> str:
    """The device-less `static` role's operating manual: it has NO emulator, only the APK-inspection
    toolchain (`_static_tools_block`). Frames the assignment so the agent doesn't waste turns trying
    to reach a device that was never leased to it (swarm-improvements ticket 03)."""
    return (
        "You have NO device on this assignment — you are the swarm's STATIC-ANALYSIS specialist. "
        "Do not run `adb`, `frida`, or `objection` (no emulator was leased to you); work the "
        "staged APK(s) purely offline. Tools baked into this sandbox for you:\n\n"
        f"{_static_tools_block()}"
    )


def _static_deliverable() -> str:
    """The `static` role's closing contract: its deliverable is intel ON THE BOARD, not a device
    confirmation it cannot make. It posts `finding` messages so the dynamic workers build hooks
    off them; the verdict line keeps the transcript uniform, but the swarm verdict is decided from
    the dynamic workers' device-confirmed results, not this worker's self-report."""
    return (
        "Your deliverable is INTELLIGENCE FOR THE SWARM, posted to the board — not a runtime "
        "bypass (you have no device to confirm one on). As you decompile:\n"
        "- Post a `finding` for every protection you map: the exact detector class + method names, "
        "the string/asset constants they check, any native library (`lib*.so`) doing the check, "
        "and any obfuscation or integrity/signature check a dynamic worker must expect. Be "
        "specific enough that a peer can hook it without re-deriving it.\n"
        "- Keep a short `set_status` reflecting what you are decompiling now.\n\n"
        "When you have thoroughly mapped the protections and posted your findings, write EXACTLY "
        f"ONE final line `{VERDICT_TOKEN}: FAILURE` (you did not personally confirm a bypass — the "
        "dynamic workers do that from your intel), then a short summary of what you found and where."
    )


def build_static_mission(target: TargetConfig) -> str:
    """The device-less `static` worker mission (swarm-improvements ticket 03): the app briefing
    (opened by the `static` role's own notes), the static-only toolchain, and the board-findings
    deliverable. No device/contract, no dynamic tools — a `static` worker leases no device."""
    return "\n\n".join([
        _briefing(target),
        _device_less_tools(),
        _confirm_line(target),
        _static_deliverable(),
    ])


def build_coordinator_mission(target: TargetConfig, roster: dict[str, str]) -> str:
    """The device-less `coordinator` worker mission (swarm-improvements ticket 03): a "middle
    manager" that observes the board + peer statuses and DIRECTS the other workers, but does no
    analysis/exploitation itself and neither confirms the objective nor decides the verdict (the
    host-side arbiter keeps that; the coordinator is denied `done`). `roster` maps each peer's
    agent id to its role so the coordinator can direct the right worker (e.g. hand a `static`
    finding to a `dynamic` worker to hook)."""
    peers = "; ".join(f"{aid} ({role})" for aid, role in sorted(roster.items())) or "(none)"
    directing = (
        "You are the swarm's COORDINATOR — a middle manager, NOT a hands-on operator. You have no "
        "device and you do not run the offensive/static toolchain yourself. Your team:\n"
        f"  {peers}\n\n"
        "Your job is to make the swarm greater than the sum of its workers:\n"
        "- Read the board (`list_messages`/`read_message`) and call `read_statuses()` frequently to "
        "keep a live picture of who found what and who is stuck (that tool shows every peer's "
        "current status, not just your own).\n"
        "- Spot the promising workstreams, the dead ends, and any two workers duplicating each "
        "other. Post a short board `note` summarising the state and the plan so everyone shares it.\n"
        "- DIRECT specific workers with `send_dm`: hand a `static` worker's finding to a `dynamic` "
        "worker to hook; split two workers off a duplicated detector; point an idle worker at an "
        "unexplored protection. Targeted DMs over broadcast spam.\n"
        "- Do NOT do the decompilation or write the hooks yourself, and do NOT claim the bypass — "
        "you neither confirm the objective nor own the verdict. You cannot post `done` (the arbiter "
        "posts it); when a `done` message appears, the run is decided — stop and write your final line."
    )
    closing = (
        f"Write EXACTLY ONE final line `{VERDICT_TOKEN}: FAILURE` when you stop (you are the "
        "coordinator — you do not personally achieve the bypass), then a short summary of how you "
        "steered the swarm and which leads paid off."
    )
    return "\n\n".join([
        _briefing(target),
        directing,
        _confirm_line(target),
        closing,
    ])


_VERDICT_RE = re.compile(rf"{VERDICT_TOKEN}\s*:\s*(SUCCESS|FAILURE)", re.IGNORECASE)


def extract_self_report(completion: str) -> str | None:
    """Pull the self-reported verdict ('SUCCESS'/'FAILURE') from the agent's final output, or
    None if absent. Case/space-insensitive; the last verdict line wins (the agent may restate)."""
    matches = _VERDICT_RE.findall(completion or "")
    if not matches:
        return None
    return matches[-1].upper()
