# ggdes/web/ — FastAPI Web Interface

## Responsibility

Provides a **modern web interface** for GGDes using FastAPI. Users can view the dashboard of all analyses, see detailed analysis info with stage progress, provide section-level feedback with a rich split-panel UI, manage worktrees (preview + cleanup), and get real-time updates via WebSocket.

The web layer is a **thin wrapper** over the KB manager and pipeline — it serves data read from the filesystem and triggers pipeline runs on demand. There is no separate persistence; it reuses the same filesystem-backed KB as the CLI and TUI.

## Design

### App Factory (`__init__.py`)

```python
app = FastAPI(title="GGDes Web", ...)
app.include_router(analyses_router)
app.include_router(feedback_router)
app.include_router(worktrees_router)
app.include_router(pages_router)
app.include_router(ws_router)
```

A single `FastAPI` instance imports and registers 5 route modules. There is no `create_app()` factory function — the module-level `app` is created at import time for direct `uvicorn.run()`.

Entry point: `python -m ggdes.web` runs `uvicorn.run(app, host="0.0.0.0", port=8000)`.

### ConnectionManager (`manager.py`)

**`ConnectionManager`** manages WebSocket connections for real-time updates:

| Method | Description |
|---|---|
| `connect(websocket)` | Accepts the WS, adds to `active_connections` list |
| `disconnect(websocket)` | Removes from list |
| `broadcast(message)` | Sends JSON to all connected clients; removes dead connections |

The module-level singleton `manager = ConnectionManager()` is shared across all route modules.

**Helper functions**:
- `get_kb()` → instantiates `KnowledgeBaseManager` from config.
- `get_config()` → loads `GGDesConfig`.

### Templates (`templates.py`)

Three inline HTML templates (no Jinja2 — pure Python string formatting):

| Template | Route | Description |
|---|---|---|
| `INDEX_HTML` | `GET /` | Main dashboard: stats cards, analysis list with progress bars, quick actions (refresh/cleanup) |
| `FEEDBACK_HTML` | `GET /feedback/{id}` | Split-panel: left=document sections with feedback textareas, right=output file tree with live content viewer. Polls for new files every 5 seconds. |
| `DETAIL_HTML` | `GET /analysis/{id}` | Detail card: analysis info, stage progress with color-coded list, generated documents list, document plans list. Modal for format selection when regenerating. |

All templates use **inline CSS** with a purple gradient theme (`#667eea → #764ba2`), responsive grid layout, and single-page-application-style JavaScript for dynamic updates.

#### CSS Design Notes
- **Stats grid**: `auto-fit, minmax(200px, 1fr)` responsive layout.
- **Feedback page**: `40% / 60%` split; collapses to stacked on mobile (`768px` breakpoint).
- **Animations**: pulse for WS status indicator, spin for loading spinner.
- **Status badges**: colored pills (green=completed, red=failed, yellow=pending, cyan=in-progress).

### WebSocket Protocol

Clients connect to `ws://host/ws`. The server accepts, adds to `ConnectionManager`, and enters a receive loop. Client messages are parsed as JSON:

| Client Action | Server Response |
|---|---|
| `{"action": "subscribe", "analysis_id": "..."}` | `{"type": "subscribed", "analysis_id": "..."}` |

**Server-to-client messages** (broadcast):

| Type | Trigger |
|---|---|
| `analysis_updated` | After resume/regenerate completes |
| `analysis_created` | After new analysis created |
| `analysis_deleted` | After analysis deleted |

The front-end JavaScript in `INDEX_HTML` listens for these types and automatically refreshes the analysis list and stats via `fetch()`.

## Flow

```
Browser → GET /
  → pages_router.root()
  → serves INDEX_HTML
  → JS connects WebSocket, loads stats + analyses via /api/stats and /api/analyses

Browser → GET /analysis/{id}
  → pages_router.analysis_detail_page()
  → loads metadata, stages, plans, documents
  → serves DETAIL_HTML with JSON data embedded in <script> tags

Browser → GET /feedback/{id}
  → pages_router.feedback_page()
  → loads plan + existing feedback
  → serves FEEDBACK_HTML with data embedded

User clicks "Resume" in dashboard:
  → POST /api/analyses/{id}/resume
  → analyses_router.resume_analysis()
  → runs AnalysisPipeline.run_all_pending()
  → broadcasts analysis_updated via WebSocket

User submits feedback:
  → POST /api/analyses/{id}/feedback/bulk
  → feedback_router.save_feedback_bulk()
  → KnowledgeBaseManager.save_section_feedback() for each item
```

## Integration

- **`ggdes.kb`**: All routes use `KnowledgeBaseManager` for loading/saving metadata, feedback, and document plans. `get_kb()` helper in `manager.py` instantiates it.
- **`ggdes.pipeline`**: `AnalysisPipeline` is called by the resume/regenerate endpoints.
- **`ggdes.worktree`**: `WorktreeManager` is used by stats, cleanup-preview, and cleanup endpoints.
- **`ggdes.feedback`**: `FeedbackManager` is used by the regenerate endpoint for revision lifecycle.
- **`ggdes.config`**: `GGDesConfig` and helper path functions (`get_output_path`, `get_kb_path`) are used across routes.
- **`ggdes.review`**: `StageReviewer.generate_preview()` is called by the stage-preview API endpoint.

### Files

| File | Lines | Content |
|---|---|---|
| `__init__.py` | 27 | App creation, router registration, uvicorn entry point |
| `manager.py` | 51 | `ConnectionManager` class + singleton, `get_kb()`/`get_config()` helpers |
| `templates.py` | 1272 | Three inline HTML templates (INDEX_HTML, FEEDBACK_HTML, DETAIL_HTML) + embedded CSS/JS |
| `routes/` | — | 5 route modules (see routes/codemap.md) |
