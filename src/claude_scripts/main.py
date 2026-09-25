import argparse
import asyncio

from claude_agent_sdk import ClaudeAgentOptions, query

from claude_scripts.rendering import render_message_pretty


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

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
        if not args.pretty:
            print(repr(message))
            continue

        render_message_pretty(message)


asyncio.run(main())
