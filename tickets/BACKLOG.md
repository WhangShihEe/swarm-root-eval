# swarm-root-eval â Backlog

Eval comparing a **single** model vs a **swarm** (orchestrator + N workers, all **Claude
Code** via Inspect's `sandbox_agent_bridge()`) on Android pentest tasks:
(1) bypass in-app anti-root/root-detection, (2) find & construct vulns/exploits from a
running APK. Harness and Inspect are kept **separate**.

## Sets

- **Set 1 â Emulator harness (Inspect-free).** âï¸ detailed in `set-1-emulator-harness.md`.
  Bring up Android-37 Pixel from clean install, provision (root + frida + APK + settings),
  addressable emulator pool, full from-scratch rebuild each bring-up (no snapshot). APK-agnostic. **This is the current work.**
  Tracked as 5 vertical-slice tickets in `.scratch/emulator-harness/issues/01..05` (chain 01→02→03→04→05); `tickets/set-1-emulator-harness.md` is the horizontal-layer reference behind them.

- **Set 2 â Inspect toolbox container + bridged Claude Code (single agent).**
  `compose.yaml` toolbox with the offensive toolchain (jadx/apktool/frida-client/objection/
  adb) + injected target APK; run **Claude Code** in-sandbox with
  `ANTHROPIC_BASE_URL=http://localhost:13131` via `sandbox_agent_bridge()`; adb-connect to a
  pooled host emulator over `host.docker.internal`. Prove one bridged agent runs a trivial
  task and Inspect logs the full transcript.

- **Set 3 â Two agent *profiles* (both Claude Code).** *Static* profile: APK only, no
  emulator grant. *Dynamic* profile: static tools + granted emulator + frida. Differ by
  tools + `CLAUDE.md`/system prompt, not harness.

- **Set 4 â Orchestrator + N workers + shared message board.** Separate bridged agents (per-
  agent transcripts); message board as a shared service (MCP server, reachable from every
  sandbox) for coordinating research directions; emulator **check-out broker** (emulators are
  a scarce pooled resource, acquired on demand â static agents need none). First pass:
  1 orchestrator + 1 dynamic agent.

- **Set 5 â Per-app task manifests + scoring oracles.** Harness stays APK-agnostic; a thin
  per-app manifest (expected package, success signal, known-vuln checklist) plugs in here.
  Oracles for Task 1 (app reaches post-root-check state) and Task 2 (verifiable
  vuln/exploit); single-vs-swarm comparison + metrics.

- **Set 6 â Per-trial reset.** Wire from-scratch rebuild (createâbootâprovision) into the
  Inspect sample lifecycle as the between-trial reset. Add snapshot caching here only if
  bring-up time proves a bottleneck.

## Carried design notes
- **APK-agnostic harness vs per-app oracle** â resolved via per-app manifest at set 5.
- **Two-tier orchestration** (cheap static swarm + scarce emulator-gated dynamic agents) â
  emulator broker at set 4; harness already exposes emulators as an acquirable pool.
- **Multi-model** = swap Claude variants behind the bridge for now; cross-vendor (Claude Code
  â GPT/Gemini through the Anthropic-compat proxy) is a later, lossy experiment.
