<div align="center">

<img src="docs/assets/logo.svg" alt="android-swarm" width="120" height="120" />

# android-swarm

**Can a swarm of Claude Code agents compromise a real Android app?** android-swarm hands
_N_ bridged Claude Code agents one thing — a single **APK file** and a live **rooted emulator** —
and asks them to defeat its anti-root / RASP defenses and build a working bypass. It's a
**capability probe** (can they do it at all, and which models do it best), not a
fairness-controlled benchmark. The whole harness is **APK-agnostic**: point it at a new app by
swapping one YAML file.

_Demo GIF — `<WIP>`_ 🎥 &nbsp;a single loop of a worker agent driving a live emulator (the RASP
target flipping `PROTECTED — TAMPER DETECTED` → `UNLOCKED` / `FLAG{…}` revealed) while the shared
messageboard fills with the swarm's posts in real time. _Produced later via
[`.scratch/demo-app-gif/`](.scratch/demo-app-gif/)._

</div>

---

## How it works

<div align="center">

<img src="docs/assets/architecture.svg" alt="architecture: one APK in, the broker grants a rooted emulator per worker, N independent Inspect-run Claude Code agents linked only by a host-side messageboard, an arbiter reads the board and issues a verdict" width="920" />

</div>

One APK goes in. A standing **broker** grants each worker its own rooted emulator. Each worker is
a bridged Claude Code agent that inspects the APK statically (jadx/apktool/androguard) and attacks
it dynamically (frida/objection over adb). A host-side **arbiter** watches the shared board and
issues the verdict.

**Why the Inspect wiring is unusual.** The obvious way to run _N_ agents in Inspect — one eval
with in-process subagents — doesn't work here: concurrent subagents collapse onto the parent's
transcript span. So android-swarm runs **each worker as its own independent `inspect eval`**
(one run = one bridge = one clean transcript) and wires the swarm together **outside Inspect**,
from a host launcher. The workers share no Inspect state; their _only_ link is a host-side,
append-only **messageboard**. The full story lives in
[`swarm-eval/README.md`](swarm-eval/README.md) and [`docs/adr/0002-…`](docs/adr/0002-separate-runs-swarm-no-central-orchestrator.md).

## Quickstart

Runs the owned **RASP-dummy** target out of the box.

**Prerequisites:** a macOS/Linux host with the Android SDK cmdline-tools + JDK 17+, [uv](https://docs.astral.sh/uv/),
Docker (the agent runs in a sandbox image, built on first run), a host `ANTHROPIC_API_KEY`
(the sandbox Claude Code is keyless — the _host_ makes the real call), and the target APK at
`apks/rasp_dummy/rasp_dummy.apk`.

```bash
cd android-swarm
source bin/env.sh          # Android SDK + adb/emulator/avdmanager + JDK on PATH (see versions.txt)
bin/doctor                 # assert pinned tools + a rootable image; must exit 0
bin/broker start           # bring the device layer up (grants rooted emulators on demand)

# (optional smoke) grab a live rooted device by hand, then hand it straight back:
bin/broker acquire --spec devices/rasp_dummy.yaml   # → serial=… adb_port=… profile=writable-system
bin/broker release --serial emulator-5554

# run one bridged Claude Code agent at the RASP-dummy target
# (single_agent.py leases + releases its own device — even on failure/timeout):
cd swarm-eval
uv run python single_agent.py devices/rasp_dummy.yaml
```

The transcript + scored self-report land in `swarm-eval/logs/<run-id>/` (open with
`uv run inspect view`). A single agent is just the swarm at **N=1**; the multi-agent form is:

```bash
uv run python swarm.py devices/rasp_dummy.yaml --workers 3    # N workers + a shared board + arbiter
```

## Running custom evals (YAML)

The target is defined **entirely by a device-spec YAML** ([`devices/*.yaml`](devices/)) — the harness
never branches per app. Each spec is **two tiers**:

- **Top-level scalars** — read by the **bash device layer** (`bin/_spec.sh`, `bin/_provision.sh`):
  `name`, `device_profile`, `system_image`, `api`, `ram_mb`, `target_apk`, `provision`, `frida`, … .
  These boot and provision the emulator to _t=0_.
- **A nested `app:` block** — read _only_ by the **Python harness** (`swarm_eval/target.py`) and
  ignored by bash: `package`, `label`, `launch_activity`, `frida_mode`, and the free-text
  `objective` / `success_signal` / `details` that become the agent's mission.

**To point the probe at a new app:** drop its APK at `apks/<app>/<app>.apk`, copy an existing
`devices/<app>.yaml` (edit the top-level `target_apk` + the `app:` block), and pass that YAML —
no Python or mission edits:

```bash
uv run python single_agent.py devices/<app>.yaml --model anthropic/<other-model>
```

`--model` is the **model-sweep lever**: the keyless sandbox Claude Code proxies to whatever host
model you name (default `anthropic/claude-sonnet-4-5-20250929`), so swapping to another Anthropic
model — or a cross-vendor `<provider>/<model>` — is a one-flag change.

> **`<WIP>` — YAML-declared runs.** Run knobs (`--model`, `--workers`, `--time-limit`, `--budget`)
> are still **CLI flags** today. The replicability goal is to fold them into the device YAML so a
> run is fully declared by one file. The open design question is how to **split the YAML by
> permission** — which keys an eval author may edit vs. which are locked to the harness.
> Context-seed: [`.scratch/yaml-config-extension/`](.scratch/yaml-config-extension/).

## For coding agents

Working in this repo with an agent? Start from [`CLAUDE.md`](CLAUDE.md) (orientation),
[`CONTEXT.md`](CONTEXT.md) (the domain vocabulary — use its terms), and
[`docs/agents/`](docs/agents/) (issue-tracker + domain-doc conventions).

## Architecture

Two deliberately separate halves:

| Layer | Where | What |
|-------|-------|------|
| **Device layer** | [`bin/`](bin/README.md), `devices/`, `apks/` | Pure-bash, **Inspect-free** emulator broker: turns a device-spec into a booted, rooted, provisioned emulator and hands it out under a cap. |
| **Inspect layer** | [`swarm-eval/`](swarm-eval/README.md) | The `swarm_eval` package: bridged Claude Code agents, the launchers (`single_agent.py`, `swarm.py`), the messageboard, and the arbiter. |

Decisions behind the split live in [`docs/adr/`](docs/adr/); specs + tickets under `.scratch/<feature>/`;
a from-scratch manual device bring-up in [`RUNBOOK.md`](RUNBOOK.md).

> The public project is **android-swarm**; the in-repo Python package and paths are still named
> `swarm_eval` / `swarm-eval/` (rename deferred — see [`.scratch/codebase-cleanup/`](.scratch/codebase-cleanup/)).
