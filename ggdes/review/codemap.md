# ggdes/review/ — Interactive Pipeline Review

## Responsibility

Provides the data structures and UI logic for **interactive stage review** during pipeline execution. After each reviewable pipeline stage completes, the `StageReviewer` generates a preview of the output and presents it to the user, who can accept, request regeneration (full or partial), or skip remaining reviews. This enables a human-in-the-loop feedback cycle.

**Tight coupling to CLI**: The reviewer uses `rich` tables, prompts, and panels for terminal interaction. Preview generation logic, however, is separable and reusable via the `generate_preview()` method.

## Design

### Data Model (`review.py`)

| Type | Role |
|---|---|
| `ReviewDecision` (Enum) | `ACCEPT` — proceed as-is. `REGENERATE_ALL` — re-run the stage with feedback. `REGENERATE_PARTIAL` — re-run specific items. `SKIP` — skip review for all remaining stages. |
| `StageReview` (dataclass) | Records a single stage review: `stage_name`, `decision`, `feedback`, `partial_keys` (for partial regen), `items_reviewed`, `items_accepted`. |
| `ReviewSession` (dataclass) | Tracks the overall review state: `analysis_id`, `interactive` flag, list of `stage_reviews`, `pending_partial_regen` dict, `stage_feedback` dict, `skip_remaining` flag. |

### ReviewSession Lifecycle

1. Created at the start of a pipeline run if interactive mode is on.
2. `add_review(StageReview)` → appends to `stage_reviews`, accumulates feedback in `stage_feedback`, tracks partial regeneration keys.
3. `is_skipping()` → returns `True` if user chose SKIP (short-circuits remaining reviews).
4. `to_dict()` → serializes for KB storage.
5. `from_dict()` → deserializes from KB storage (resume support).

### Reviewer (`reviewer.py`)

**StageReviewer** takes `config` and `analysis_id`, and provides:

#### Preview Generation

`generate_preview(stage_name) → StagePreview | None`

Dispatches to private `_preview_{stage_name}` methods via `getattr`. Returns `None` if the required output file doesn't exist.

| Preview Method | Reads From | Includes |
|---|---|---|
| `_preview_git_analysis()` | `git_analysis/summary.json` | Files changed, commit summary, line diff stats |
| `_preview_change_filter()` | `git_analysis/summary.json` | Filtered files (with `is_filtered` flag), relevant line ranges |
| `_preview_technical_author()` | `technical_facts/facts.json` | Facts grouped by category, fact IDs, descriptions |
| `_preview_coordinator_plan()` | `plans/plan_*.json` | Document formats, section counts |
| `_preview_output_generation()` | `outputs/` directory | Generated files by extension, file sizes |

#### StagePreview Dataclass

| Field | Description |
|---|---|
| `stage_name` | e.g., `"git_analysis"` |
| `display_name` | Human-readable, e.g., `"Git Analysis"` |
| `summary` | One-line summary |
| `item_count` | Total number of items in output |
| `key_items` | 3-5 representative items (label + detail) |
| `item_keys` | All item identifiers for partial regen selection |
| `raw_data` | Full output data (for detailed inspection) |
| `format_hint` | `"json"` or plain text |

#### Reviewable vs. Skip Stages

| Reviewable | Infrastructure (auto-skip) |
|---|---|
| `git_analysis` | `worktree_setup` |
| `change_filter` | `ast_parsing_base` |
| `technical_author` | `ast_parsing_head` |
| `coordinator_plan` | `semantic_diff` |
| `output_generation` | |

#### CLI Review Interface

`review_stage(preview) → StageReview` presents:

1. A `rich.Panel` with the stage display name and summary.
2. A `rich.Table` of key items (up to 5).
3. A numbered choice prompt:
   - **0** Accept (proceed)
   - **1** Regenerate all (with optional feedback)
   - **2** Regenerate specific items (interactive item selection)
   - **3** Skip remaining reviews
4. For partial regeneration: `_select_items()` shows up to 10 items with number/ranges input (e.g., `0,2,5` or `1-3,7` or `all`).
5. For full output inspection: `show_full_output()` renders raw JSON with `rich.Syntax`.

## Flow

```
pipeline runs stage
  → stage completes
  → if interactive:
      reviewer = StageReviewer(config, analysis_id)
      preview = reviewer.generate_preview(stage_name)
      if preview:
          review = reviewer.review_stage(preview)
          session.add_review(review)
          if review.decision == REGENERATE_ALL:
              re-run stage with feedback
          elif review.decision == REGENERATE_PARTIAL:
              re-run only specified items
          elif review.decision == SKIP:
              session.skip_remaining = True
              → skip all future reviews
      else:
          → not reviewable, skip
  → if not interactive (or skip_remaining):
      proceed without review
```

## Integration

- **`ggdes.config`**: `get_kb_path(config, analysis_id)` resolves the KB directory for reading stage output files.
- **`ggdes.kb`**: `ReviewSession.to_dict()` / `from_dict()` is persisted via `KnowledgeBaseManager.save_review_session()` / `load_review_session()`.
- **`ggdes.pipeline`**: `AnalysisPipeline` creates `ReviewSession`, checks `interactive` mode, calls `reviewer.review_stage()` after each reviewable stage, and uses the returned feedback for regeneration.
- **`ggdes.tui`**: `ReviewScreen` uses `StageReviewer.generate_preview()` to show stage summaries, and constructs a `ReviewSession` from checkbox/input widgets, saved via `KnowledgeBaseManager`.
- **`ggdes.web.routes.analyses`**: `GET /api/analyses/{id}/stage-preview/{stage_name}` uses `StageReviewer.generate_preview()` to serve stage previews to the web UI.

### Files

| File | Lines | Content |
|---|---|---|
| `review.py` | 119 | Data model: `ReviewDecision`, `StageReview`, `ReviewSession` |
| `reviewer.py` | 438 | `StageReviewer` with preview generation and CLI review UI |
