# ggdes/tui/ — Terminal UI (Textual)

## Responsibility

Provides a **full-featured terminal user interface** using the [Textual](https://textual.textualize.io/) framework. Users can browse analyses, inspect stage status, review outputs, browse git history, manage worktrees, provide section feedback, and create/resume/delete analyses — all without leaving the terminal.

The TUI is the **primary interactive front-end** for GGDes. It connects to the KB manager directly (not through the web API).

## Design

### Main Application

**`GGDesTUI(App[None])`** — the top-level application class.

#### Layout

The screen is organized as a `TabbedContent` with 6 tabs:

| Tab | ID | Widget | Purpose |
|---|---|---|---|
| 📊 Analyses | `"analyses"` | `AnalysisDetailView` + sidebar | List analyses, view details, resume/delete |
| 🌳 Worktrees | `"worktrees"` | `WorktreeView` | Manage active worktrees |
| 📜 Git Log | `"gitlog"` | `GitLogView` | Browse commits, select ranges |
| 📝 Feedback | `"feedback"` | `FeedbackView` | Provide section-level feedback |
| 🔍 Debug | `"debug"` | `DebugView` | System debugging |
| ❓ Help | `"help"` | `CommandHelp` | Keyboard shortcuts reference |

#### Keyboard Bindings

| Key | Action | Description |
|---|---|---|
| `q` | `action_quit` | Quit the TUI |
| `r` | `action_refresh` | Refresh current view |
| `a` | `action_new_analysis` | Create new analysis |
| `s` | `action_gitlog_set_start` | Set selected commit as start |
| `e` | `action_gitlog_set_end` | Set selected commit as end |
| `f` | `action_gitlog_toggle_focus` | Toggle focus commit |
| `c` | `action_gitlog_clear` | Clear all selections |
| `t` | `action_feedback_tab` | Switch to Feedback tab |
| `d` | `action_debug_tab` | Switch to Debug tab |
| `Ctrl+R` | `action_resume_selected` | Resume selected analysis |
| `Ctrl+D` | `action_delete_selected` | Delete selected analysis |

### Widgets (sorted by complexity)

#### `GitLogView(VerticalScroll)`
- Fetches commits via `git -C <repo> log` subprocess.
- Displays in a `DataTable` with columns: Hash, Date, Author, Message, Type.
- Color-codes commit types: `fix` (red), `feat` (green), `refactor` (blue), `doc` (cyan), `test` (yellow), `chore` (dim).
- Tracks reactive state: `start_commit`, `end_commit`, `focus_commits` (set).
- Supports commit range selection: `start_commit..end_commit` via `get_commit_range()`.
- Merge-base checking in `_commit_is_before()` uses `git merge-base --is-ancestor`.
- Row highlighting: green for start, red for end, yellow for focus.

#### `AnalysisDetailView(VerticalScroll)`
- Reactive: auto-updates when `analysis_id` changes.
- Shows: name, ID, repo path, commit range, created date.
- **Progress bar** — completed / total stages.
- **StageStatusWidget** per stage — colored icon + name.
  - `○` Pending (dim), `◐` In Progress (yellow), `✓` Completed (green), `✗` Failed (red), `⊘` Skipped (blue).
- **Action buttons**:
  - `▶ Resume (N pending)` — runs pipeline for remaining stages.
  - `📝 Review` — opens `ReviewScreen` if reviewable stages are completed.
  - `🔄 Regenerate Documents` — opens `FormatResumeDialog` (for completed analyses).
  - `🗑 Delete` — confirmation dialog, then cleanup + delete.
  - `📁 Open Worktree` — placeholder.
- **Revisions** section — uses `FeedbackManager.list_revisions()` to show revision history.

#### `ReviewScreen(Screen[None])`
- Shows all 5 reviewable stages (`git_analysis` through `output_generation`).
- For each completed stage: shows preview summary + key items via `StageReviewer.generate_preview()`.
- Per-stage controls: `Checkbox` (regenerate with feedback) + `Input` (feedback text).
- Loads previous review session from KB if it exists.
- Actions: `Submit & Resume` (saves session, runs pipeline) or `Skip Review`.

#### `WorktreeView(VerticalScroll)`
- Iterates `kb_manager.list_analyses()` and shows worktree info for each.
- Cards with: analysis name, base/head paths, and buttons (Open Base, Open Head, Cleanup).

#### `FormatResumeDialog(Screen[None])`
- Modal dialog triggered from the detail view on completed analyses.
- Shows 4 checkboxes: Markdown, DOCX, PDF, PPTX.
- On confirm: triggers `_regenerate_with_formats()` → resets `output_generation` (and `coordinator_plan` if formats changed) → runs pipeline.

#### `NewAnalysisDialog(Screen[None])`
- Modal dialog for creating a new analysis.
- Fields: Name, Commit Range (pre-filled from GitLogView selection), Focus Commits, Output Formats.
- On create: generates a `uuid4()`, calls `kb_manager.create_analysis()`, optionally runs pipeline.

#### `ConfirmDialog(Screen[None])`
- Generic confirmation dialog used for delete, run-after-create, etc.
- Custom CSS for modal appearance.

#### `CommandHelp(Static)`
- Static help text showing git worktree commands, GGDes CLI commands, git log keyboard shortcuts, and stage status icons.

#### `StageStatusWidget(Static)`
- Small widget: shows colored icon + stage name.

### Helper Views (separate files)

| File | Widget | Purpose |
|---|---|---|
| `feedback_view.py` | `FeedbackView` | Section-level feedback UI |
| `debug_view.py` | `DebugView` | Debug logging / system info |

## Flow

```
User launches TUI:
  GGDesTUI.run()
    → compose(): build 6-tab layout
    → loads analyses list in sidebar
    → user clicks an AnalysisListItem
        → on_list_view_selected → detail_view.analysis_id = id
        → detail_view.watch_analysis_id → update_view()
            → shows progress, stages, buttons

User creates analysis:
  → presses 'a' or clicks "New Analysis" button
  → NewAnalysisDialog with pre-filled commits from GitLogView
  → _on_create_analysis → kb_manager.create_analysis()
  → optional ConfirmDialog → pipeline.run_all_pending()

User resumes analysis:
  → clicks "Resume" button
  → pipeline = AnalysisPipeline(config, analysis_id)
  → pipeline.run_all_pending()
  → refresh()

User reviews:
  → clicks "Review" button
  → ReviewScreen pushed as screen
  → submits → session saved to KB → pipeline runs
```

## Integration

- **`ggdes.config`**: `load_config()` at startup for config + repo_path.
- **`ggdes.kb`**: `KnowledgeBaseManager` for all CRUD — list, load, create, delete analyses. `StageStatus` enum for status display.
- **`ggdes.review`**: `StageReviewer.generate_preview()` for review summaries. `ReviewSession`/`StageReview`/`ReviewDecision` for review state management.
- **`ggdes.pipeline`**: `AnalysisPipeline.run_all_pending()` for resuming/regenerating.
- **`ggdes.worktree`**: `WorktreeManager` for cleanup on delete.
- **`ggdes.feedback`**: `FeedbackManager.list_revisions()` for revision display.

### Files

| File | Lines | Content |
|---|---|---|
| `app.py` | 1729 | Main TUI app + all widgets except FeedbackView/DebugView |
| `feedback_view.py` | — | Feedback tab widget |
| `debug_view.py` | — | Debug tab widget |

The main app file is large (1729 lines) because it contains 10+ widget classes plus the main `GGDesTUI` class in a single file.
