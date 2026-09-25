check:
	uv run pyrefly check
	uv run ruff check
	uv run pyright
	uv run pytest

test:
	uv run pytest

watch:
	watchexec -e py -- make check

.PHONY: check test watch
