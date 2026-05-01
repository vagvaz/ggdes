# ggdes/stages/

## Responsibility

Provide the abstraction layer for pipeline stages — the base class, the result type, the registry, shared utilities, and canonical stage name constants. Every pipeline stage (whether extracted or legacy) conforms to the `Stage` interface defined here.

## Files

| File | Role |
|------|------|
| `base.py` | `Stage` ABC and `StageResult` dataclass |
| `__init__.py` | Stage name constants, `STAGE_REGISTRY`, `get_stage()`, `register_stage()` |
| `utils.py` | Shared utility functions consumed by pipeline and stages |
| `worktree_setup.py` | WorktreeSetupStage — first refactored stage using the new pattern |

## Design

### Stage ABC (`base.py:27`)

```python
class Stage(ABC):
    name: str = ""              # Subclasses override with a unique string

    @abstractmethod
    async def run(
        self,
        metadata: AnalysisMetadata,   # Mutable — stages can update it
        config: GGDesConfig,          # Global config
        kb: KnowledgeBaseManager,     # Read/write KB artifacts
        console: Console,             # Rich console for progress output
        feedback: str | None = None,  # Review feedback from prior runs
    ) -> StageResult:
        ...
```

Key design choices:
- **Explicit parameter passing** — no shared state, no `self.config` stored on the stage instance. All dependencies injected at call time.
- **Async interface** — `run()` is async, giving stages the option to use async IO. The pipeline calls it via `asyncio.run()`.
- **Mutable metadata** — stages can update `metadata.worktrees`, `metadata.stages`, etc. directly.
- **Optional feedback** — the `feedback` param carries review session feedback for stages that support regeneration.

### StageResult (`base.py:13`)

```python
@dataclass
class StageResult:
    success: bool = True        # Stage completed successfully
    error: str | None = None    # Error message if failed
    skipped: bool = False       # Stage had nothing to do (not a failure)
```

Three outcome states:
- `success=True, skipped=False` — normal completion
- `success=False, error=msg` — failure (pipeline halts)
- `success=True, skipped=True` — intentionally skipped (pipeline advances)

### Stage Name Constants (`__init__.py:13`)

Canonical source for all 9 pipeline stage names. Every consumer (`pipeline.py`, `kb/manager.py`, `review/`) imports from here to avoid string duplication:

| Constant | Value | Legacy Method |
|----------|-------|---------------|
| `STAGE_WORKTREE_SETUP` | `"worktree_setup"` | Extracted → `WorktreeSetupStage` |
| `STAGE_GIT_ANALYSIS` | `"git_analysis"` | `_run_git_analysis()` |
| `STAGE_CHANGE_FILTER` | `"change_filter"` | `_run_change_filter()` |
| `STAGE_AST_PARSING_BASE` | `"ast_parsing_base"` | `_run_ast_parsing("base")` |
| `STAGE_AST_PARSING_HEAD` | `"ast_parsing_head"` | `_run_ast_parsing("head")` |
| `STAGE_SEMANTIC_DIFF` | `"semantic_diff"` | `_run_semantic_diff()` |
| `STAGE_TECHNICAL_AUTHOR` | `"technical_author"` | `_run_technical_author()` |
| `STAGE_COORDINATOR_PLAN` | `"coordinator_plan"` | `_run_coordinator_plan()` |
| `STAGE_OUTPUT_GENERATION` | `"output_generation"` | `_run_output_generation()` |

`ALL_STAGES` (`__init__.py:23`) provides the canonical ordering.

### Stage Dependency Graph (`__init__.py:38`)

`STAGE_DEPENDENCIES` defines the prerequisite relationships between stages for automated scheduler resolution:

```python
STAGE_DEPENDENCIES = {
    "worktree_setup": [],
    "git_analysis": ["worktree_setup"],
    "change_filter": ["git_analysis"],
    "ast_parsing_base": ["worktree_setup"],
    "ast_parsing_head": ["worktree_setup"],
    "semantic_diff": ["git_analysis"],
    "technical_author": ["git_analysis", "ast_parsing_base", "ast_parsing_head", "semantic_diff"],
    "coordinator_plan": ["technical_author"],
    "output_generation": ["coordinator_plan"],
}
```

Key insight for parallelism: `git_analysis` and `ast_parsing_*` have no dependency on each other (both depend only on `worktree_setup`), so they can run concurrently.

### Topological Scheduler (`resolve_stage_order`, `__init__.py:70`)

Uses **Kahn's algorithm** to produce parallel-compatible execution layers:

```python
resolve_stage_order() -> list[list[str]]
# Returns layers like:
#   [["worktree_setup"],
#    ["git_analysis", "ast_parsing_base"],
#    ["semantic_diff", "ast_parsing_head"],
#    ["technical_author"],
#    ["coordinator_plan"],
#    ["output_generation"]]
```

- Computes in-degree (unresolved dependencies) per stage
- Tracks reverse dependencies for cascade notifications
- Each inner list is a layer of stages that can run in parallel
- Outer list is in strict dependency order
- Raises `ValueError` on circular dependencies

### Stage Registry (`__init__.py:55`)

```python
STAGE_REGISTRY: dict[str, type[Stage]] = {
    WorktreeSetupStage.name: WorktreeSetupStage,
}
```

- **Purpose**: Enables name-based stage dispatch so `pipeline.py` can run extracted stages without a big if/elif chain.
- **Lookup**: `get_stage(name)` returns `type[Stage] | None`
- **Registration**: `register_stage(stage_class)` adds to the dict. Extracted stages self-register at import time (currently just `WorktreeSetupStage`).
- **Migration**: As legacy methods are extracted into standalone stage classes, they are added to this registry and removed from the if/elif chain in `pipeline.py`.

### Shared Utilities (`utils.py`)

All follow a consistent pattern: they read from the knowledge base and return parsed data. Pipeline methods delegate to these.

| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `get_summary_path(kb, id)` | `(KBM, str) → Path` | Path to `change_filter/summary.json` or fallback to `git_analysis/summary.json` | Prefers filtered summary over raw |
| `get_changed_files_from_analysis(kb, id)` | `(KBM, str) → list[str]` | List of changed file paths | File paths only, for AST parsing scoping |
| `get_changed_files_detailed(kb, id)` | `(KBM, str) → list[dict]` | List of dicts with path, change_type, lines_added/deleted, summary, relevant_line_ranges | Rich detail for tool executor |
| `load_ast_elements(kb, id, variant)` | `(KBM, str, "head"|"base") → dict[str, list[Any]]` | Map of file_path → list of code element dicts | AST data for grounded LLM calls |
| `build_tool_executor(config, kb, id, repo_path, metadata)` | `(...) → ToolExecutor` | Grounded tool executor | Lazily imports `ToolExecutor`, wires changed files + AST + commit range |

### WorktreeSetupStage (`worktree_setup.py`)

The first stage extracted from the pipeline's if/elif chain into the new pattern. Demonstrates the convention:

1. **Class-level `name`** — `"worktree_setup"` must match its `STAGE_REGISTRY` key
2. **Async `run()`** — no `__init__` needed; the stage is instantiated as `stage_class()` in the pipeline
3. **Error handling** — returns `StageResult(success=False, error=msg)` on failure
4. **KB writes** — updates `metadata.worktrees` (a `WorktreeInfo` object with `base`/`head` paths)
5. **Console output** — uses the injected `console` for structured progress reporting

What it does:
- Parses `metadata.commit_range` (format: `"base..head"`)
- Creates worktrees via `WorktreeManager.create_for_analysis()`
- Verifies worktrees exist and have content
- Stores resolved absolute paths in `metadata.worktrees`

## Flow

```
Pipeline.run_stage("worktree_setup")
    │
    ├── get_stage("worktree_setup") → WorktreeSetupStage
    ├── stage = WorktreeSetupStage()
    ├── asyncio.run(stage.run(metadata, config, kb, console, feedback))
    │
    ▼
StageResult(success=True/False, skipped=True/False, error=msg)
    │
    ├── success + skipped  → mark_complete / mark_skipped → advance pipeline
    ├── success + !skipped → mark_complete → maybe_review() → advance/pause
    └── !success           → mark_failed → halt pipeline
```

## Integration

- **Pipeline**: `pipeline.py` imports `StageResult` (as `StageResultData`), `get_stage`, and all stage name constants. Methods delegate to utilities.
- **Knowledge base**: `kb/manager.py` imports stage constants from here (avoids circular imports, uses its own copy).
- **Review**: `review/` uses stage names to look up reviewable artifacts.
- **CLI**: `ggdes resume <id>` calls `run_stage()` for individual stages.
- **Adding a new stage**:
  1. Add a constant to `__init__.py` (e.g. `STAGE_MY_NEW = "my_new"`)
  2. Append to `ALL_STAGES`
  3. Create `my_new_stage.py` with `class MyNewStage(Stage): name = "my_new"`
  4. Register via `register_stage(MyNewStage)` or add to `STAGE_REGISTRY` directly
  5. Remove from `pipeline.py`'s if/elif chain
