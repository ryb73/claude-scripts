# `claude-plan` script

## Context

`src/claude_scripts/main.py` is a scratch file where the Claude Agent SDK's `query()`
API and message types (`AssistantMessage`, `ResultMessage`, `ToolUseBlock`, etc.) were
explored. This project's first "real" script, `claude-plan`, builds on that by wrapping
Claude Code's plan-mode workflow into a CLI: run a planning turn, relocate the resulting
plan file into `docs/plans/` with a sensible name, and stream every message from both
queries to stdout (mirroring `main.py`'s existing `repr` / `--pretty` output modes).

The tricky part: when `permission_mode="plan"` is used, the underlying `claude` CLI
subprocess pre-selects a plan file path under `~/.claude/plans/<slug>.md` (via a system
reminder invisible to the SDK caller) and only allows Claude to `Write` to that one file
— it cannot be told up front to write anywhere else. So the script has to run the
planning query, discover the path Claude wrote to by scanning the `Write` `ToolUseBlock`
in the returned messages, then run a second query that decides the right destination
under `docs/plans/` and copies the plan file there itself (the original stays behind
under `~/.claude/plans/`).

## CLI shape

```
claude-plan "<prompt>" [--pretty]
```

- `prompt`: positional, the planning prompt (same role as the hardcoded prompt in `main.py`).
- `--pretty`: optional, same meaning as in `main.py` — pretty-print each message
  (via the `match`-based renderer) instead of the default `repr(message)` one-per-line.

Every message from *both* the planning query and the filename-decision query is written
to stdout, in the order received (planning query first), as they stream in.

New module: `src/claude_scripts/plan.py`, with a sync `main()` entry point that wraps
`asyncio.run(...)`, matching the existing `main.py` pattern. Register it in
`pyproject.toml`:

```toml
[project.scripts]
claude-scripts = "claude_scripts:main"
claude-plan = "claude_scripts.plan:main"
```

`main.py`'s rendering helpers (`render_fields`, `compact_value`, `render_content_block`,
and the per-message `match` block used under `--pretty`) are reused rather than
duplicated. Since `main.py` unconditionally calls `asyncio.run(main())` at module scope
(unsafe to import), extract those helpers into a new `src/claude_scripts/rendering.py`
module with no side effects, and have both `main.py` and `plan.py` import from it.

## Step 1 — planning query

Mirror the tool/permission setup already in `main.py`'s `main()`:

```python
options = ClaudeAgentOptions(
    allowed_tools=[
        "Read", "Edit", "Grep", "Glob", "Agent", "ListAgents", "SendMessage",
        "Write", "Bash",
    ],
    tools=[
        "Read", "Edit", "Grep", "Glob", "Agent", "ListAgents", "SendMessage",
        "Write", "Bash",
    ],
    disallowed_tools=["mcp*"],
    permission_mode="plan",
    model="claude-sonnet-5",
    max_budget_usd=2,
)
```

**Find the plan file path** without collecting messages into a list: keep a single
`plan_file_path: Path | None` accumulator, and update it in place while iterating
`async for message in query(prompt=user_prompt, options=options)`. For each
`AssistantMessage`, scan `.content` for a `ToolUseBlock` where `name == "Write"` and
`"file_path" in input`, and overwrite the accumulator on a match (last one wins, in case
Claude retries the write). Print the message to stdout in the same loop iteration (step 3).
If the accumulator is still `None` after the loop ends, exit with an error — the planning
turn didn't produce a plan file.

## Step 2 — decide destination and copy the file (agent-driven)

Run a second, separate `query()` call whose job is to pick a relative path under
`docs/plans/` and perform the copy itself:

```python
options = ClaudeAgentOptions(
    allowed_tools=["Read", "Glob", "Grep", "Write", "Bash"],
    tools=["Read", "Glob", "Grep", "Write", "Bash"],
    disallowed_tools=["mcp*"],
    permission_mode="bypassPermissions",
    add_dirs=[str(plan_file_path.parent)],
    model="claude-haiku-4-5-20251001",
    max_budget_usd=1,
)
```

`add_dirs` is required: `plan_file_path` lives under `~/.claude/plans/`, outside the
subprocess's `cwd` (the target repo), so without it Claude has no filesystem permission
to `Read` or `cp` the plan file at all. `permission_mode="bypassPermissions"` is needed
because, unlike step 1's read-only tools, this query actually writes files via `Bash`/`Write`
and there's no interactive user around in a headless script to approve them.

Prompt: tell it the plan file's absolute path (from step 1) and instruct it to:
- `Read` that file itself to see the plan's content (rather than us reading it and
  pasting it into the prompt),
- look at existing files under `docs/plans/` (relative to cwd) via `Glob`/`Read` to match
  naming conventions (if the directory doesn't exist yet, pick a reasonable convention,
  e.g. a short kebab-case slug of the plan title),
- confine the destination to somewhere under `docs/plans/`,
- create any needed parent directories and **copy** (not move — the original under
  `~/.claude/plans/` should be left alone) the plan file to that destination itself,
  e.g. via `Bash("mkdir -p docs/plans/... && cp <source> <dest>")`.

We don't need or use a response from this agent — its job is fully accomplished by the
side effect of the copy, so there's no final answer to parse or validate. The script
just iterates the query to print each message to stdout (step 3) and lets it run to
completion; `docs/plans/` staying confined is a matter of the prompt instructions above
plus `add_dirs` scoping what the agent can actually touch, not code-side validation.

## Step 3 — stdout output

Print each message to stdout as it's received from both queries (planning query first,
then the filename-decision query), using the same two modes `main.py` already has:
- default: `print(repr(message))`.
- `--pretty`: the existing `match`-based rendering (now living in `rendering.py`) that
  formats `ResultMessage` / `AssistantMessage` / `UserMessage` / fallback cases using
  `render_fields`, `compact_value`, and `render_content_block`.

This happens inline in the same `async for message in query(...)` loops used by steps 1
and 2 — no message lists are buffered anywhere.

## Sandboxing with Podman

Step 2 runs with `permission_mode="bypassPermissions"` and `Bash`/`Write` access, so a
misbehaving or misdirected agent turn could run arbitrary shell commands with no
approval gate. Don't run `claude-plan` bare on the host — run it inside a rootless
Podman container so the blast radius of anything it does is confined to that container
and its narrow, purpose-specific mounts.

- `Containerfile` at the repo root: based on a Python 3.12 image, installs Node.js (the
  `claude` CLI that `claude_agent_sdk` shells out to is distributed as an npm package,
  `@anthropic-ai/claude-code`) and `uv`, then `uv sync`'s this project's dependencies.
- A wrapper script, `bin/claude-plan-sandboxed`, (re)builds the image and then runs it:
  ```sh
  #!/usr/bin/env bash
  set -euo pipefail

  mkdir -p docs/plans
  config_dir=$(mktemp -d)
  trap 'rm -rf "$config_dir"' EXIT

  podman build -t claude-scripts-plan "$(dirname "$0")/.."

  podman run --rm \
    -v "$(pwd)":/workspace:ro,Z \
    -v "$(pwd)/docs/plans":/workspace/docs/plans:Z \
    -v "$config_dir":/root/.claude:Z \
    -w /workspace \
    -e ANTHROPIC_API_KEY \
    claude-scripts-plan \
    claude-plan "$@"
  ```
  - The target repo is mounted **read-only** at `/workspace` — the container can inspect
    the codebase and existing `docs/plans/` naming conventions but can't modify source
    files, git history, or anything else in the repo.
  - A single, more specific mount layered on top makes just `docs/plans/` read-write —
    the *only* writable spot in the whole repo, and exactly where step 2's `cp` needs to
    land its output. `plan.py` itself needs no changes: it still just writes relative to
    `cwd`, which happens to have this one writable subtree.
  - The container gets its **own** `~/.claude`: a fresh host temp directory (`mktemp -d`),
    unrelated to and never touching the real `$HOME/.claude` on the host. This is where
    step 1's plan-mode `Write` lands (container-local, wiped via the `trap` after the run
    finishes) — the host's actual Claude Code config, credentials, and plan history for
    other projects are never exposed to the container at all.
  - Since the container's `~/.claude` starts empty, auth can't come from a cached
    credentials file — pass `ANTHROPIC_API_KEY` from the host shell's environment
    (`-e ANTHROPIC_API_KEY` forwards the value without writing it into the image or any
    mounted file).
  - No other host paths are mounted, so even an unexpected `Bash` command in step 2 can't
    reach anything outside `/workspace` (read-only), `docs/plans/` (read-write), or the
    container's own filesystem.
- Rootless Podman is assumed (no `--privileged`, no extra capabilities), so container
  escape would additionally require a host root exploit, not just a container root shell.

This wrapper — not a bare `uv run claude-plan` / installed `claude-plan` — is the
supported way to invoke the script; the Verification section below uses it.

## Module structure (for testability)

To make steps 1 and 2 testable without needing fabricated `ClaudeAgentOptions` wiring
in every test, split `plan.py` into pure single-message-at-a-time reducers plus thin
async orchestration:

- `update_plan_file_path(current: Path | None, message: Message) -> Path | None` — pure;
  given the accumulator so far and one new message, returns the updated accumulator per
  step 1's `Write`-tool-use scan (or `current` unchanged if the message doesn't match).
- `async def run_planning_query(prompt: str, *, pretty: bool, env: dict[str, str] | None = None) -> Path`
  — iterates the query, prints each message via `rendering.py` (per step 3), folds
  `update_plan_file_path` over the stream, and returns the final path (raising if `None`).
- `async def run_filename_query(plan_file_path: Path, cwd: Path, *, pretty: bool, env: dict[str, str] | None = None) -> None`
  — sets `add_dirs=[str(plan_file_path.parent)]` and `permission_mode="bypassPermissions"`
  on its `ClaudeAgentOptions` so the agent can read the plan file and copy it itself;
  iterates the query purely to print each message (step 3) and let it run to completion.
  No return value — nothing downstream needs the agent's answer.
- `async def amain(argv: list[str]) -> int` — orchestrates steps 1-3 using the above.
- `def main() -> None` — `sys.exit(asyncio.run(amain(sys.argv[1:])))`, the registered entry point.

Both `run_planning_query` and `run_filename_query` accept an `env` override that's
merged into `ClaudeAgentOptions.env`, so tests can isolate the subprocess's config
directory without touching the real process environment or `~/.claude`.

## Tests (`tests/test_plan.py`)

Add `pytest` to the `dev` dependency group in `pyproject.toml`, and a `test` target to
the `Makefile` (`uv run pytest`), wired into `check` alongside the existing
pyrefly/ruff/pyright steps.

**Unit tests (fast, no network, run in `check`)** — construct `AssistantMessage` /
`ToolUseBlock` objects by hand (no real queries) and fold them through the reducer one
at a time (as `amain` would) to assert against the pure function:
- `update_plan_file_path`: a `Write` tool-use with `file_path` updates the accumulator;
  a later match overwrites an earlier one; non-matching messages leave `current` unchanged.

**Integration tests (real API calls, opt-in only)** — marked with a custom
`@pytest.mark.integration` marker (registered in `pyproject.toml`, deselected by default
via `addopts = "-m 'not integration'"` so `make check` never spends money/network by
accident). These call `run_planning_query` / `run_filename_query` for real, with:
- `env={"CLAUDE_CONFIG_DIR": str(tmp_path)}` (pytest's built-in `tmp_path` fixture) so
  the subprocess's settings, auth cache, and `plans/` directory are fully isolated from
  the developer's real `~/.claude`,
- a small `max_budget_usd`,
and assert:
- `run_planning_query(...)` on a trivial prompt returns a path that actually exists on
  disk under the isolated `CLAUDE_CONFIG_DIR`,
- after `run_filename_query(...)` completes for that path against a scratch `cwd` (a
  `tmp_path`-based repo dir, not the real `claude-scripts` checkout), a `.md` file has
  appeared somewhere under that `cwd`'s `docs/plans/` (checked via `Path.glob`, since the
  exact name is the agent's choice and not returned to the caller) whose content matches
  the original plan file.

Run these explicitly with `uv run pytest -m integration` when actually verifying
end-to-end behavior against the API.

## Verification

- Run `uv run pytest` (unit tests only) and confirm `update_plan_file_path` passes
  without hitting the network.
- Run `uv run pytest -m integration` and confirm the isolated `CLAUDE_CONFIG_DIR` tests
  pass.
- Run `bin/claude-plan-sandboxed "add a --dry-run flag to claude-plan itself"` from
  within `claude-scripts` and confirm:
  - a new file appears under `docs/plans/` with reasonable content and name,
  - `repr(message)` lines for both queries print to stdout as they stream in.
- Run again with `--pretty` and confirm the output switches to the `main.py`-style
  human-readable rendering instead of `repr(...)` lines.
- Run `make check` (`pyrefly`, `ruff`, `pyright`, unit tests) to confirm the new modules
  and tests are clean.
