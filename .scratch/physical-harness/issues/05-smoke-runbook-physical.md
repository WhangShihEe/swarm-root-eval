# 05: Smoke + RUNBOOK for the physical path

**What to build:** A repeatable, documented end-to-end run on the phone, and proof the agent
can actually flip `rasp_dummy` to PASS on real hardware. Someone following the RUNBOOK from a
clean phone can reproduce the setup and the run; a smoke captures the win.

**Blocked by:** 03, 04.

**Status:** ready-for-agent

- [ ] RUNBOOK documents the one-time manual prereq (unlock bootloader + Magisk + DenyList + USB debugging) and the wireless-adb bring-up flow, calling out that it wipes the device and is not part of the harness.
- [ ] RUNBOOK documents the per-run flow: `bin/doctor`/`bin/verify` physical preflight → `python single_agent.py devices/pixel7.yaml` → where the contract and transcript land.
- [ ] A smoke runs `single_agent devices/pixel7.yaml` against `rasp_dummy` and asserts the run reaches the success signal — banner `UNLOCKED` / `verdict=PASS` and `FLAG{rasp-bypassed}` (via `RASPTARGET` logcat or screencap) — captured in the run log.
- [ ] The smoke tolerates the device flakiness (retry/skip-with-clear-message when the phone is absent) so it never hangs a suite.
- [ ] RUNBOOK notes the known real-hardware detector picture (`emulator` won't fire; frida-server trips the `frida` check, which the agent must defeat) so a reader interprets a run correctly.
