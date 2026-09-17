# 07: Dynamic-agent offensive-tooling layer — frida-17 usable + static tools + first green

**What to build:** close the gap between "the harness reaches the device" (ticket 04) and "the
agent can actually do offense." Make frida-17 usable (the built-in Java bridge is gone), fold
the static-analysis tools into the dynamic image (per CONTEXT `dynamic = static + dynamic`), fix
the over-promising mission prompt, and **iterate with the agent, human-in-the-loop, to a first
RootBeer bypass.** This is an **empirical iteration ticket**, not a hermetic one — its real
acceptance is a green run, so it needs the user in the loop.

**Blocked by:** 04 (infra proven end-to-end, commit a4d6cfb). **Milestone:** with ticket 06,
this unlocks the **model sweep** (sweep is gated on a first green).

**Status:** ready (human-in-the-loop iteration)

## Build items
- [x] **frida-17 Java bridge:** bake **`frida-java-bridge` + `frida-compile`** into the image so
      custom `Java.perform(...)` scripts **compile with the bridge and run** (today they die with
      `ReferenceError: 'Java' is not defined`).
- [x] **Non-interactive frida runner:** a helper/pattern in the sandbox that attaches, loads a
      compiled agent, waits for a completion signal or timeout, and **exits** — no lingering REPL
      (today `frida -l` hangs → agent SIGTERMs it, rc 143).
- [x] **objection** installed + verified working *today* (ships a compiled agent with the bridge
      → works on frida 17). Document a **non-interactive** invocation for the agent (e.g.
      `objection explore --startup-command "android root disable"`).
- [x] **Static tools in the dynamic image** (per CONTEXT — the omission was a bug against the
      definition): **jadx** (Java decompile), **apktool** (smali/resources), **aapt/apkanalyzer**
      (manifest), `file`, `strings`, `unzip`, plus a **JRE** for jadx/apktool. frida-tools stays
      pinned **17.17.0**; image still builds arm64 (corp-CA caveat).
- [x] **Mission prompt rewrite:** list **exactly** the tools present (kill "static tools may also
      be present"), and point the agent at: objection fast-path, custom-frida via `frida-compile`,
      the non-interactive runner, and the static tools.
- [x] **Fail-fast:** a task `time_limit` / model timeout so a hung/empty provider fails fast and
      **releases the broker device** instead of pinning it through the whole retry sequence.

## First green (empirical, human-in-the-loop)
- [ ] **Primary bar:** a real **RootBeer bypass** (`ROOTBEER_BYPASS: SUCCESS`) driven by
      **Claude**, reached by iterating on prompt + tooling with the user in the loop.
- [ ] **Fallback bar** (if RootBeer proves stubborn): **tools demonstrably usable** — a custom
      frida `Java.perform` script runs and hooks a method, objection runs a bypass, static tools
      are used, and a clean verdict line is emitted — even if this app isn't beaten.
- [ ] **Deliverable:** a short **iteration log** (runs, what broke, what changed) + the green
      (or best) transcript.

## Out of scope / notes
- **Reasoning-model output hygiene** (Qwen `<think>` leaking into content → `</think>` spam eats
  the verdict) is **OUT** → belongs with the **model sweep** as a bridge filter, alongside
  `swarm_eval/model_filters.py` (`merge_system_messages`). Parked.
- **First green on Claude**, not the cross-vendor providers: `deepinfra` Qwen returns malformed
  tool-call streams (empty turns → CC exits 1); `cerebras`/`novita` emit valid tool calls — a
  sweep-time concern, not this ticket's.
- This ticket is **iterative, not hermetic** — the user drives the loop; "done" is a real run.
- Ref: ticket 04, CONTEXT dynamic-agent definition, `swarm_eval/mission.py`.

## Iteration log

Deliverable per this ticket: runs, what broke, what changed, and the green (or best) transcript.
The **build items** are done and image-verified; the **First green** rows above are the empirical,
human-in-the-loop part — fill this log as you iterate.

### 0 — Build items landed & image-verified (setup, not a run)
- **Image:** `swarm-eval:t07` builds arm64, exit 0 (corp-CA caveat unchanged). All build-time
  smokes pass.
- **frida-17 Java bridge:** `frida-compile` + `frida-java-bridge` baked into scaffold
  `/opt/frida-agent`. Smoke: a `require('frida-java-bridge')` + `Java.perform` agent compiles to
  **750,659 bytes** (bridge bundled; a bare agent is a few hundred). Probe result: NODE_PATH does
  **not** resolve the bridge from an arbitrary cwd → **author custom agents inside
  `/opt/frida-agent`** (the mission prompt says exactly this).
- **Non-interactive runner:** `/usr/local/bin/frida-run` (venv-python shebang). Attaches/spawns,
  loads a compiled agent, exits on `send({type:'done',ok})` / agent error / timeout (rc
  0/2/3/124). No REPL. `frida-run --help` verified.
- **objection:** 1.12.5, `objection version` verified. Non-interactive form documented in prompt
  (`echo exit | objection -g <pkg> explore --startup-command "android root disable"`).
- **Static tools:** jadx 1.5.1, apktool 2.10.0, androguard 4.1.4, `file`/`strings`/`unzip`, JRE
  (OpenJDK 17). **Note (arch decision):** `aapt/apkanalyzer` were the ticket's named manifest
  tools, but their only Google-shipped binaries are **x86_64** and die under Rosetta on this
  arm64 image (same reason ticket 04 takes adb from apt, not platform-tools). Substituted
  **androguard** (pure-Python, arch-agnostic) + apktool/jadx, which all decode the manifest.
- **Mission prompt:** rewritten to name the exact toolset, the frida-17 bridge workflow, the
  runner, and the objection fast path; "static tools may also be present" removed.
- **Fail-fast:** `dynamic_agent(time_limit=1800)` (wall-clock) → on trip, cleanup releases the
  broker device. Overridable per run.
- **Tests:** 61 passed (2 new — exact-toolchain prompt assertions + the time-limit).
- **Left for the loop:** an actual `inspect eval` run against a broker-granted device (needs
  broker + emulator up) → first RootBeer green on Claude.

### Run template (copy per iteration)
```
### N — <one-line outcome>
- Command: inspect eval dynamic_agent.py --model anthropic/claude-... (time_limit=?)
- Broker/device: <serial, profile>
- What the agent did: <static recon → objection/frida path>
- What broke: <error / hang / wrong hook / verdict missing>
- What changed: <prompt tweak / tool fix / image rebuild>
- Verdict: RASP_BYPASS: SUCCESS|FAILURE  (log: logs/<...>.eval)
```
