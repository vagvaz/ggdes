# ggdes/

## Responsibility

The core Python package for GGDes (Get from Git Design Documentation). Orchestrates a multi-stage analysis pipeline that — given a git commit range — produces design documentation in Markdown, DOCX, PDF, and PPTX formats with embedded diagrams.

## Key Modules

| Module | Role |
|--------|------|
| `pipeline.py` | Central orchestrator — `AnalysisPipeline` class |
| `config/` | Pydantic-backed configuration hierarchy |
| `stages/` | Stage ABC, registry, constants, utilities |
| `agents/` | LLM-powered agents: GitAnalyzer, TechnicalAuthor, Coordinator, output agents |
| `kb/` | Knowledge base — persistent analysis artifacts on disk |
| `parsing/` | AST parsing of source files |
| `cli/` | Command-line interface (`ggdes analyze`, `ggdes resume`, etc.) |
| `web/` | Web UI (FastAPI + WebSocket) |
| `tui/` | Terminal UI (Textual) |
| `schemas/` | Pydantic schemas for LLM structured output |
| `semantic_diff.py` | Semantic change detection |
| `diagrams/` | PlantUML-based diagram generation |
| `review/` | Interactive review session management |
| `llm/` | LLM provider abstraction (Anthropic, OpenAI, Ollama, custom) |
| `tools/` | Grounded tool executor for LLM calls |
| `validation/` | Code reference and AST validation |
| `worktree/` | Git worktree creation and cleanup |
| `prompts/` | Prompt templates |
| `skills/` | Skill documentation for output agents |
| `rendering/` | Document rendering helpers |
| `utils/` | Shared utilities (lock, etc.) |
| `feedback.py` | User feedback tracking |
| `comparison.py` | Side-by-side analysis comparison |

---

## pipeline.py — AnalysisPipeline

### Responsibility

Orchestrate the multi-stage analysis pipeline: 9 stages run sequentially (with one parallel group), each stage consuming KB artifacts produced by the previous stage and writing its own outputs back. Supports interactive review, resume, and error recovery.

### Design

**Class: `AnalysisPipeline`** (`pipeline.py:40`)

```python
class AnalysisPipeline:
    def __init__(self, config: GGDesConfig, analysis_id: str, interactive: bool = False):
```

**State:**
- `config` — global configuration
- `analysis_id` — unique analysis identifier
- `interactive` — pause after each reviewable stage for user feedback
- `kb_manager` — `KnowledgeBaseManager` for reading/writing artifacts
- `metadata` — `AnalysisMetadata` loaded from KB (mutable throughout pipeline)
- `repo_path` — resolved `Path` to the repository
- `wt_manager` — `WorktreeManager` for worktree lifecycle
- `_metadata_lock` — threading lock for safe concurrent metadata access
- `_review_session` — optional `ReviewSession` for interactive feedback

### Stage Lifecycle

Each stage follows the same lifecycle, implemented in `run_stage()` (`pipeline.py:91`):

```
1. SKIP CHECK       — is_stage_completed(name)? → return True (already done)
2. START            — metadata.start_stage(name), save to KB
3. DISPATCH         — registry lookup → async run()  OR  legacy if/elif
4. OUTCOME HANDLING
   ├── skipped      → metadata.skip_stage(name) → return True (advance pipeline)
   ├── success      → metadata.complete_stage(name)
   │                    └── interactive? → _maybe_review(name)
   │                                           ├── continue → return True
   │                                           └── pause    → return False
   └── failure      → metadata.fail_stage(name, error) → return False (halt)
5. EXCEPTION        — catch-all → metadata.fail_stage(name, str(e)) → return False
```

### Dispatch Mechanism (Two Paths)

**Path 1 — Extracted stages via registry** (`pipeline.py:120-181`):
```python
stage_class = get_stage(stage_name)
if stage_class is not None:
    stage = stage_class()
    result = asyncio.run(stage.run(metadata, config, kb, console, feedback))
    # handle success / skipped / failure
```

Currently extracted: `STAGE_WORKTREE_SETUP` → `WorktreeSetupStage`

**Path 2 — Legacy if/elif dispatch** (`pipeline.py:183-207`):
```python
if stage_name == STAGE_GIT_ANALYSIS:
    success = self._run_git_analysis()
elif stage_name == STAGE_CHANGE_FILTER:
    success = self._run_change_filter()
elif stage_name == STAGE_AST_PARSING_BASE:
    success = self._run_ast_parsing("base")
elif stage_name == STAGE_AST_PARSING_HEAD:
    success = self._run_ast_parsing("head")
elif stage_name == STAGE_TECHNICAL_AUTHOR:
    success = self._run_technical_author()
elif stage_name == STAGE_COORDINATOR_PLAN:
    success = self._run_coordinator_plan()
elif stage_name == STAGE_OUTPUT_GENERATION:
    success = self._run_output_generation()
elif stage_name == STAGE_SEMANTIC_DIFF:
    success = self._run_semantic_diff()
```

Migration path: extract each legacy method into a standalone `Stage` subclass and register it. The if/elif shrinks; the registry grows.

### Parallel Group Execution

AST parsing of base and head commits can run independently:

```python
parallel_group = {
    STAGE_AST_PARSING_BASE,   # "ast_parsing_base"
    STAGE_AST_PARSING_HEAD,   # "ast_parsing_head"
}
```

Logic in `run_all_pending()` (`pipeline.py:384`):
1. If **all** stages in the group are pending → run them via `ThreadPoolExecutor` (up to 2 workers)
2. If **some** are already completed → run remaining sequentially
3. If any parallel stage fails → pipeline halts

`run_parallel_group()` (`pipeline.py:351`) submits stages to a `concurrent.futures.ThreadPoolExecutor`, collects results as they complete.

### Interactive Review

When `interactive=True`:
- After each reviewable stage completes, `_maybe_review()` (`pipeline.py:251`) is called
- Skips infrastructure stages (defined in `SKIP_STAGES`) and non-reviewable stages (defined in `REVIEWABLE_STAGES`)
- Uses `StageReviewer` to generate a preview of the stage output
- Presents review UI via `reviewer.review_stage(preview)`
- User decisions:
  - `accept` → continue to next stage
  - `skip` → skip remaining reviews
  - `regenerate_all` / `regenerate_partial` → invalidate this + all subsequent stages via `_invalidate_from_stage()` (`pipeline.py:321`), save feedback, return
- Feedback is persisted in the review session and passed back to stages on resume

### Resume Support

- `_load_review_session()` — loads persisted `ReviewSession` from KB on init
- `_get_feedback_for_stage(name)` — retrieves accumulated feedback for a specific stage
- `_invalidate_from_stage(name)` — resets all completed stages from `name` onward to `PENDING`
- CLI: `ggdes resume <id>` creates a new pipeline instance, calls `run_all_pending()`

### Error Handling

- **Stage failure**: caught in `run_stage()` → `fail_stage()` → returns `False`
- **Pipeline halt**: in `run_all_pending()`, any failure breaks the loop with a "Run `ggdes resume <id>` to retry" message
- **Exception safety**: every stage path is wrapped in `try/except Exception` so unexpected crashes produce a clean `fail_stage()` with traceback
- **Lock safety**: `LockContext` acquired for the full pipeline run prevents concurrent modifications

### Delegation to Stage Utilities

Several pipeline methods delegate directly to `ggdes/stages/utils.py`:
- `_get_summary_path()` → `get_summary_path(kb, id)`
- `_get_changed_files_from_analysis()` → `get_changed_files_from_analysis(kb, id)`
- `_get_changed_files_detailed()` → `get_changed_files_detailed(kb, id)`
- `_build_tool_executor()` → `build_tool_executor(config, kb, id, repo_path, metadata)`
- `_load_ast_elements_for_tools()` → `load_ast_elements(kb, id, "head")`

### Stage Method Overview

| Method | Stage | Key Operations |
|--------|-------|----------------|
| `_run_git_analysis()` (461) | STAGE_GIT_ANALYSIS | Validates commit range, runs `GitAnalyzer.analyze()`, saves `summary.json` + `diff.txt` |
| `_run_change_filter()` (533) | STAGE_CHANGE_FILTER | Uses `ChangeFilter` to semantically filter changed files; saves to `change_filter/summary.json` |
| `_run_ast_parsing(variant)` (647) | STAGE_AST_PARSING_* | Scans worktree, parses with `ASTParser` (incremental or full), saves per-file JSON |
| `_run_semantic_diff()` (960) | STAGE_SEMANTIC_DIFF | Runs `SemanticDiffAnalyzer` on changed files, saves to `semantic_diff/result.json` |
| `_run_technical_author()` (804) | STAGE_TECHNICAL_AUTHOR | Detects primary language, builds `ToolExecutor`, runs `TechnicalAuthor.synthesize()`, validates facts via `ASTValidator` |
| `_run_coordinator_plan()` (901) | STAGE_COORDINATOR_PLAN | Runs `Coordinator.create_plan()` for target formats |
| `_run_output_generation()` (1052) | STAGE_OUTPUT_GENERATION | Generates Markdown (source), then parallel DOCX/PPTX/PDF via `ThreadPoolExecutor` |

## Flow (End-to-End)

```
CLI: ggdes analyze --feature "X" --commits HEAD~3..HEAD
  │
  ▼
load_config()                        # ggdes/config/loader.py
  │
  ▼
KnowledgeBaseManager.create()        # creates analysis dir, stores metadata
  │
  ▼
AnalysisPipeline.run_all_pending()
  │
  ├── STAGE_WORKTREE_SETUP          ─ WorktreeSetupStage (extracted)
  │     └── WorktreeManager.create_for_analysis()
  │
  ├── STAGE_GIT_ANALYSIS            ─ _run_git_analysis()
  │     └── GitAnalyzer.analyze() → summary.json + diff.txt
  │
  ├── STAGE_CHANGE_FILTER           ─ _run_change_filter()
  │     └── ChangeFilter.filter_changes() → change_filter/summary.json
  │
  ├── STAGE_AST_PARSING_BASE        ─ _run_ast_parsing("base")  ┐
  ├── STAGE_AST_PARSING_HEAD        ─ _run_ast_parsing("head")  ┘ parallel group
  │     └── ASTParser → ast_{variant}/*.json
  │
  ├── STAGE_SEMANTIC_DIFF           ─ _run_semantic_diff()
  │     └── SemanticDiffAnalyzer → semantic_diff/result.json
  │
  ├── STAGE_TECHNICAL_AUTHOR        ─ _run_technical_author()
  │     └── TechnicalAuthor.synthesize() → technical_facts
  │
  ├── STAGE_COORDINATOR_PLAN        ─ _run_coordinator_plan()
  │     └── Coordinator.create_plan() → document plans
  │
  └── STAGE_OUTPUT_GENERATION       ─ _run_output_generation()
        ├── MarkdownAgent.generate()       → .md file
        ├── DocxAgent.generate()           → .docx file
        ├── PptxAgent.generate()           → .pptx file
        └── PdfAgent.generate()            → .pdf file
```

## Integration Points

- **LLM providers** (`ggdes/llm/`): All agent calls go through the provider abstraction with retry logic, structured output parsing, and thinking mode support
- **Knowledge base** (`ggdes/kb/`): Every stage reads inputs and writes outputs to the KB on disk. Enables resume, comparison, and inspection
- **Validation** (`ggdes/validation/`): Code references in LLM outputs are validated against parsed AST and git diff to prevent hallucinations
- **Diagrams** (`ggdes/diagrams/`): PlantUML diagrams are auto-generated from technical facts and embedded in all output formats
- **Review** (`ggdes/review/`): Interactive review sessions pause the pipeline after key stages, accumulating feedback for regeneration
- **Worktrees** (`ggdes/worktree/`): Isolated git worktrees for base and head commits enable safe parallel AST parsing
