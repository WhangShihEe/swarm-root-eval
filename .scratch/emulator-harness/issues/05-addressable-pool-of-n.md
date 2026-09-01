# 05: Scale to an addressable pool of N

**What to build:** `env-up` can bring up N provisioned devices at once on distinct ports,
tracked in a registry that hands out addressable device handles — the seam later sets consume.
This is the set-1 exit criterion.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] `env-up TARGET_APK=<path> N=2` launches 2 provisioned devices on distinct console/adb port pairs (5554/5555, 5556/5557, …).
- [ ] A registry maps serial → console port → adb port → status; `acquire()` / `release()` flip status (no scheduling policy yet).
- [ ] `N=1` is the default and is not special-cased in the code.
- [ ] `env-down` tears down every instance and clears the registry.
- [ ] No Inspect import anywhere in the harness.
