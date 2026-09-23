# 04: README quickstart-accuracy fixes (ticket 02 follow-up)

**What to build:** Correctness fixes to the public README shipped in ticket 02. A `/code-review`
pass after ticket 03 found the "runs out of the box" Quickstart is broken on a fresh clone and
that a CI-relevant contract was dropped in the rewrite. Close the gaps so the advertised copy-paste
path actually works and automation-facing contracts are documented again. Docs-only; no code change.

**Blocked by:** None (02 is `done`; this amends its output).

**Status:** ready-for-agent

- [ ] **Missing CA-bundle prerequisite (breaks first-run build).** The Quickstart lists Docker as a
      prereq but omits the corporate CA bundle at `swarm-eval/certs/ca-bundle-cf.pem`. The sandbox
      image `COPY`s it (`swarm-eval/Dockerfile:47`) and `certs/` is gitignored, so on a fresh clone
      the first `single_agent.py` run fails the image build with `COPY failed: ... no such file or
      directory` — contradicting "Runs the owned RASP-dummy target out of the box." Restore the
      prerequisite line the pre-rewrite README carried (bundle path + that it's a corporate cert,
      never committed), or mark it inline `<WIP>` with a note if the intended public story is a
      bundle-free image. Keep it compact / above-the-fold.

- [ ] **Dropped swarm exit-code contract + fail-fast warning.** The rewrite removed `swarm.py`'s
      documented exit codes (0 success / 1 failure / 2 setup-fail) and the warning that running
      `inspect eval dynamic_agent.py` directly fails fast. Both matter for wiring `swarm.py` into
      CI/automation. Restore them — likely in the terse Architecture section or a short "Running the
      swarm" note — verifying the codes still match `swarm.py` before documenting.

- [ ] **Hardcoded release serial can leak a leased slot.** The smoke block shows
      `bin/broker acquire` with the serial as a varying placeholder (`# → serial=…`) but the next
      line releases `emulator-5554` literally. If the broker grants a different serial the release is
      a no-op and the slot stays leased, so the following `single_agent.py` can't acquire (pool at
      cap). Make the release use the actually-granted serial (capture it, or show the release as
      operating on the acquired device) so the smoke sequence is self-consistent.

- [ ] Re-run `/code-review` on the README diff and confirm all internal links still resolve
      (they did at ticket 02 time) before marking done.

## Notes

- `cd android-swarm` (README:54) was reviewed and is **intentional** — it matches the deferred
  public repo branding (`android-swarm`; internal checkout stays `swarm-root-eval`). Not in scope.
- Source: `/code-review --low` after documentation ticket 03. The CA-bundle and exit-code items
  were verified against `swarm-eval/Dockerfile` and the pre-rewrite README; the serial item is a
  read of the current Quickstart block.
