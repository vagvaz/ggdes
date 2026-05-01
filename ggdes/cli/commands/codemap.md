# ggdes/cli/commands/

## Responsibility

All GGDes CLI command implementations. Each file registers one or more commands
with the shared Typer `app` via `@app.command()` and contains the command's
argument/option handling and orchestration logic.

## Design

### File Layout

| File | Command(s) | Description |
|---|---|---|
| `analyze.py` | `analyze` | Start a new analysis of git commits |
| `compare.py` | `compare` | Compare two analyses side-by-side |
| `config_cmd.py` | `config` | View current configuration |
| `doctor.py` | `doctor` | System health diagnostics |
| `export_cmd.py` | `export`, `archive` | Export analysis data; archive (export + delete) |
| `manage.py` | `cleanup`, `conversations` | Clean up worktrees; view LLM conversations |
| `resume.py` | `resume` | Resume an incomplete/paused analysis |
| `server.py` | `tui`, `debug`, `web` | Launch TUI, debug TUI, or web interface |
| `status.py` | `status`, `list` | Show status of analyses (detail or summary table) |

### Command Details

#### `analyze` (`analyze.py`)

- **Options:**
  - `--feature` (required) — Name for this analysis
  - `--commits` (required) — Git commit range (e.g., `"HEAD~5..HEAD"`)
  - `--repo` — Path to repository (defaults to CWD or config)
  - `--provider`, `--model`, `--api-key` — Override model config
  - `--formats` — Comma-separated: `markdown`, `docx`, `pdf`, `pptx`
  - `--focus` — Focus on specific commit hashes
  - `--storage` — Conversation storage policy: `raw`, `summary`, `none`
  - `--force` — Force run even if another analysis is locked
  - `--auto` — Non-interactive mode (skip prompts, no user context questionnaire)
  - `--setup-only` — Only create worktrees, skip analysis
  - `--semantic-diff` (default: True) — Enable AST-based semantic analysis
  - `--no-filter` — Disable semantic change filtering
  - `--render-png` — Render markdown to PNG (requires playwright)
  - `--interactive` — Interactive review after each pipeline stage
  - `--context-file` — YAML/JSON file with user context (skips questionnaire)
- **Pipeline stages triggered:** All stages via `run_analysis_pipeline()`
  (worktree setup, AST parsing base+head, semantic diff, change filter, technical
  author, coordinator plan, output generation).
- **Lock:** Uses `LockContext(repo_path, analysis_id, force=force)`.

#### `compare` (`compare.py`)

- **Arguments:** `analysis1`, `analysis2` (ID or name)
- **Options:** `--output` — Export comparison to JSON file
- **Pipeline stages triggered:** None (reads existing KB data).
- **Uses:** `AnalysisComparator.compare()` → `print_comparison()` / `export_comparison()`.

#### `config` (`config_cmd.py`)

- **Options:** `--show` (default: True) — Print model provider, model name, API key status,
  KB path, worktrees path, default format, semantic diff toggle, auto cleanup toggle.
- **Pipeline stages triggered:** None.

#### `doctor` (`doctor.py`)

- **Options:** `--fix` — Attempt automatic fixes for issues found
- **Output sections** (printed with bold headers in order):
  1. **Python Environment** — Python version; core package imports (`typer`, `rich`, `pydantic`, `pyyaml`, `tree_sitter`, `loguru`)
  2. **Diagram Generation** — PlantUML jar presence; Java runtime (required); Graphviz `dot` with additional layout engines (`neato`, `twopi`, `circo`) checked via `_check_dot_features()`; notes which PlantUML diagram types require Graphviz
  3. **Document Generation** — Node.js runtime; npm packages (`pptxgenjs`, `docx`) via `require.resolve()` using `_check_npm_package()`; Pandoc fallback
  4. **PDF & Image Processing** — LibreOffice (`soffice`); Poppler (`pdftoppm`, `pdfimages`); Tesseract OCR
  5. **Knowledge Base & Git** — Git availability (required); knowledge base directory existence (with analysis count)
- **Helper functions:**
  - `_check_exec(name, description, required=False)` — Checks if an executable is on `PATH` via `shutil.which()`. Prints green checkmark (`✓`) on success, red cross (`✗`) for missing required executables, yellow warning (`⚠`) for missing optional ones. Returns `bool`.
  - `_check_npm_package(name)` — Checks if a global npm package is available by spawning `node -e "require.resolve('...')"` and inspecting the exit code. Prints green checkmark with resolved path, or yellow warning. Returns `bool`. Gracefully handles `FileNotFoundError` (Node.js not installed) and timeouts.
  - `_check_dot_features()` — When `dot` is found, probes `dot -?` and checks `PATH` for additional Graphviz layout engines (`neato`, `twopi`, `circo`). Prints discovered layouts and documents which PlantUML diagram types require `dot` (activity, component, deployment, usecase). Silently handles missing `dot` or timeouts.
- **Auto-fixes** (`--fix` flag):
  - PlantUML jar missing → downloads `plantuml-1.2024.7.jar` from GitHub to `ggdes/diagrams/plantuml.jar`
  - Knowledge base directory missing → creates it (including parents)
  - Other issues (missing executables, npm packages) are reported but not auto-fixed
- **Counting:** Tracks `issues` (red, typically missing required items), `warnings` (yellow, missing optional items), and `fixes` (green, auto-resolved). Prints a summary line at the end. When issues exist and `--fix` was not used, suggests `ggdes doctor --fix`.
- **Pipeline stages triggered:** None.

#### `export` (`export_cmd.py`)

- **Arguments:** `analysis` (ID or name), `output` (path, `.json` or `.zip`)
- **Options:** `--include-diagrams` (default: True), `--include-worktrees`
- **Pipeline stages triggered:** None.
- **Exports:** metadata, git_analysis summary, technical facts, document plans,
  full analysis directory (ZIP) or structured JSON.

#### `archive` (`export_cmd.py`)

- **Arguments:** `analysis` (ID or name)
- **Options:** `--export-first` (default: True), `--keep-days` (default: 30)
- **Pipeline stages triggered:** None.
- **Action:** Exports analysis, deletes from KB, cleans up worktrees.
- **Safety:** Warns if analysis is newer than `keep_days`.

#### `cleanup` (`manage.py`)

- **Arguments:** `analysis` (ID or name)
- **Options:** `--remove-kb` — Also delete from knowledge base (with confirmation)
- **Pipeline stages triggered:** None.
- **Action:** Removes worktrees and optionally KB entry.

#### `conversations` (`manage.py`)

- **Arguments:** `analysis` (ID or name)
- **Options:** `--agent` — Filter by agent name; `--raw` — Show full messages
- **Pipeline stages triggered:** None.
- **Displays:** Per-agent conversation metadata (token counts, message count, summaries).

#### `resume` (`resume.py`)

- **Arguments:** `analysis` (ID or name)
- **Options:**
  - `--force` — Force resume even if locked
  - `--stage` — Run a specific stage only
  - `--retry-failed` — Reset failed stages to pending and retry
  - `--formats` — Override output formats (resets coordinator_plan + output_generation)
  - `--overwrite-context` — Re-ask user questions for new context
  - `--interactive` — Interactive review mode
  - `--context-file` — Load context from file
- **Pipeline stages triggered:** Pending stages only (via `pipeline.run_all_pending()`)
  or a specific stage via `pipeline.run_stage(stage)`.
- **Key behavior:** Updates `target_formats` and `user_context` in metadata if
  `--formats` or `--overwrite-context` is used; resets dependent stages.

#### `tui` (`server.py`)

- **No options.** Launches the Textual-based TUI via `run_tui()` from `ggdes.tui`.

#### `debug` (`server.py`)

- **Argument:** `analysis` (optional, ID or name — shows selector if omitted)
- **Launches:** A Textual-based debug TUI (`DebugTUI`) with the `DebugView` widget
  for browsing agent conversations, outputs, and file trees.

#### `web` (`server.py`)

- **Options:** `--host` (default: `127.0.0.1`), `--port` (default: `8000`), `--reload`
- **Launches:** uvicorn running `ggdes.web:app` (FastAPI application).
- **Requires:** `fastapi`, `uvicorn`, `websockets` (web extra).

#### `status` / `list` (`status.py`)

- **Argument:** `analysis` (optional, ID or name)
- **Without argument:** Prints a Rich table of all analyses with columns:
  ID, Name, Repository, Formats, Status, Completed, Pending.
- **With argument:** Prints detailed stage-by-stage status for a single analysis,
  including generated documents.
- **`list`** is an alias that delegates to `status()`.

## Flow

```
CLI invocation → Typer dispatches to registered command
                    ↓
              Command function validates inputs (parse_and_validate_* / resolve_analysis / etc.)
                    ↓
              Loads config (load_config → GGDesConfig + repo_path)
                    ↓
              Creates KB manager, pipeline, or other services
                    ↓
              Executes pipeline stages or reads KB data
                    ↓
              Prints results / generates output
```

## Integration

- All commands import `app` and `console` from `ggdes.cli`.
- Commands consume CLI utilities from `ggdes.cli.utils` (resolve_analysis,
  validate_commit_range, parse_and_validate_formats, etc.).
- Commands create `KnowledgeBaseManager` from `ggdes.kb` to read/write analysis data.
- Commands create `AnalysisPipeline` from `ggdes.pipeline` to run stages.
- `analyze` and `resume` use `LockContext` from `ggdes.utils.lock`.
- `server.py` commands import from `ggdes.tui`, `ggdes.tui.debug_view`, and `ggdes.web`.
- `compare.py` imports `AnalysisComparator` from `ggdes.comparison`.
- `doctor.py` imports `PlantUMLGenerator` from `ggdes.diagrams` and `load_config` from `ggdes.config`.
- `manage.py` imports `WorktreeManager` from `ggdes.worktree`.
