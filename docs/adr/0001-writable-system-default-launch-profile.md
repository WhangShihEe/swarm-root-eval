# ADR-0001: Writable-`/system` is the default dynamic-agent launch profile

**Status:** accepted (2026-09-03) — reverses the default recorded in ticket 02 / `RUNBOOK.md`.

## Context

Ticket 02's writable-`/system` recon (`RUNBOOK.md` → "Writable-`/system` verdict") proved
that the API-35 rootable image *can* give an agent a writable `/system` — cold-boot with
`-writable-system`, `adb root`, `disable-verity`, reboot, `remount` → `/system` mounted RW
via overlayfs (write / read-back / delete confirmed live). But it recorded the **Frida-only**
profile (root shell + frida-server, `/system` untouched) as the **default** dynamic-agent
launch profile, reserving writable-`/system` as an opt-in variant, because the demo-tier
anti-root tasks are solvable with frida alone and Frida-only has a lighter footprint.

As the probe moves past the demo tier, the capability we actually want to hand a dynamic
agent is the **broader** one: a writable `/system` unlocks build.prop overlays, a system CA
cert for transparent TLS interception, and a persistent system `su` — the on-disk changes
that some RASP bypasses need — while still giving frida on top. Making the narrower profile
the default meant every real target run had to remember to opt in.

## Decision

**Writable-`/system` is the default launch profile.** The device-spec's `writable_system`
boolean is the full definition of how a device launches: absent ⇒ `true` ⇒ writable-`/system`;
`false` ⇒ Frida-only. `env-up` reads it (a CLI `--writable-system`/`--frida-only`/`--profile`
override wins for one-off runs) and, on the writable-`/system` profile, runs ticket 02's proven
recipe end to end, then provisions to t=0 on top — so a granted device has **both** a writable
`/system` **and** frida. Frida-only stays available for images/targets that want the
untouched-`/system`, lower-footprint foothold.

Writable-`/system` bring-up **fails loudly** if `/system` cannot be made writable — there is no
silent fallback to Frida-only. A caller that asked for a writable `/system` is never handed a
device without one.

## Consequences

- The `RUNBOOK.md` verdict's "Frida-only by default" line is superseded by this ADR; the recipe
  and evidence there remain valid (they are what `env-up` now automates).
- The provisioning invariant still holds: **the harness writes only to `/data`** (see
  `CONTEXT.md` → "Provisioning"). The writable-`/system` profile *grants the agent* a writable
  `/system`; the harness itself does not write app/system files there. Making `/system` RW
  (disable-verity + remount) is a mount-state change, not a harness file write into `/system`.
- The broker/pool honor the spec-resolved profile (ticket 08); `env-up` derives it from the
  spec it is already given, so the default path forwards nothing special.
