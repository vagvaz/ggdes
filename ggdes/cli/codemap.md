# ggdes/cli/

## Responsibility

Entry point for the GGDes command-line interface. Defines the Typer application,
the `main()` entry point, and the `--version` callback. CLI commands are registered
by importing the command modules in `ggdes/cli/commands/` (wildcard imports trigger
the `@app.command()` decorators). Shared CLI utilities live in `utils.py`.

## Design

### Typer App (`ggdes/cli/__init__.py`)

- **`app = typer.Typer(...)`** — the root Typer application. All commands are
  registered via `@app.command()` in the individual command modules.
- **`console = Console()`** — a Rich console shared across all CLI commands.
- **`version_callback`** — a `@app.callback(invoke_without_command=True)` that
  handles `--version` by printing the package version from installed metadata.
- **`main()`** — the `[project.scripts]` entry point; simply calls `app()`.
  Resolved via pyproject.toml as `ggdes.cli:main`.

### Command Registration Pattern

Command modules use wildcard imports (`from ggdes.cli.commands.analyze import *`)
which trigger `@app.command()` decoration at import time. Each module defines one
or more functions decorated with `@app.command()`. The `name=` parameter can be
used to alias commands (e.g., `@app.command(name="list")` for the `list` command).

### Shared CLI Utilities (`ggdes/cli/utils.py`)

| Function | Purpose |
|---|---|
| `_get_version()` | Returns installed ggdes package version via `importlib.metadata` |
| `_load_user_context_from_file()` | Loads YAML/JSON context files for analysis configuration |
| `resolve_analysis()` | Resolves an analysis ID or name to `(id, metadata)` tuple by scanning the KB |
| `_gather_user_context()` | Interactive questionnaire via Rich Prompt to gather focus areas, audience, purpose, detail level |
| `generate_analysis_id()` | Creates a unique ID: `{name}-{timestamp}-{md5_hash[:8]}` |
| `validate_commit_range()` | Validates git commit range format `base..head`, verifies commits exist, counts commits |
| `parse_and_validate_formats()` | Parses comma-separated format string into validated list (`markdown`, `docx`, `pdf`, `pptx`) |
| `parse_and_validate_storage()` | Validates storage policy against `StoragePolicy` enum values |
| `create_analysis_metadata()` | Creates analysis entry in the knowledge base with all metadata fields |
| `run_analysis_pipeline()` | Orchestrates the full analysis pipeline: worktree setup, user context gathering (interactive or file-based), stage configuration (semantic diff on/off, change filter on/off), and `pipeline.run_all_pending()` |

## Flow

```
main() → app() → version_callback (if --version) / command dispatch
                    ↓
              Command module (e.g., analyze, resume, status)
                    ↓
              utils helpers (resolve_analysis, validate_commit_range, etc.)
                    ↓
              Pipeline execution via run_analysis_pipeline()
                    ↓
              KnowledgeBaseManager for persistence
```

## Integration

- **Commands** are imported by `ggdes/cli/__init__.py` via wildcard imports.
- **Utils** are consumed by individual command modules in `ggdes/cli/commands/`.
- **`resolve_analysis`** delegates to `KnowledgeBaseManager.list_analyses()`.
- **`run_analysis_pipeline`** creates an `AnalysisPipeline` from `ggdes.pipeline`
  and runs stages defined in `ggdes.stages` (worktree setup, AST parsing, semantic
  diff, change filtering, technical author, coordinator, output generation).
- **`LockContext`** from `ggdes/utils/lock.py` is used by the `analyze` command
  to prevent concurrent runs.
- **`load_config`** from `ggdes.config` is called by every command to resolve
  repository path, model provider, and API keys.
