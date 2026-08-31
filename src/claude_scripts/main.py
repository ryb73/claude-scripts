import asyncio
from collections.abc import Iterable
from typing import assert_never

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ContentBlock,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)


def render_fields(fields: Iterable[object]):
    return "/".join(str(f) for f in fields if f is not None and f != "")


def compact_value(value: object):
    if value is None or isinstance(value, (int, float, bool, range, complex)):
        return None
    if isinstance(value, str):
        max_len = 50
        if len(value) < max_len:
            return value
        return value[:max_len] + f"...({len(value)})"
    if isinstance(value, list):
        return [compact_value(v) for v in value]
    if isinstance(value, dict):
        return {k: compact_value(v) for k, v in value.items()}
    return f"[nocompact] {value!r}"


def render_content_block(b: ContentBlock):
    match b:
        case TextBlock(text):
            return text
        case ThinkingBlock(thinking):
            if thinking != "":
                return f"Thinking... {thinking} 💭"
            return "Thinking..."
        case ToolUseBlock(id=id, name=name, input=input):
            return "ToolUse: " + render_fields([name, id, compact_value(input)])
        case ToolResultBlock(
            tool_use_id=tool_use_id, content=content, is_error=is_error
        ):
            return "ToolResult: " + render_fields(
                [tool_use_id, is_error, compact_value(content)]
            )
        case ServerToolUseBlock():
            return str(b)
        case ServerToolResultBlock():
            return str(b)
    assert_never(b)


async def main():
    # Agentic loop: streams messages as Claude works
    async for message in query(
        prompt="""
        Can you put together a plan for fleshing out the implementation of main.py such
        that it neatly prints each message?
        """,
        options=ClaudeAgentOptions(
            allowed_tools=[
                "Read",
                "Edit",
                "Grep",
                "Glob",
                "Agent",
                "ListAgents",
                "SendMessage",
            ],
            tools=[
                "Read",
                "Edit",
                "Grep",
                "Glob",
                "Agent",
                "ListAgents",
                "SendMessage",
            ],
            disallowed_tools=["mcp*"],
            permission_mode="plan",
            model="claude-sonnet-5",
            max_budget_usd=2,
        ),
    ):
        # Print human-readable output
        match message:
            case ResultMessage(
                subtype=subtype,
                is_error=is_error,
                stop_reason=stop_reason,
                result=result,
                structured_output=structured_output,
                errors=errors,
                api_error_status=api_error_status,
                terminal_reason=terminal_reason,
            ):
                fields = [
                    subtype,
                    is_error,
                    stop_reason,
                    result,
                    structured_output,
                    errors,
                    api_error_status,
                    terminal_reason,
                ]
                print("Result: " + render_fields(fields))
                print()

            case AssistantMessage(
                content=content,
                parent_tool_use_id=parent_tool_use_id,
                error=error,
                stop_reason=stop_reason,
            ):
                for b in content:
                    print("Assistant: " + render_content_block(b))
                print(render_fields([parent_tool_use_id, error, stop_reason]))
                print()

            case UserMessage(
                content=content,
                parent_tool_use_id=parent_tool_use_id,
                tool_use_result=tool_use_result,
                origin=origin,
            ):
                if isinstance(content, str):
                    print("UserMessage: " + content)
                else:
                    for b in content:
                        print("UserMessage: " + render_content_block(b))
                print(
                    render_fields(
                        [parent_tool_use_id, origin, compact_value(tool_use_result)]
                    )
                )
                print()

            case _:
                print(str(message))
                print()

        # if isinstance(message, AssistantMessage):
        #     for block in message.content:
        #         if hasattr(block, "text"):
        #             print(block.text)  # Claude's reasoning  # noqa: ERA001
        #         elif hasattr(block, "name"):  # noqa: ERA001
        #             print(f"Tool: {block.name}")  # Tool being called  # noqa: ERA001
        # elif isinstance(message, ResultMessage):  # noqa: ERA001
        #     print(f"Done: {message.subtype}")  # Final result  # noqa: ERA001


asyncio.run(main())
