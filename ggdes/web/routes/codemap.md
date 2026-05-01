# ggdes/web/routes/ — FastAPI Route Modules

## Responsibility

All HTTP and WebSocket endpoints for the GGDes web interface. There are **24 routes** across **5 modules**, organized by domain: analyses CRUD, feedback persistence, page serving, worktree management, and real-time WebSocket communication.

## Route Summary

| Module | File | Prefix | Routes |
|---|---|---|---|
| **analyses** | `analyses.py` | (none) | 13 |
| **feedback** | `feedback.py` | (none) | 3 |
| **pages** | `pages.py` | (none) | 3 |
| **worktrees** | `worktrees.py` | (none) | 3 |
| **ws** | `ws.py` | (none) | 1 (WebSocket) |

All routers are created with `APIRouter()` (no prefix — the full path is specified in each decorator). They are registered in `ggdes/web/__init__.py` with `app.include_router()`.

---

## `analyses.py` — Analysis CRUD + Document Routes (13 routes)

The largest route module. Handles listing, reading, creating, deleting analyses, plus document retrieval and feedback-driven regeneration.

### Endpoints

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/api/analyses` | `list_analyses` | List all analyses with progress (completed/failed/pending counts, percent) and stage details. |
| `GET` | `/api/analyses/{analysis_id}` | `get_analysis` | Detailed view of a single analysis: stages, git summary, facts count, plans, worktree age. |
| `POST` | `/api/analyses` | `create_analysis` | Create a new analysis. Query params: `name`, `commit_range`, `focus_commits`, `formats`. Generates UUID. Broadcasts `analysis_created`. |
| `POST` | `/api/analyses/{analysis_id}/resume` | `resume_analysis` | Resume/regenerate. Optional JSON body `{"formats": [...]}` to reset specific stages. Runs `AnalysisPipeline.run_all_pending()`. Broadcasts `analysis_updated`. |
| `POST` | `/api/analyses/{analysis_id}/regenerate` | `regenerate_from_feedback` | Save section feedback + trigger regeneration via `FeedbackManager.regenerate()`. Returns new `revision_id`. Broadcasts `analysis_updated`. |
| `POST` | `/api/analyses/{analysis_id}/delete` | `delete_analysis` | Clean up worktrees + remove from KB. Query param `remove_kb` (default True). Broadcasts `analysis_deleted`. |
| `GET` | `/api/analyses/{analysis_id}/revisions` | `list_revisions` | List all revisions using `FeedbackManager.list_revisions()`. Includes `current` revision ID. |
| `PUT` | `/api/analyses/{analysis_id}/revisions/current` | `set_current_revision` | Set current revision (no regeneration). Body: `{"revision_id": "..."}`. |
| `GET` | `/api/analyses/{analysis_id}/documents` | `get_documents` | List generated documents from output directory by format. Returns name, path, size, modified time. |
| `GET` | `/api/analyses/{analysis_id}/documents/{format}/download` | `download_document` | Stream a generated document file as `FileResponse`. |
| `GET` | `/api/analyses/{analysis_id}/diagrams` | `get_diagrams` | List generated diagram files (.png, .svg, .pdf) from output directory. |
| `GET` | `/api/analyses/{analysis_id}/plan` | `get_document_plan` | Get the latest document plan JSON. |
| `GET` | `/api/analyses/{analysis_id}/outputs` | `list_outputs` | List all output files in the analysis directory (JSON, MD, TXT, YAML). Recursive glob with relative paths. |
| `GET` | `/api/analyses/{analysis_id}/outputs/content` | `get_output_content` | Read and return content of a specific output file. Query param: `path`. Pretty-prints JSON files. |
| `GET` | `/api/analyses/{analysis_id}/stage-preview/{stage_name}` | `get_stage_preview` | Generate a stage preview via `StageReviewer.generate_preview()`. Returns summary, item_count, key_items. |

### Request Models

| Model | Fields | Used By |
|---|---|---|
| `ResumeRequest` | `formats: list[str] \| None` | `resume_analysis` |
| `RegenerateRequest` | `section_feedback: dict[str, str]`, `stage_feedback`, `affects_structure`, `summary` | `regenerate_from_feedback` |
| `SetRevisionRequest` | `revision_id: str` | `set_current_revision` |

---

## `feedback.py` — Feedback Persistence (3 routes)

### Endpoints

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/api/analyses/{analysis_id}/feedback` | `get_feedback` | Get all section feedback as `dict[str, str]` (section_title → feedback text). |
| `POST` | `/api/analyses/{analysis_id}/feedback` | `save_feedback` | Save feedback for a single section. Query params: `section_title`, `feedback`. |
| `POST` | `/api/analyses/{analysis_id}/feedback/bulk` | `save_feedback_bulk` | Save feedback for multiple sections at once. Body: `{"feedback_items": [{"section": "...", "feedback": "..."}]}`. Returns count saved. |

All feedback endpoints delegate to `KnowledgeBaseManager.save_section_feedback()` / `load_section_feedback()`.

---

## `pages.py` — HTML Page Routes (3 routes)

### Endpoints

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/` | `root` | Serves `INDEX_HTML` — the main dashboard. |
| `GET` | `/feedback/{analysis_id}` | `feedback_page` | Serves `FEEDBACK_HTML` — split-panel feedback interface. Injects `analysis_id`, `analysis_name`, `plan_json`, `feedback_json` via `str.format()`. |
| `GET` | `/analysis/{analysis_id}` | `analysis_detail_page` | Serves `DETAIL_HTML` — analysis detail page. Injects `analysis_id`, `analysis_name`, `stages_json`, `documents_json`, `plans_json`, `target_formats`, etc. |

These are the only routes returning `HTMLResponse`. All other routes return JSON.

Each page route loads metadata from KB, builds the necessary data structures, and formats them into the HTML template as JSON strings embedded in `<script>` tags for client-side rendering.

---

## `worktrees.py` — Worktree + Stats Routes (3 routes)

### Endpoints

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/api/stats` | `get_stats` | System-wide statistics: analysis counts (total/completed/failed/in_progress), worktree count + total size in MB, config paths (repo, KB, worktree). |
| `GET` | `/api/worktrees/cleanup-preview` | `preview_worktree_cleanup` | Dry-run of worktree cleanup. Query param: `days` (default 7). Returns list of worktrees that would be removed with their age. |
| `POST` | `/api/worktrees/cleanup` | `cleanup_worktrees` | Execute worktree cleanup. Query param: `days` (default 7). Returns list of removed worktrees. |

Stats computation:
- `completed` = all stages `COMPLETED`
- `failed` = any stage `FAILED`
- `in_progress` = any stage `IN_PROGRESS`
- Worktree size = sum of all file sizes in all base/head directories

---

## `ws.py` — WebSocket (1 endpoint)

### Endpoint

| Type | Path | Handler | Description |
|---|---|---|---|
| WebSocket | `/ws` | `websocket_endpoint` | Real-time update stream. |

Protocol:
1. Server accepts the connection via `manager.connect(websocket)`.
2. Server enters a receive loop waiting for client messages.
3. Client can send `{"action": "subscribe", "analysis_id": "..."}` → server confirms.
4. On disconnect: server calls `manager.disconnect()`.
5. Server broadcasts `analysis_updated`, `analysis_created`, `analysis_deleted` events to all connected clients via `manager.broadcast()`.

The `ConnectionManager` singleton (`ggdes.web.manager.manager`) is shared between this module and any route module that triggers broadcast events (analyses.py in particular).

---

## Flow for Key Operations

### Loading the Dashboard
```
GET / → pages.root() → INDEX_HTML
  JS: connectWebSocket() → ws://host/ws
  JS: loadStats() → GET /api/stats → stats cards rendered
  JS: loadAnalyses() → GET /api/analyses → analysis list rendered
```

### Creating an Analysis (via API)
```
POST /api/analyses?name=X&commit_range=abc..def&formats=markdown
  → create_analysis()
  → kb.create_analysis()
  → manager.broadcast({"type": "analysis_created", ...})
  → returns {id, name, ...}
```

### Providing Feedback + Regenerating
```
User fills textareas in FEEDBACK_HTML
  → POST /api/analyses/{id}/feedback/bulk (auto-save on "Save All Feedback")
  → POST /api/analyses/{id}/regenerate (on "Save & Regenerate")
     → kb.save_section_feedback() for each section
     → FeedbackManager.regenerate() → saves revision
     → manager.broadcast({"type": "analysis_updated", ...})
     → reloads page after 2 seconds
```

### Worktree Cleanup
```
User clicks "Preview Cleanup" in dashboard
  → GET /api/worktrees/cleanup-preview?days=7
  → wt_manager.cleanup_old_worktrees(dry_run=True)
  → shows list of old worktrees

User clicks "Cleanup Old Worktrees"
  → POST /api/worktrees/cleanup?days=7
  → wt_manager.cleanup_old_worktrees(dry_run=False)
  → alert with count, reload stats
```

## Integration

All route modules share these common dependencies:

- **`ggdes.web.manager`**: `get_kb()`, `get_config()`, `manager` (ConnectionManager singleton)
- **`ggdes.kb`**: `KnowledgeBaseManager`, `StageStatus` enum
- **`ggdes.config`**: `GGDesConfig`, `get_output_path()`, `get_kb_path()`
- **`ggdes.pipeline`**: `AnalysisPipeline` (resume/regenerate routes)
- **`ggdes.worktree`**: `WorktreeManager` (stats, cleanup routes)
- **`ggdes.feedback`**: `FeedbackManager` (revision routes)
- **`ggdes.review`**: `StageReviewer` (stage-preview route)

### Files

| File | Lines | Routes | Content |
|---|---|---|---|
| `analyses.py` | 575 | 15 | Analysis CRUD, documents, diagrams, plans, outputs, regeneration |
| `feedback.py` | 46 | 3 | Feedback get/save (single + bulk) |
| `pages.py` | 134 | 3 | HTML page serving (dashboard, detail, feedback) |
| `worktrees.py` | 122 | 3 | System stats, worktree cleanup preview + execute |
| `ws.py` | 33 | 1 (WS) | WebSocket endpoint for real-time updates |
