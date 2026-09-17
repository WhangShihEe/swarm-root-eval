"""Ticket 02 smoke: prove the full bridged path — task / dataset / scorer / logging with a
REAL Claude Code agent over sandbox_agent_bridge() (via inspect_swe.claude_code()), keyless
in the sandbox. The scorer greens on BOTH S1 completion paths: a submit-style tool call, and
a plain final-message match."""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageAssistant, ModelOutput
from inspect_ai.tool import ToolCall
from inspect_ai.solver import solver, TaskState, Generate
from inspect_ai.scorer import scorer, Score, Target, accuracy, stderr, CORRECT, INCORRECT
from inspect_ai.util import sandbox
from inspect_swe import claude_code
from inspect_ai.model import (
    ChatMessage, ChatMessageSystem, GenerateConfig, GenerateInput,
    Model, ModelOutput,
)
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_swe import claude_code

TOKEN = "yes"
APK = str(Path(__file__).resolve().parent.parent / "apks" / "rootbeer" / "rootbeer.apk")


@task
def smoke():
    return Task(
        dataset=MemoryDataset([
            Sample(
                input=f"If you see this message, first create 3 subagents. One should create a file which containes a poem. The other 2 should echos 'hello'. After all the finished, then submit '{TOKEN}'",
                target=TOKEN,
                # APK staged into the sandbox via the Sample's files (the delivery mechanism).
                files={"rootbeer.apk": APK},
            )
        ]),
        solver=claude_code(model_config="claude-sonnet-4-5-20250929", filter=merge_system_messages),
        scorer=token_present(),
        sandbox="docker",
    )

async def merge_system_messages(
    model: Model,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> ModelOutput | GenerateInput | None:
    system = [m for m in messages if isinstance(m, ChatMessageSystem)
          and not m.text.startswith("x-anthropic-")]
    if len(system) <= 1:
        return None
    merged = ChatMessageSystem(content="\n\n".join(m.text for m in system))
    rest = [m for m in messages if not isinstance(m, ChatMessageSystem)]
    return GenerateInput(
        input=[merged, *rest], tools=tools, tool_choice=tool_choice, config=config
    )

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
