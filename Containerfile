FROM python:3.14-slim

RUN apt-get update \
    && apt-get upgrade \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY README.md ./
RUN uv sync --locked

ENV PATH="/app/.venv/bin:${PATH}"

# A fixed, non-root user: `claude`'s `--dangerously-skip-permissions` (what
# permission_mode="bypassPermissions" sends the CLI) refuses to run as root.
RUN useradd -m -u 1000 -s /bin/bash sandbox
USER sandbox
