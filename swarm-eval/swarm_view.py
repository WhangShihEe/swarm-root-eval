"""`swarm-view` — the bespoke swarm-run review UI (swarm-improvements ticket 05, cut 1).

Thin root-level entrypoint mirroring `swarm.py`/`report.py`, so a finished run is turned into a
single self-contained HTML review (`logs/<swarm-id>/review.html`):

    # a specific run
    python swarm_view.py logs/<swarm-id>

    # no argument: pick from logs/ (newest default; a tty gets a numbered picker)
    python swarm_view.py

    # custom output path / inspect-view link-out target
    python swarm_view.py logs/<swarm-id> -o /tmp/review.html --view-port 7575

The real logic lives in `swarm_eval.viewer`: a thin builder over the pure `run_reader` (no model,
no `safetytooling`) that assembles one view model and injects it into one HTML template asset. It
builds no server — the live phase (FastAPI + SSE) is an explicitly named follow-up that feeds the
same frontend by swapping the data source. Also exposed as the `swarm-view` console script.
"""

from __future__ import annotations

from swarm_eval.viewer import main

if __name__ == "__main__":
    raise SystemExit(main())
