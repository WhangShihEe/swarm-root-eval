"""Ticket 01 smoke: prove the Inspect wiring — task / dataset / scorer / logging —
with a MOCK solver (no model, no bridge, no emulator). The scorer greens on BOTH
S1 completion paths: a submit-style tool call, and a plain final-message match."""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageAssistant, ModelOutput
from inspect_ai.tool import ToolCall
from inspect_ai.solver import solver, TaskState, Generate
from inspect_ai.scorer import scorer, Score, Target, accuracy, stderr, CORRECT, INCORRECT
from inspect_ai.util import sandbox

TOKEN = "yes"
APK = str(Path(__file__).resolve().parent.parent / "apks" / "rootbeer" / "rootbeer.apk")


@task
def smoke():
    return Task(
        dataset=MemoryDataset([
            Sample(
                input=f"If you see this message, submit '{TOKEN}'",
                target=TOKEN,
                # APK staged into the sandbox via the Sample's files (the delivery mechanism).
                files={"rootbeer.apk": APK},
            )
        ]),
        solver=mock_answer(),
        scorer=token_present(),
        sandbox="local",
    )


@solver
def mock_answer():
    """Stand-in for ticket 02's bridged agent. Deterministically leaves the token in
    BOTH places a real agent might: the final completion, and a submit tool call."""
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # path (b): final-message match — the token is the completion text.
        state.output = ModelOutput.from_content(model="mock/mock", content=TOKEN)
        # path (a): submit-style tool call — what a real agent emits to finish.
        state.messages.append(
            ChatMessageAssistant(
                content="",
                tool_calls=[ToolCall(id="submit-1", function="submit",
                                     arguments={"answer": TOKEN})],
            )
        )
        # Criterion 5: confirm the APK was staged into the sandbox. Read as BYTES
        # (text=True would try to UTF-8-decode the binary zip and blow up), and assert
        # the zip magic so we prove it's really the APK, not just some file.
        apk = await sandbox().read_file("rootbeer.apk", text=False)
        assert apk[:2] == b"PK", "staged file is not a zip/APK"
        return state
    return solve


@scorer(metrics=[accuracy(), stderr()])
def token_present():
    """Custom scorer: it receives the whole TaskState, not just output.completion — so it
    can check EITHER path. That reach is what built-in match()/includes() don't give you."""
    async def score(state: TaskState, target: Target) -> Score:
        want = target.text
        # path (b): final message / completion
        if want in (state.output.completion or ""):
            return Score(value=CORRECT, answer=state.output.completion,
                         explanation="matched final completion")
        # path (a): a submit-style tool call carrying the token
        for msg in state.messages:
            for tc in (getattr(msg, "tool_calls", None) or []):
                if want in str(tuple(tc.arguments.values())):
                    return Score(value=CORRECT, answer=str(tc.arguments),
                                 explanation="matched submit tool call")
        return Score(value=INCORRECT, explanation="token in neither path")
    return score
