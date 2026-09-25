import argparse
import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    Message,
    ToolUseBlock,
    query,
)

from claude_scripts.rendering import render_message_pretty

PLANNING_ALLOWED_TOOLS = [
    "Read",
    "Edit",
    "Grep",
    "Glob",
    "Agent",
    "ListAgents",
    "SendMessage",
    "Write",
    "Bash",
]

COPY_ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Write", "Bash"]


def update_plan_file_path(current: Path | None, message: Message) -> Path | None:
    """Fold over a message stream to track the plan file Claude wrote to.

    Plan mode lets Claude write exactly one file (the plan itself), at a path
    chosen by the harness rather than by us, so this scans for the `Write`
    tool-use that reveals where it landed.
    """
    if not isinstance(message, AssistantMessage):
        return current
    for block in message.content:
        if (
            isinstance(block, ToolUseBlock)
            and block.name == "Write"
            and "file_path" in block.input
        ):
            current = Path(block.input["file_path"])
    return current


def _print_message(message: Message, *, pretty: bool) -> None:
    if pretty:
        render_message_pretty(message)
    else:
        print(repr(message))


def _print_stderr(line: str) -> None:
    print(line, file=sys.stderr)


async def run_planning_query(
    prompt: str, *, pretty: bool, env: dict[str, str] | None = None
) -> Path:
    plan_file_path: Path | None = None
    options = ClaudeAgentOptions(
        allowed_tools=PLANNING_ALLOWED_TOOLS,
        tools=PLANNING_ALLOWED_TOOLS,
        disallowed_tools=["mcp*"],
        permission_mode="plan",
        model="claude-sonnet-5",
        max_budget_usd=2,
        env=env or {},
        stderr=_print_stderr,
    )
    async for message in query(prompt=prompt, options=options):
        _print_message(message, pretty=pretty)
        plan_file_path = update_plan_file_path(plan_file_path, message)

    if plan_file_path is None:
        msg = "Planning turn finished without writing a plan file"
        raise RuntimeError(msg)
    return plan_file_path


async def run_filename_query(
    plan_file_path: Path,
    cwd: Path,
    *,
    pretty: bool,
    env: dict[str, str] | None = None,
) -> None:
    """Have Claude pick a destination under docs/plans/ and copy the plan there.

    No response is parsed from this query: its job is fully accomplished by
    the side effect of the copy.
    """
    prompt = f"""
    Read the plan file at {plan_file_path} to see its content.

    Look at the existing files under docs/plans/ (relative to the current
    working directory) to match naming conventions. If docs/plans/ doesn't
    exist yet, pick a reasonable convention, e.g. a short kebab-case slug of
    the plan's title.

    Create any needed parent directories, then copy (not move -- leave the
    original file at {plan_file_path} alone) the plan file to your chosen
    destination somewhere under docs/plans/.
    """
    options = ClaudeAgentOptions(
        allowed_tools=COPY_ALLOWED_TOOLS,
        tools=COPY_ALLOWED_TOOLS,
        disallowed_tools=["mcp*"],
        permission_mode="bypassPermissions",
        add_dirs=[str(plan_file_path.parent)],
        cwd=str(cwd),
        model="claude-haiku-4-5-20251001",
        max_budget_usd=1,
        env=env or {},
        stderr=_print_stderr,
    )
    async for message in query(prompt=prompt, options=options):
        _print_message(message, pretty=pretty)


async def amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="claude-plan")
    parser.add_argument("prompt")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--dangerous",
        action="store_true",
        help=(
            "Required acknowledgment: the filename-decision step runs with "
            "Bash and Write access and no approval prompts. Only run this "
            "inside a sandbox, never bare on a host."
        ),
    )
    args = parser.parse_args(argv)

    if not args.dangerous:
        print(
            "claude-plan's filename-decision step runs an unattended query with "
            "Bash and Write access, auto-approved with no prompts. Pass "
            "--dangerous to acknowledge this and continue -- and only do so "
            "inside a sandbox, never bare on a host.",
            file=sys.stderr,
        )
        return 1

    plan_file_path = await run_planning_query(args.prompt, pretty=args.pretty)
    await run_filename_query(plan_file_path, Path.cwd(), pretty=args.pretty)
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))
