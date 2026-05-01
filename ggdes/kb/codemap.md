# ggdes/kb/ — Knowledge Base (File-System Analysis State)

## Responsibility

The KB module is the **persistence layer** for all analysis state and data. It stores analysis metadata, stage tracking, generated artifacts, review sessions, and user feedback — all on the filesystem. There is no database; the filesystem _is_ the database.

Successive analyses reuse the same metadata file, and stages update their status in-place, so interrupted runs can be resumed by re-reading the saved state.

## Design

### Key Types

| Type | Role |
|---|---|
| `StageStatus` (Enum) | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `SKIPPED` — stage lifecycle states |
| `StageInfo` (Pydantic) | Status + started_at + completed_at + output_path + error_message for a single stage |
| `WorktreeInfo` (Pydantic) | Tracks `base` / `head` worktree paths, creation timestamp, cleanup policy |
| `DocumentInfo` (Pydantic) | Tracks generated document format, file path, generation timestamp |
| `AnalysisMetadata` (Pydantic) | Full analysis record — the central data structure. Fields: `id`, `name`, `repo_path`, `commit_range`, `focus_commits`, `created_at`/`updated_at`, `prompt_version`, `target_formats`, `storage_policy`, `user_context`, `feature_description`, `no_filter`, `worktrees`, `stages` (dict), `documents` (list), `current_revision`, `render_png` |
| `KnowledgeBaseManager` | CRUD operations on `AnalysisMetadata` + review/feedback persistence |

### Stage Lifecycle

The `AnalysisMetadata` object owns a `dict[str, StageInfo]` keyed by stage name. Stage names are defined as constants on `KnowledgeBaseManager`:

```
STAGE_WORKTREE_SETUP     → "worktree_setup"
STAGE_GIT_ANALYSIS       → "git_analysis"
STAGE_CHANGE_FILTER      → "change_filter"
STAGE_AST_PARSING_BASE   → "ast_parsing_base"
STAGE_AST_PARSING_HEAD   → "ast_parsing_head"
STAGE_SEMANTIC_DIFF      → "semantic_diff"
STAGE_TECHNICAL_AUTHOR   → "technical_author"
STAGE_COORDINATOR_PLAN   → "coordinator_plan"
STAGE_OUTPUT_GENERATION  → "output_generation"
```

All 9 stages are initialized as `PENDING` when an analysis is created.

### Stage Transition Methods (on `AnalysisMetadata`)

| Method | Effect |
|---|---|
| `start_stage(name)` | Sets `IN_PROGRESS`, records `started_at`, clears error |
| `complete_stage(name, output_path?)` | Sets `COMPLETED`, records `completed_at` |
| `fail_stage(name, error_message)` | Sets `FAILED`, records `completed_at` + error |
| `reset_stage(name)` | Resets to `PENDING`, clears all timestamps and error |
| `skip_stage(name)` | Sets `SKIPPED`, records `completed_at` |

Helper queries: `is_stage_completed(name)`, `get_completed_stages()`, `get_pending_stages()`.

### Resume Support

`KnowledgeBaseManager.can_resume(analysis_id, retry_failed=False)` → `(bool, reason)`:
- Returns `(False, reason)` if the analysis doesn't exist.
- Returns `(False, "Stage 'X' failed")` if any stage is `FAILED` and `retry_failed` is `False`.
- Otherwise returns `(True, None)`.

`reset_failed_stages(analysis_id)` resets all `FAILED` stages back to `PENDING` for retry.

### Review/Feedback Persistence

- **Review sessions**: Serialized as `review_session.json` in the analysis directory. Uses `ReviewSession.to_dict()` / `ReviewSession.from_dict()` pattern. Saved/loaded via `save_review_session()` / `load_review_session()` on `KnowledgeBaseManager`.
- **Section feedback**: Stored in `section_feedback.json`. Each section maps to `{"feedback": str, "updated_at": ISO timestamp}`. Older entries stored as plain strings are auto-normalized. Methods: `save_section_feedback()`, `load_section_feedback()`, `load_section_feedback_with_timestamps()`.

### Directory Layout

Each analysis lives under `{kb_base}/analyses/{id}/`:

```
analyses/{id}/
├── metadata.yaml          # AnalysisMetadata serialized as YAML
├── review_session.json    # Review session state (optional)
├── section_feedback.json  # Section-level feedback (optional)
├── git_analysis/          # Git diff summary JSON
├── ast_base/              # Base commit AST data
├── ast_head/              # Head commit AST data
├── semantic_descriptions/ # Semantic diff output
├── technical_facts/       # Technical facts JSON
├── plans/                 # Document plan JSON files (plan_*.json)
├── diagrams/              # Generated diagram images
└── outputs/               # Generated documents by format
```

### Storage Format

Metadata is serialized as **YAML** (human-readable, diff-friendly). Stage status enums and storage policy enums are converted to their string `.value` before serialization.

## Flow

```
create_analysis()
  ├─ mkdir analysis directories (git_analysis, ast_base, etc.)
  ├─ create AnalysisMetadata with all stages=PENDING
  ├─ save as metadata.yaml
  └─ return metadata

pipeline runs:
  ├─ load_metadata() → check stage status
  ├─ metadata.start_stage("X")
  ├─ save_metadata()
  ├─ ... do work ...
  ├─ metadata.complete_stage("X", output_path)
  └─ save_metadata()

resume:
  ├─ load_metadata()
  ├─ can_resume() check
  ├─ get_pending_stages() → determine what to run
  └─ run only pending stages

feedback cycle:
  ├─ save_section_feedback(title, text) → write to section_feedback.json
  ├─ load_section_feedback() → dict for agent consumption
  └─ save_review_session() → store ReviewSession state
```

## Integration

- **`ggdes.config`**: Provides `GGDesConfig` and `get_kb_path()` / `get_worktrees_path()` for resolving paths.
- **`ggdes.pipeline`**: `AnalysisPipeline` loads metadata, iterates `ALL_STAGES`, calls `start_stage`/`complete_stage`/`fail_stage`.
- **`ggdes.review`**: `ReviewSession.to_dict()` feeds into `save_review_session()`.
- **`ggdes.tui`**: `GGDesTUI` and `AnalysisDetailView` use `KnowledgeBaseManager` to list/load/delete analyses.
- **`ggdes.web`**: All API routes use `get_kb()` which returns a `KnowledgeBaseManager`.
- **`ggdes.feedback`**: `FeedbackManager` reads/writes section feedback, manages revision lifecycle.

### File: `manager.py` (576 lines)

Single-file module. No sub-modules. Exports `KnowledgeBaseManager`, `AnalysisMetadata`, `StageStatus`, `StageInfo`, `WorktreeInfo`, `DocumentInfo`.
