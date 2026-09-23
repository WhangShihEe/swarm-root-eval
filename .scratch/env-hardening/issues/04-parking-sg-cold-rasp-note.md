# 04: parking_sg mission states its protection truthfully (cold)

**What to build:** The parking_sg mission no longer misleads the agent that the app has no
anti-root/RASP. It states — coldly, naming no bypass — that the app is PairIP-wrapped (the native-VM
variant) and Play-license gated, so it may refuse to reach its UI on the non-Play image, and phases
1–2 are real work here rather than a no-op. This stops the agent from mis-attributing a launch block
to the environment and skipping the protection phase.

**Blocked by:** None (can start immediately).

**Status:** done

Context: `.scratch/env-hardening/report.md` §S4a — static analysis of the parking_sg APK confirms
PairIP VM classes, the native `libpairipcore.so` (so it is the native-VM variant, not license-only),
and the PairIP Play-license classes.

- [x] The false "no anti-root/RASP … phases 1-2 typically no-ops" language is removed from the
      parking_sg device-spec's objective note.
- [x] The replacement names the real protection cold: PairIP (a native VM component ships in the arm64
      split) plus a Play-licensing check that does not pass on the non-Play image, so the app may
      refuse to reach its real UI — with **no** bypass method (no frida/patch/license-stub) named,
      consistent with the shared cold prompt.
- [x] The existing paid-session Confidentiality/Integrity phase-3 example is preserved.
- [x] A note kept out of the cold prompt (comment or follow-up) flags that making parking_sg actually
      launchable/testable — stub the license gate, ship a debuggable build, or accept it as a
      "protected, may not launch" target — is a separate human decision.

## Comments

- **Done (this branch).** The objective note lives in `configs/apps/parking_sg.yaml`
  (`objective_append:`), not `devices/parking_sg.yaml` — the yaml-config refactor moved app/mission
  slots to `configs/apps/`. Confirmed the resolved mission text via `target.py::_mission_fields`.
  The false "no anti-root/RASP … phases 1-2 typically no-ops" clause is replaced with a COLD
  PairIP + Play-licence description (no bypass method named); the paid-session
  Confidentiality/Integrity phase-3 example is preserved verbatim.
- **Human decision (kept out of the cold prompt).** Making parking_sg actually launchable/testable
  — stub the Play-licence gate, ship a debuggable build, or accept it as a "protected, may not
  launch" target — is a separate human call. This ticket only makes the mission state the
  protection truthfully; it does NOT make the app run. Flag also recorded as a `#` comment in
  `configs/apps/parking_sg.yaml` above `objective_append:` (comments are never concatenated into
  the mission, so it reaches humans, not the agent).
