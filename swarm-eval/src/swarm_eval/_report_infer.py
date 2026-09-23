"""Host-side inference runner, executed *inside the safety-tooling submodule's own environment*.

`report.py`'s default synthesis backend invokes this script through
`uv run --project <safety-tooling> python _report_infer.py <in.json> <out.txt>` (see
`report.safetytooling_infer`). It runs in the submodule's interpreter — where `safetytooling` and
its pinned client stack (anthropic/openai/…) are installed — because that stack is mutually
exclusive with the swarm-eval harness's own pins (anthropic/openai/pydantic all differ), so the
two cannot share one venv. Keeping the actual model call here, at the process boundary, is how the
report's inference "runs via the safetytooling submodule" without dragging its dependency tree
into the harness.

This module imports ONLY `safetytooling` (and the stdlib); it never imports `swarm_eval`, so it
loads cleanly under the submodule's environment. Input JSON: `{"model", "system", "user"}`. It
writes the completion text to the output path and prints nothing to stdout on success.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


async def _run(model: str, system: str, user: str) -> str:
    from safetytooling.apis import InferenceAPI
    from safetytooling.data_models import ChatMessage, MessageRole, Prompt

    # cache_dir=None / prompt_history_dir=None: a report is a one-shot synthesis — no on-disk
    # cache or prompt-history side effects in the run's tree.
    api = InferenceAPI(cache_dir=None, prompt_history_dir=None)
    prompt = Prompt(
        messages=[
            ChatMessage(role=MessageRole.system, content=system),
            ChatMessage(role=MessageRole.user, content=user),
        ]
    )
    responses = await api(model_id=model, prompt=prompt, print_prompt_and_response=False)
    if not responses:
        raise RuntimeError("safetytooling returned no completion")
    return responses[0].completion


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: _report_infer.py <in.json> <out.txt>", file=sys.stderr)
        return 2
    payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    completion = asyncio.run(_run(payload["model"], payload["system"], payload["user"]))
    Path(argv[2]).write_text(completion, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
