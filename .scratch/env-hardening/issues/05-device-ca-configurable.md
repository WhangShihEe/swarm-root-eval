# 05: env-up trusts a configured egress CA on the device (org-gated, inert by default)

**What to build:** On a host that supplies its own egress-proxy CA, env-up makes the emulator trust
it, so proxy-fronted backends become reachable and interceptable — the precondition for any phase-3
finding on a network-backed target. On any host that supplies no cert, the step is a silent no-op, so
the feature ships to everyone inert and nothing org-specific is ever committed (no separate branch).

**Blocked by:** None to build. The live traffic-capture part of validation pairs with 01 (a resident
frida session is what holds a hook open long enough to capture traffic).

**Status:** code-merged (device-validation pending) — criteria 1,2,4,5 done + merged into feat/yaml-config-extension; criterion 3 (on-device TLS probe to scamshield) deferred to orchestrator Phase B

Context: `.scratch/env-hardening/report.md` §S2. Mirrors the existing precedent where the sandbox
already trusts an out-of-band corporate CA kept in a gitignored certs location. Device-confirmed on
android-15: the runtime trust store is the Conscrypt APEX, not the legacy system cacerts dir.

- [ ] During writable-`/system` env-up, CA(s) supplied out-of-band (in the already-gitignored certs
      location) are installed into the device trust store; with no cert present the step no-ops cleanly.
- [ ] The cert lands where the running OS actually reads trust on this image — the Conscrypt APEX
      store — not the legacy system cacerts directory (which is writable but not honored at runtime on
      android-15).
- [ ] Validated by an on-device TLS probe to a proxied host: the chain now validates. First target a
      public backend (scamshield's API) and capture one real request/response pair.
- [ ] Nothing org-specific is committed: the certs location stays gitignored, and a clone with no cert
      builds and boots with the step inert.
- [ ] Flagged as separate follow-ups (not built here): TLS certificate pinning is a per-app wall a
      trusted CA alone will not defeat, and internal-only backend hosts need DNS stubbing.

## Comments
