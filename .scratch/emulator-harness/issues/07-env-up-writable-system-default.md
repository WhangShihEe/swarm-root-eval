# 07: Device-spec defines the launch profile; env-up delivers writable-`/system` as the default

**What to build:** the device-spec becomes the full definition of how a device launches. It
gains a launch-profile toggle — a boolean `writable_system` (absent ⇒ `true` ⇒ the
writable-`/system` profile; `false` ⇒ the Frida-only profile) — and `env-up` reads it and
brings the device up accordingly, with **writable-`/system` as the default**. On the
writable-`/system` profile `env-up` runs ticket 02's proven recipe end to end (cold-boot with
`-writable-system` → root → `disable-verity` → reboot → re-wait for boot → `remount`), then
provisions to **t=0** on top, so the granted device has **both** a writable `/system` **and**
frida. Frida-only stays available for images/targets that want the untouched-`/system`,
lower-footprint foothold. This flips ticket 02's recorded default, so the reversal is recorded.

**Blocked by:** None (can start immediately; builds on the done bring-up + provisioning from
tickets 03–04, and on ticket 02's verified writable-`/system` recipe in `RUNBOOK.md`).

**Status:** ready-for-agent

- [ ] The device-spec gains a `writable_system` boolean; **absent means `true`** (writable-`/system`). The spec fully defines the launch — the normal path needs no CLI flag. An invalid value is rejected by spec validation like any other bad field.
- [ ] `env-up` resolves the launch profile from the spec and brings the device up on it, defaulting to writable-`/system` when the flag is absent.
- [ ] The writable-`/system` bring-up runs the proven recipe: cold-boot with `-writable-system`, `adb root`, `disable-verity`, **reboot**, re-wait for the device to come back, `remount` → `/system` is RW (overlayfs), then provision to t=0 (root shell, frida-server v17.17.0, APK install, normalized settings) on top. The device ends with a writable `/system` **and** frida running.
- [ ] The Frida-only profile (`writable_system: false`) still yields today's behaviour — root + frida-server + APK, `/system` untouched — unchanged.
- [ ] An explicit `env-up` CLI override can force either profile for a one-off run, taking precedence over the spec's value.
- [ ] `verify` confirms, on the writable-`/system` profile, that `/system` is genuinely writable (write → read-back → delete of a throwaway file) and that frida is up; on Frida-only it confirms frida is up and does not require a writable `/system`.
- [ ] Writable-`/system` bring-up **fails loudly** if `/system` cannot be made writable — no silent fallback to Frida-only. A caller that asked for a writable `/system` must never be handed a device that lacks it.
- [ ] The default reversal (writable-`/system` over Frida-only) is recorded — an ADR and/or the `CONTEXT.md` "Writable-`/system` verdict" glossary entry updated — since it overrides ticket 02's verdict. The provisioning invariant "the harness writes only to `/data`" still holds: the profile *grants the agent* a writable `/system`; the harness does not itself write app/system files there.
- [ ] Demoable live: a from-scratch `env-up` on a default (or `writable_system: true`) spec yields a device where `adb shell touch /system/<x>` succeeds and `frida-ps -U` reaches it; a `writable_system: false` spec yields the untouched-`/system` device with frida up.
