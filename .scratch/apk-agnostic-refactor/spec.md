# APK-agnostic eval + entrypoint split

**Goal:** the eval run is IDENTICAL for every APK — any difference between two runs is fully
defined by that target's `devices/<name>.yaml`, nothing app-specific hardcoded in Python. And
the eval has **two clean entrypoints** over **one** agent unit:

1. `single_agent.py` — a host-side launcher for ONE dynamic agent (leases a device, sets the
   budget/time-limit, runs the agent, releases the device). Used to see whether a single model
   makes progress, and to check the single-agent environment works.
2. `swarm.py` (→ `conductor.py`) — a host-side launcher for N dynamic agents plus the swarm-only
   layer (shared messageboard, agent ids, arbiter, collation).

Both select a target by passing **only** the yaml, e.g. `python single_agent.py devices/healthhub.yaml`
/ `python swarm.py devices/healthhub.yaml`.

## Module roles after the refactor

| module | role |
|---|---|
| `swarm_eval/target.py` *(new)* | read the one device yaml → `TargetConfig` (the Python-side counterpart to bash's `bin/_spec.sh`) |
| `swarm_eval/mission.py` | turn a `TargetConfig` into the ONE generic mission prompt + the verdict contract |
| `swarm_eval/agent_runner.py` *(new)* | shared host-side per-run machinery: lease a device → inject the contract → launch one `dynamic_agent` (subprocess) with budget/time-limit → release |
| `dynamic_agent.py` | the `@task` agent unit: given a target (`-T spec=`) + an INJECTED device contract, attack the app. Never talks to the broker itself. Spawned N× by the conductor, 1× by single_agent |
| `single_agent.py` *(new)* | entrypoint 1 — one device, one dynamic agent, no board |
| `swarm.py` + `conductor.py` | entrypoint 2 — N agents + board/arbiter/ids/collation, over the same per-run machinery |

## Key design decisions (settled)

- **Device acquire/release is a launcher concern, not an agent concern.** It leaves the Inspect
  task and moves host-side into the launchers (guaranteed release via a host `try/finally`).
  A contract is ALWAYS injected; `dynamic_agent` fails fast if none is present.
- **`dynamic_agent` keeps a thin `@task`** (it is the spawnable worker, not a pure library) with
  a `build_dynamic_task(target, *, swarm=None, …)` builder under it.
- **The swarm signal** (board-tools + collaboration prompt) is the presence of the board env
  (`SWARM_ID`), not `DEVICE_CONTRACT` (which is now always set).
- **The shared per-run machinery is launched as a subprocess** (`inspect eval dynamic_agent.py
  -T spec=… --model … --time-limit …`), the same way for single and swarm.
- **The yaml is the single source of truth**, read by two consumers: bash bring-up (`bin/_spec.sh`,
  `_provision.sh`) parses specific top-level keys with `yq`; Python parses the same file for the
  APK file-set + mission fields. The new `app:` block is additive nested keys the bash layer ignores.

## Load-bearing constraints to preserve

- `filter=sweep_generate_filter` stays wired into `claude_code(...)` (strips leaked `<think>`
  from non-Claude models); `model_config="claude-sonnet-4-5-20250929"` + `version="sandbox"` stay.
- The self-report scorer + `extract_self_report` + the verdict token stay (a generic token is fine).
- APK(s) staged at `/root/<name>` (agent cwd is `/root`); split sets stage base + all `split_config.*`.
- Swarm mode keeps board-tools + the `swarm_prompt` collaboration wrapper.

## Out of scope

- Fixing that frida Java method-hooking silently fails on this emulator (known env issue).
- Replacing the self-report scorer with a device-verifying oracle (a separate known-needed
  feature — inspect-swarm ticket 06 — note it, don't build it here).
- Model/provider/latency choices.

## Tickets

- `01` — `TargetConfig` loader + yaml `app:` blocks (prefactor)
- `02` — one generic mission + yaml-selected target through `dynamic_agent`
- `03` — host-side device lease (`agent_runner`) + `single_agent.py` + conductor/swarm migration
