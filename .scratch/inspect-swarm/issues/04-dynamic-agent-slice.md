# 04: Dynamic agent, end-to-end — one bridged CC agent works an APK on a broker-granted device

**What to build:** a **single dynamic agent** (CONTEXT: static tools **plus** a broker-granted
emulator + frida) running as **one bridged Claude Code agent in one Inspect run** (the
separate-runs swarm model — one agent = one bridge = one clean transcript, no subagent
interleaving). It runs in a sandbox with the **Android offensive toolchain**, is handed a
broker-granted device, reaches it over **adb from inside the sandbox**, and works the
**RootBeer** APK. Combines the agent building block with the **device-linking infra** — per the
decision that you can't prove the agent works without wiring the device. Self-report oracle.
**This is the reusable dynamic-agent unit that ticket 05 (swarm framework) launches N times.**

**Scope:** device-linking infra only. The swarm-level infra (messageboard, multi-instance
launcher, arbiter, N separate runs, log correlation) is **ticket 05**, not here.

**Blocked by:** 02 (done). Needs a running broker (`bin/broker start`).

**Status:** in progress — code complete + hermetically tested + image build-verified; the
live end-to-end run (against a running broker + booted emulator) is the remaining step.

## Acceptance
- [x] **Sandbox image extended:** `adb`, `frida`/`frida-tools` **pinned to match frida-server
      17.17.0** (hard build-time assert), `objection`, `python3`, baked in. **Host network
      enabled** via `compose.yaml` (bridge + `host.docker.internal:host-gateway`, NOT
      `network_mode: none`). Build verified green locally (inherits the gitignored corp-CA
      caveat). **adb is the Debian apt package, not Google's platform-tools** — the latter is
      x86_64-only and dies under Rosetta on the arm64 (Apple-Silicon) image whose emulator
      target is `arm64-v8a`. frida CLIs symlinked into `/usr/local/bin` so a login shell (which
      resets PATH and drops `/opt/frida/bin`) still resolves them.
- [ ] **Broker linking (control plane):** the Inspect **solver acquires** a device at sample
      **setup** via `bin/broker acquire` (writable-`/system` default profile), **injects the
      connection contract** (`serial/console_port/adb_port/profile`) into the sandbox, and
      **releases** at **teardown** via `bin/broker release`. A failed/timed-out run **still
      releases** — no leaked scarce slot.
- [x] **Broker linking (control plane):** `acquire_device` setup solver calls `bin/broker
      acquire --spec` and injects the contract; `release_device` cleanup calls `bin/broker
      release --serial` and runs on success/failure/timeout (Inspect `cleanup=`), no-ops when
      no grant was made, and never raises. Hermetically tested against a fake broker.
- [~] **adb reach (data plane):** the injected `/root/connect-device.sh` runs `adb connect
      host.docker.internal:<adb_port>` + a **two-sided frida version match** (client == 17.17.0,
      then `frida-ps -U` which aborts on a server mismatch). Wiring complete; the live
      handshake needs a booted device (pending run).
- [~] **The agent loop:** the mission (`swarm_eval/mission.py`) hands the bridged CC agent the
      staged **RootBeer APK** + contract + toolchain and asks for a real bypass attempt. Prompt
      complete; the actual attempt is the live run.
- [x] **Self-report scoring:** `self_report()` scorer extracts `ROOTBEER_BYPASS: SUCCESS|FAILURE`
      and matches the Sample target. Machine-checkable oracle deferred (gates the model sweep).
- [x] **One clean transcript** per agent — by construction (single agent, one bridge, no
      subagents; separate-runs model).
- [~] **Runnable standalone:** `inspect eval dynamic_agent.py` — task discoverable, Task
      constructs, image builds. The green end-to-end result is the pending live run.
- [x] Harness stays Inspect-free; broker used as a **client** (untouched). `broker_client.py`
      imports zero Inspect. Cap: single agent, device demand = 1.

## Notes / decisions
- **Who acquires the device = the solver (setup/teardown), not the agent.** Chosen for
  **guaranteed release** (an LLM worker can't leak a scarce device). Agent-driven acquire via a
  `bridged_tools` tool is a later option if workers must acquire on demand (ticket 05).
- **frida client/server version match** is a classic silent failure — pin the client to 17.17.0.
- **Board reaches workers host-side (`bridged_tools`) and needs no worker network — but adb
  does**, which is why this sandbox needs host network reach. (The board itself is ticket 05.)
- **Launch profile = writable-`/system`** (current env-up default; frida-only is a per-grant
  stealth fallback).
- Verify while building: the exact **contract-injection mechanism** (env vars vs task metadata
  vs a setup file written into the sandbox).

## Decisions settled while building
- **Contract-injection mechanism = files written into the sandbox** (chosen over env/metadata):
  the contract is per-sample *runtime* data, only known after acquire, so it can't ride on the
  solver's construction-time `env=`. Setup writes `/root/device-contract.env` (source-able) +
  an executable `/root/connect-device.sh`; the serial is also stashed in `state.metadata` so
  `cleanup` releases the right device.
- **adb = Debian apt package, not Google platform-tools.** Live build caught it: platform-tools
  is x86_64-only → `rosetta error` on the arm64 image (emulator target `arm64-v8a`).
- **`version="sandbox"`** on `claude_code()` — use the baked CC + toolchain and fail loud
  instead of a silent runtime download (now that the sandbox has host network).
- **Structure:** testable library in the `swarm_eval` package (`broker_client`, `mission`,
  `model_filters`); `dynamic_agent.py` at the project root is the `inspect eval` entrypoint
  (mirrors `smoke.py`). `merge_system_messages` hoisted to `model_filters` (was duplicated).
- **Tests:** pytest, hermetic — fake `bin/broker` via `SWARM_BROKER_BIN`, monkeypatched
  `sandbox()`/`acquire`/`release` (same fake-injection idiom as the harness bash suites). 21
  tests: contract parse/render, acquire/release, contract injection, scorer, verdict extraction.
- **Remaining = the live run:** `bin/broker start` then `inspect eval dynamic_agent.py --model
  anthropic/claude-…`. Can't be exercised here (no booted emulator); everything up to it is
  green.
- Ref: broker `.scratch/emulator-harness/issues/06-broker-service.md`;
  `inspect_swe` https://meridianlabs-ai.github.io/inspect_swe/claude_code.html
