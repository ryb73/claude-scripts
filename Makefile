check:
	uv run pyrefly check
	uv run ruff check
	uv run pyright

watch:
	watchexec -e py -- make check

.PHONY: check watch
