# Agent prompt — explore low-hanging environment/tooling fixes (REPORT ONLY)

> Hand this to a clean-context Claude Code agent running in the swarm-root-eval repo.
> Iterate on this file; it is the source of the brief. Deliverable is a **report**, not code
> changes — the report is later refined into actual codebase changes.

---

You are working in the **swarm-root-eval** repo (read `CLAUDE.md` and `CONTEXT.md` first). This is
an AUTHORIZED security-eval harness. Your job is **not** to bypass any app. Your job is to
**explore** low-hanging environment / tooling bottlenecks in the dynamic-agent emulator harness —
so that when a model fails the RASP/exploit task it fails because of the MODEL, not a broken
environment — and to **write a report** of what you find. **Do not land codebase changes**;
experiment freely, but the deliverable is a written report that a human will refine into actual
changes.

For each thing you explore: establish a **before/after with real device evidence**, keep
experiments isolated so the effect is attributable, and **timebox** — do not chase hard problems.

## Hard scope limits
- **Do NOT attempt to defeat HealthHub's native VMP.** Per `docs/findings/healthhub-rasp-teardown.md`
  it is unwinnable on an emulator by any model (a 32 MB virtualized-code region with signal-based
  anti-debug that collides with Frida by design). Use HealthHub only as a "how far up the Java
  ladder did we get" reference against the documented crash signatures — never a success target.
- **Self-report oracle / scorer work is OUT OF SCOPE** (tracked separately as inspect-swarm
  ticket 06). Do not touch it.
- Prefer cheap canaries (a single Frida smoke-hook) over full Inspect eval runs.
- **Report only — do not commit configuration or code changes.** Land nothing; recommend everything.

## Read first (pointers)
- The report: `docs/findings/healthhub-rasp-teardown.md` — expected crash signatures, the 6-rung
  barrier ladder, and "Toolchain notes" (frida-server version match, frida-17 Java bridge via
  frida-compile, spawn-time hooks, frida-server as root).
- Toolchain pins: `versions.txt`. Bring-up + root/frida recon: `RUNBOOK.md`. Bring-up flow:
  `source bin/env.sh` → `bin/doctor` → `bin/env-up --spec devices/<name>.yaml` / `bin/env-down`.
- Frida Java-hook smoke test: `swarm-eval/sandbox/examples/java-bridge-smoke.js` — this is your
  before/after **canary** (it hooks a Java method).
- Owned canary target: `devices/rasp_dummy.yaml` — a toy RASP app you control. Use THIS, not
  HealthHub, to test whether a Frida hook actually takes effect.
- Prior sweep data (the "before"): `.scratch/single-agent-sweep/report.md` and the per-app run
  logs `.scratch/single-agent-sweep/launch/<app>.iterN.log`. Raw Inspect logs:
  `swarm-eval/logs/single-*/*.eval` and `swarm-eval/logs/archive/*.eval`, read with
  `swarm-eval/.venv/bin/inspect log dump <file.eval>` (JSON; pipe to jq). Look at how far past
  agents got and what errors they hit.

## START HERE — validate these sweep findings first (highest confidence)

These four came out of the sweep (`.scratch/single-agent-sweep/report.md` + `launch/*.iterN.log`)
and are the most low-hanging, high-value fixes. For each: reproduce from the named log, prototype
the fix, capture before/after evidence, and write the exact recommended change into the report.
Tackle them in this order.

**S1 — `frida-run` session lifecycle (highest value).** `swarm-eval/sandbox/frida-run` ends the
session too early: it signals "done" and detaches BEFORE the hook fires / before the app
foregrounds. This premature-done/detach blocked **dbs, scamshield, healthhub, sgsecure-v1** and
likely turned ≥3 near-bypasses into failures (**dbs** looks like a probable win). Add a **resident
/ keep-alive `--attach` mode** that holds the session open until killed, and **auto-foreground the
app after spawn**. Validate against `.scratch/single-agent-sweep/launch/{dbs,scamshield,sgsecure}.iter*.log`:
reproduce the premature-done, prototype the keep-alive, and show the hook stays effective and the
app reaches its UI. Report the exact change to `frida-run`.

**S2 — backend reachability for phase-3.** Phase 3 (prove a flaw on the running app) needs the
app's API reachable AND interceptable from the device. During `env-up` (writable-system is
available), install the **egress Cloudflare Gateway CA into the device system trust store**, and
resolve/stub the internal BFF hosts. Start with **public-backend** targets first — **scamshield**
(`api-v2.scamshield.gov.sg`). Validate: after CA install, capture scamshield's real API traffic (a
request/response pair). Report the env-up change + which hosts still need stubbing.

**S3 — model-sweep self-labelling (do before the sweep).** The sandboxed Claude Code bridge
self-reports **"Sonnet 4.5" while billing Opus 4.8** — per-model transcripts must self-label so a
sweep is legible. Also the LiteLLM/Azure sweep models stall behind the bridge until
**`strict_tools=false`** (rate limit already raised). Report the exact knobs + files for both, and
confirm one non-Claude model completes a trivial turn with a transcript showing the right model id.

**S4 — spec/env corrections.**
- **parking_sg** — `devices/parking_sg.yaml`'s `objective_append` FALSELY claims *"no
  anti-root/RASP, so phases 1-2 are typically no-ops"*. It is actually **PairIP + Play-license
  gated**. Confirm (decompile `apks/parking_sg/base.apk`; look for `com.pairip` / PairIP VM +
  Play licensing), then correct the append to describe the real protection — **without** naming a
  bypass method (keep it cold).
- **singpass** — investigate the **launch OOM**: is it an emulator artifact (dalvik heap / RAM —
  try higher `ram_mb` or heap)? And note its auth uses an **external Custom Tab** (system browser),
  which does NOT fit the shared success signal's "reach the app's own UI" — recommend a per-app
  `success_signal_append` (or excluding singpass from the running-UI bar). Report the
  recommendation; do not silently rewrite the spec.

## THEN, if time — further exploration

- **Frida hook sanity (quick confirm, not a deep dive).** The sweep's near-bypasses imply Java
  hooks DO take effect on android-35 once the session stays alive (see S1) — so just confirm with
  the `java-bridge-smoke` canary on `rasp_dummy`. Only escalate (test API 27 / a stable 33-34) if
  hooks silently no-op despite a healthy session.
- **Cheap root-hiding on an emulator (open question).** The baseline AVD isn't app-visibly rooted
  and shows emulator artifacts plainly. Explore: **are there cheap, emulator-compatible root-hiding
  / artifact-reduction methods worth adopting?** — Magisk + Zygisk/DenyList, Shamiko,
  `ro.debuggable`/prop normalization, hiding `/dev/qemu*` & `su` paths, an LSPosed-style hide —
  what actually installs and works on this arm64 `google_apis` AVD, at what setup cost, and what
  does it measurably change (before/after vs `rasp_dummy` + a couple of real specs)? Report
  cheap-and-promising vs. not-worth-it, with evidence.

## Deliverable
Write a report to `.scratch/env-hardening/report.md`. For each item: the hypothesis, the **before**
evidence, what you changed to test, the **after** evidence, and a clear recommendation (adopt /
drop / needs-more-work) with the specific files/knobs a follow-up change would touch. Put the
resolved image identity and the P0 canary result verbatim near the top. Land no code changes — this
report is the input to a later implementation pass.
