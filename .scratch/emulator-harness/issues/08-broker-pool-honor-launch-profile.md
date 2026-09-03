# 08: Broker + pool honor the spec's launch profile end to end

**What to build:** thread the ticket-07 launch profile through the pool engine and the broker,
so a brokered device comes up under the profile its spec defines — writable-`/system` by
default. The broker stops owning a default profile: a grant **honors the spec** (ticket 06's
start-time `--profile` demotes to an optional override that forces one profile across every
grant). The effective profile each device was launched under is visible in the connection
contract, `ping`, and `status`, so a client knows whether it was handed a writable `/system`.

**Blocked by:** 07.

**Status:** done

- [x] `bin/broker start` with no flag grants writable-`/system` devices (because specs default to it and the broker honors the spec). The broker no longer refuses or force-downgrades the profile.
- [x] The pool engine records the effective launch profile per slot so `status` and the connection contract can report it. The default path forwards nothing special — `env-up` derives the profile from the spec it is already given.
- [x] `broker start --profile <p>` becomes an optional **override** applied to every grant, taking precedence over the spec (e.g. force Frida-only across a run for a lighter footprint); the override reaches `env-up` via the pool.
- [x] The connection contract, `ping`, and `status` report the **real** profile each device was brought up under (spec-resolved, or the override when one is set), not a fixed string.
- [x] The broker `demo` verifies a default-start acquire yields a writable-`/system` device (`/system` writable and frida up), and releases cleanly.
- [x] No Inspect import anywhere in the harness (the ticket-06 invariant still holds).
