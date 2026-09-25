from collections.abc import Iterable
from typing import assert_never

from claude_agent_sdk import (
    AssistantMessage,
    ContentBlock,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
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


def render_message_pretty(message: object) -> None:
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
