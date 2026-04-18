## Environment Setup
- `uv sync` — install core dependencies.
- `uv sync --extra dev` — install development extras (linting, typing, tests).
- `uv sync --extra web` — add web UI dependencies (FastAPI, uvicorn).

## Running the Application
- `uv run ggdes analyze --feature "<name>" --commits "<range>"` — run documentation analysis over a commit range.
- `uv run ggdes status` — list stored analyses and their stages.
- `uv run ggdes resume <analysis-id> [--stage <stage>]` — resume or rerun pipeline stages.
- `uv run ggdes cleanup <analysis-id> [--remove-kb]` — clean worktrees / knowledge base.
- `uv run ggdes web [--host 0.0.0.0 --port 8080]` — launch web UI.
- `uv run ggdes tui` — start terminal UI.
- `uv run ggdes compare <analysis-a> <analysis-b> [--output comparison.json]` — compare analyses.
- `uv run ggdes doctor [--fix]` — system health checks and automatic fixes.

## Make Targets & Tooling
- `make format` — Ruff formatter over repo.
- `make check-format` — Ruff format check and lint.
- `make check-type` — mypy strict type checking (`uv run mypy ggdes`).
- `make check` — run linting + typing checks.
- `make test` — execute pytest suite.
- `make test-cov` — pytest with coverage reports.
- `make run` — invoke CLI via `uv run python -m ggdes.cli`.
- `make web` / `make tui` — helpers for UI entrypoints.
- `make clean` — remove caches and build artifacts.

## Other Utilities
- `uv run ggdes analyze --feature X --commits "HEAD~5..HEAD" --auto` — fully automated analysis.
- `uv run ggdes web --reload` — development mode web server (when supported).
