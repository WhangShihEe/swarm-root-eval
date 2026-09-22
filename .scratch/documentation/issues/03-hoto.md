# 03: Private HOTO (handover)

**What to build:** A private handover package for the supervisor and future teams. A human reads
one document to understand where things stand, the shape of the agent-driven workflow, and where
to pick up; a second file lets them bootstrap an AI agent to continue the work or interview for
more detail. Kept short and compact.

**Blocked by:** 02 (the handover's TLDR points at the finished README).

**Status:** ready-for-agent

- [ ] `docs/handover/` added to `.gitignore` (private; not in public history).
- [ ] `docs/handover/HANDOVER.md` (human-read):
      - TLDR that points to the README for the general shape.
      - A human-readable explanation of the **agent workflow** used here (AI Hero, matt-pocock
        skills, the grilling -> tickets loop) so a reader grasps *how the work gets done*.
      - "Start here if lost" = implement the **physical connection**; point at the already-scoped
        `.scratch/physical-harness/` (spec + 5 tickets: WiFi adb, broker extended to a real phone,
        multi-device-ready).
      - **Future workstreams** where the author left off: physical phone (RASP checks likely pass on
        real hardware where the emulator is walled); larger runtimes / stronger models / larger swarms
        / better harness (gated by time+budget, not capability — "the model is not the bottleneck");
        and real-login access (Singpass / NRIC / phone numbers for authorized white-hat pen-testing —
        cannot meaningfully test without real credentials, and the author's own ID cannot be used).
- [ ] `docs/handover/CONTINUE.prompt.md` (AI-only bootstrap): a prompt that spins up an agent to
      continue *or interview for more*, pointing at the grilling-skill workflow and the
      `.scratch/physical-harness/` tickets as the first concrete pickup.
