# 05: env-up trusts a configured egress CA on the device (org-gated, inert by default)

**What to build:** On a host that supplies its own egress-proxy CA, env-up makes the emulator trust
it, so proxy-fronted backends become reachable and interceptable — the precondition for any phase-3
finding on a network-backed target. On any host that supplies no cert, the step is a silent no-op, so
the feature ships to everyone inert and nothing org-specific is ever committed (no separate branch).

**Blocked by:** None to build. The live traffic-capture part of validation pairs with 01 (a resident
frida session is what holds a hook open long enough to capture traffic).

**Status:** done (install device-confirmed) — criteria 1,2,4,5 done + merged; criterion 3 PARTIAL: CA install into the Conscrypt APEX store confirmed live on-device; end-to-end TLS-interception probe not runnable from this emulator (no on-device openssl/curl/wget) and needs a confirmed corp-proxied egress path — documented as the remaining follow-up

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

## Phase B on-device confirmation (criterion 3) — CA INSTALL PASSED; live TLS probe deferred

On the same brokered writable-system device, ticket-05 env-up ran automatically (corp CA present in
the gitignored `swarm-eval/certs/`). Broker log: `device-ca: installed 2 CA file(s) into
/apex/com.android.conscrypt/cacerts`. On-device the Conscrypt APEX cacerts store held 150 certs vs
147 in the legacy `/system/etc/security/cacerts` — the corp CA landed in the RUNTIME-HONORED APEX
store, as designed.

The live TLS-interception probe (openssl s_client to a proxied host) was NOT run: this android-15
emulator ships no `openssl`/`curl`/`wget` in its shell, so a device-trust-store TLS check needs an
app-level / Java-frida HTTPS probe, AND it is only meaningful if the emulator's egress is corp-
proxied (unconfirmed here — the docker BUILD egress is proxied, but the emulator's runtime egress
path is separate). Remaining follow-up, consistent with this ticket's own "TLS pinning + DNS
stubbing are separate" note.
