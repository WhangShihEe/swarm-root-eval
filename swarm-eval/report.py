"""`report` — the post-run report CLI (swarm-improvements ticket 04).

Thin root-level entrypoint mirroring `swarm.py`/`single_agent.py`, so a finished run is turned
into `logs/<swarm-id>/report.md` with:

    python report.py logs/<swarm-id>
    python report.py logs/<swarm-id> --model claude-sonnet-4-5-20250929

The real logic lives in `swarm_eval.report` (collation via the pure `run_reader`, then a direct
host-side LLM synthesis through the safety-tooling submodule). The report model defaults
independently of the eval's swept `--model`; see that module's docstring.
"""

from __future__ import annotations

from swarm_eval.report import main

if __name__ == "__main__":
    raise SystemExit(main())
