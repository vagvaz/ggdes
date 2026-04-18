## Before Requesting Review / Completion
1. Ensure code is formatted: `make format` (or `uv run ruff format .`).
2. Run lint + type checks: `make check` (includes lint & mypy) or individually `make check-format` and `make check-type`.
3. Execute test suite: `make test` (or `uv run pytest tests/ -v`), plus `make test-cov` when coverage needed.
4. For CLI/UI changes, run smoke command if applicable (e.g., `uv run ggdes analyze ...` or `make run`).
5. Clean up generated artifacts if necessary using `make clean`.
6. Update documentation or configuration samples (`README.md`, `ggdes.yaml`, docs/) when behavior changes.
