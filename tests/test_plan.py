from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

from claude_scripts.plan import (
    run_filename_query,
    run_planning_query,
    update_plan_file_path,
)


def _write_message(file_path: Path) -> AssistantMessage:
    return AssistantMessage(
        content=[
            ToolUseBlock(id="tool-1", name="Write", input={"file_path": str(file_path)})
        ],
        model="claude-sonnet-5",
    )


def test_update_plan_file_path_finds_write_tool_use(tmp_path: Path):
    target = tmp_path / "plans" / "foo.md"
    result = update_plan_file_path(None, _write_message(target))
    assert result == target


def test_update_plan_file_path_last_write_wins(tmp_path: Path):
    first_target = tmp_path / "plans" / "foo.md"
    second_target = tmp_path / "plans" / "bar.md"
    first = update_plan_file_path(None, _write_message(first_target))
    second = update_plan_file_path(first, _write_message(second_target))
    assert second == second_target


def test_update_plan_file_path_ignores_non_matching_messages(tmp_path: Path):
    text_message = AssistantMessage(
        content=[TextBlock(text="thinking...")], model="claude-sonnet-5"
    )
    other_tool_message = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tool-2", name="Read", input={"file_path": str(tmp_path / "x.md")}
            )
        ],
        model="claude-sonnet-5",
    )

    assert update_plan_file_path(None, text_message) is None
    current = tmp_path / "plans" / "foo.md"
    assert update_plan_file_path(current, text_message) == current
    assert update_plan_file_path(current, other_tool_message) == current


def test_update_plan_file_path_requires_file_path_key():
    message = AssistantMessage(
        content=[ToolUseBlock(id="tool-3", name="Write", input={})],
        model="claude-sonnet-5",
    )
    assert update_plan_file_path(None, message) is None


@pytest.mark.integration
async def test_run_planning_query_writes_a_plan_file(tmp_path: Path):
    config_dir = tmp_path / "claude-config"
    plan_file_path = await run_planning_query(
        "Write a one-sentence plan for a trivial change.",
        pretty=False,
        env={"CLAUDE_CONFIG_DIR": str(config_dir)},
    )

    assert plan_file_path.is_file()


@pytest.mark.integration
async def test_run_filename_query_copies_plan_into_docs_plans(tmp_path: Path):
    config_dir = tmp_path / "claude-config"
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    plan_file_path = await run_planning_query(
        "Write a one-sentence plan for a trivial change.",
        pretty=False,
        env={"CLAUDE_CONFIG_DIR": str(config_dir)},
    )

    await run_filename_query(
        plan_file_path,
        repo_dir,
        pretty=False,
        env={"CLAUDE_CONFIG_DIR": str(config_dir)},
    )

    copies = list(repo_dir.glob("docs/plans/**/*.md"))
    assert len(copies) == 1
    assert copies[0].read_text() == plan_file_path.read_text()
