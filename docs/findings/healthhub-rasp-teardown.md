# HealthHub RASP Teardown

> Authorized emulator research. Captured 2026-08-31; frida-hook root-cause added 2026-09-01.
> Source of record for this finding (originally a claude.ai artifact,
> `code/artifact/b3173ccf-de5a-46ea-8945-1ccb93cb1a1e`). Materialized here so a clean-context
> agent can read it.

| | |
|---|---|
| Package | `sg.gov.hpb.healthhub` |
| Version | 6.0.11 · vc 223 |
| Target SDK | 35 |
| Device | AVD · Android 17 (SDK 37) · arm64 |
| Protection | DexGuard-class Java layer + native VMP |

## Verdict

The crash is **not a bug**. HealthHub ships a commercial anti-tamper layer (RASP) that detects
the emulator and deliberately kills itself before drawing a pixel. Disabling USB debugging
changes nothing — that was never the trigger.

- The **Java-side** integrity checks are fully bypassable with Frida — enough to render the
  splash and reach Firebase init.
- The **native layer** — a 32 MB virtualized-code region using signal-based anti-debug — is the
  real gate, and it is hostile to instrumentation by design. **Runtime Frida cannot clear it.**

## 1. The failure

Launching on the emulator, the process dies instantly with no dialog. The DropBox
`data_app_crash` entry shows it never gets past its own `Application` constructor — the crash
originates in `attachBaseContext`, the first app code the framework runs:

```
FATAL EXCEPTION: main
java.lang.RuntimeException: Unable to instantiate application o.LazySemanticsKt
Caused by: java.lang.RuntimeException: 253928486
    at o.waitForFirstLayout.attachBaseContext(:933)
    at o.LazySemanticsKt.attachBaseContext(:2577)
```

All four split APKs install correctly, the ABI matches, `libdac2.so` loads fine — not a
packaging fault. The tell is the exception itself: a bare number, `253928486`, thrown from the
earliest possible entry point.

## 2. How we know it's RASP (6 traits)

1. **Coded exceptions** — messages are bare integers (`253928486`, `43568147`, `176268365`). Real
   exceptions describe themselves; obfuscated checks emit a code.
2. **Replicated everywhere** — the same guard sits in the `Application`, two `ContentProvider`s,
   and the base `Activity`. A bug doesn't reproduce identically across unrelated entry points.
3. **Varied kill vectors** — numeric throw, `ArithmeticException: /0`, `NullPointerException`, a
   direct `System.exit(10)`, then a native `SIGSEGV`.
4. **Impossible signatures** — decompiled overrides declare `attachBaseContext(Context) throws
   Throwable`; the real framework method can't. A DexGuard instrumentation fingerprint.
5. **Emulator probing** — a live trace caught a read of `…vendor_qemu_prop…` straight from the
   property store.
6. **Localized obfuscation** — only the guarded methods carry string-decryption, control-flow
   flattening, reflection; the rest of the app is normal.

## 3. The barrier ladder (checks fire in execution order)

Frida neutralized every Java-layer guard in turn; each time the next surfaced — until native.

| # | Where | Trigger | Status |
|---|-------|---------|--------|
| 1 | `Application.attachBaseContext` (`o.waitForFirstLayout`) | `RuntimeException 253928486` / `/0` | Bypassed |
| 2 | `ContentProvider.onCreate ×2` (`FirebaseInitProvider`, `o.OffsetNode`) | `RuntimeException 43568147` | Bypassed |
| 3 | `Application.onCreate` (`o.LazySemanticsKt`) | `RuntimeException 253928486` | Bypassed |
| 4 | base `Activity.attachBaseContext` (`o.describeContents`) | `NullPointerException` | Bypassed |
| 5 | direct self-terminate | `Process.killProcess` + `System.exit(10)` | Blocked |
| 6 | **native VMP enforcement** | `SIGSEGV` in a 32 MB anon r-x region @ `0x50000000` | **The wall** |

## 4. What was tried

- **Swallowing the checks** got from instant death → rendered splash → Firebase/GMS init. But the
  guards sit *inside* methods that also do real init, so swallowing the whole method skips that
  init and produces genuine downstream NPEs. Whack-a-mole that doesn't converge.
- **Spoofing the environment** — a comprehensive spoof (`Build.*`, Java `SystemProperties`, native
  `__system_property_get`, emulator file-path probes, all faked to a Pixel 7) did **not** stop
  even the first check. The verdict is computed in native code and does not flow through the APIs
  Java or libc expose. The property read that *did* show up — `/dev/__properties__/…vendor_qemu_prop…`
  — walks the property backing store directly, bypassing name-based hooks entirely.

## 5. The native wall

With the Java checks swallowed, the process still dies from a native `SIGSEGV`:

```
[NATIVE FAULT] access-violation @ pc=0x50000d08  access read 0x0
   region: base=0x50000000  size=33554432 (32 MB)  prot=r-x  file=<anonymous>
      libart.so!0x270cf8
```

A 32 MB anonymous, executable region at a fixed address is the signature of a **VMP** — a
virtualized native-code protector. The check logic runs inside it, entered from Java via JNI, and
advances using **deliberate null-read faults** its own signal handler processes — an obfuscation
technique that doubles as anti-debug: any foreign handler in the signal path (a debugger, or
Frida) breaks the flow. Frida's own interception lives on the same `SIGSEGV` path — they collide
by design. The app also **respawns un-instrumented processes** that escape any Frida attach and
die at check #1, and writes no tombstone.

## 6. Recommendations

- **Run on a physical retail device** — no emulator, no attached debugger; none of these traps
  trip and the app runs unmodified. Fastest path if the goal is to *use/observe* the app.
- **Corellium, then instrument what's left** — real ARM virtualization removes the emulator half;
  the VMP + signal anti-debug still fight any Frida/ptrace attach (a multi-week devirtualize
  effort, not a scripting task).
- **Magisk / root-hiding — not the tool.** Addresses neither the qemu-property detection nor a
  VMP anti-debug, and adds root artifacts the RASP can detect.
- **Static patch — low value.** The logic is virtualized native code; there's no branch to NOP
  without breaking the VMP first.

## 7. Toolchain notes (emulator harness)

- The AVD ran **Android 17 (SDK 37)**, on which **frida-server 16.x segfaults** — only the 17.x
  series runs. Match host and server versions exactly.
- Frida 17 removed the built-in `Java` bridge global. A plain script fails with `Java is not
  defined`; the agent must be built with **frida-compile** bundling **frida-java-bridge**.
- Early checks run in `attachBaseContext`, so hooks must be installed at **spawn** (`frida -f` /
  suspended spawn), not on a late attach.
- `frida-server` must run as **root**; a non-root server enumerates but cannot spawn.
