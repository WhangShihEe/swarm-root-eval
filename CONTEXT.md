# CONTEXT — swarm-root-eval glossary

The vocabulary this repo uses. When naming a concept in a ticket, commit, or hypothesis, use
the term as defined here; don't drift to synonyms. Decisions that shaped these live in
`docs/adr/` (created lazily as decisions are recorded).

## The eval

- **Capability probe** — the actual goal: *can a swarm compromise a real app at all*, and do
  some models do it better than others. This is feasibility + discovery, **not** a
  fairness-controlled benchmark. A green result answers "it's possible," not "swarm beats
  single by X%."
- **Model sweep** — vary the model served behind the bridge (Claude variants first,
  cross-vendor later and lossy) to rank them. Gated: it runs **only after a first green** —
  sweeping models over a task no config can pass yields no signal.
- **N=1-is-single** — the single-agent case is the swarm at N=1, a config, not a separate
  build. Both the agent layer and the device layer avoid special-casing N=1.
- **APK-in interface** — the agent always receives exactly one **APK file**; the harness
  derives everything else from it and never branches per app.
- **Target ladder** — the sequence of targets: **RootBeer** (known anti-root sample) → a
  custom **RASP** crash-on-root app we own (ground truth we control) → an **authorized** real app.

## Agents

- **Swarm** — an **orchestrator** plus N bridged Claude Code **workers**.
- **Static agent** — has the APK and static tools (jadx / apktool); no emulator. Cheap,
  effectively unbounded in count.
- **Dynamic agent** — static tools **plus** a broker-granted emulator and frida. Scarce,
  gated by the broker.

## Device layer (the harness)

- **Broker** — a standing host process, **started before any eval**, that owns the emulator
  pool and its cap, and **grants / launches / reclaims** devices on request. The gate that
  makes emulators a scarce, shared resource; it enforces the cap, not Inspect.
- **Pool engine** — the in-process engine the broker wraps: launches, tracks (a registry),
  and reclaims N provisioned devices. Ticket 05.
- **Connection contract** — what `acquire()` returns: `{serial, console_port, adb_port}` — how
  a client reaches a granted device.
- **Brokered-adb** — the access model: the broker grants scoped **adb** access to its device;
  the agent then runs frida / objection / adb-shell itself. Not a gesture (screenshot/tap) API.
- **Provisioning** — taking a booted device to **t=0**: root shell, frida-server (pinned
  **v17.17.0**), APK install (package + launch activity via `apkanalyzer manifest`), normalized
  settings. Writes only to `/data` — **never `/system`**.
- **Device-spec** — the declarative YAML (`devices/pixel-a37.yaml`) that drives the device
  layer, parsed with **`yq`** (a pinned harness dependency).
- **Reset = full rebuild** — every bring-up and every reset is create → cold boot → provision
  from scratch. No golden snapshot (revisit only if bring-up time proves a bottleneck).
- **Writable-`/system` verdict** — recon output (ticket 02): whether this image supports a
  writable `/system`. It does. **Writable-`/system` is now the default dynamic-agent launch
  profile** (ticket 07 / ADR-0001): `env-up` cold-boots with `-writable-system` and runs the
  proven `disable-verity` + reboot + `remount` recipe, then provisions frida on top — so a
  device has both a writable `/system` and frida. **Frida-only** (root shell, `/system`
  untouched, lighter footprint) stays available via `writable_system: false`.
- **Launch profile** — how a device is brought up, defined by the device-spec's
  `writable_system` boolean (absent ⇒ `true` ⇒ writable-`/system`; `false` ⇒ Frida-only). An
  `env-up`/broker CLI override can force either for a one-off run. Writable-`/system` bring-up
  fails loudly if `/system` cannot be made writable — never a silent fallback to Frida-only.

## Inspect layer (separate, later)

- **Inspect** — used as the eval framework only (run / log / score). Kept separate from the
  harness; no Inspect import in harness code.
- **Inspect bridge** — `sandbox_agent_bridge()`: a proxy inside the sandbox
  (`ANTHROPIC_BASE_URL=http://localhost:13131`) relaying model calls to Inspect's current
  provider. Inspect logs the transcript **passively**; the agent runs its own loop and signals
  completion by **returning**. Model sweep = swap the served model (`inspect/<provider>/<model>`),
  agent code unchanged.
- **Oracle** — the success check. MVP = agent **self-report** + manual verification; the real
  oracle is a per-app **manifest** declaring a concrete, machine-checkable success signal
  (e.g. app reaches its post-root-check state, observed independently from logcat/state).
