"""Web interface for GGDes using FastAPI.

Provides a web UI for managing and viewing analyses, with real-time
updates and a modern, responsive interface.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from ggdes.config import GGDesConfig, load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.pipeline import AnalysisPipeline
from ggdes.worktree import WorktreeManager

app = FastAPI(title="GGDes Web", description="Web interface for GGDes analysis")


# Connection manager for WebSocket broadcasts
class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


def get_kb() -> KnowledgeBaseManager:
    """Get knowledge base manager."""
    config, _ = load_config()
    return KnowledgeBaseManager(config)


def get_config() -> GGDesConfig:
    """Get configuration."""
    config, _ = load_config()
    return config


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serve the main web interface."""
    return HTMLResponse(content=INDEX_HTML, status_code=200)


@app.get("/api/analyses")
async def list_analyses() -> list[dict[str, Any]]:
    """List all analyses."""
    kb = get_kb()
    analyses: list[dict[str, Any]] = []

    for analysis_id, metadata in kb.list_analyses():
        # Calculate progress
        total = len(metadata.stages)
        completed = sum(
            1 for s in metadata.stages.values() if s.status == StageStatus.COMPLETED
        )
        failed = sum(
            1 for s in metadata.stages.values() if s.status == StageStatus.FAILED
        )
        pending = total - completed - failed

        analyses.append(
            {
                "id": analysis_id,
                "name": metadata.name,
                "repo_path": metadata.repo_path,
                "commit_range": metadata.commit_range,
                "created_at": metadata.created_at.isoformat(),
                "progress": {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "pending": pending,
                    "percent": (completed / total * 100) if total > 0 else 0,
                },
                "stages": {
                    name: {
                        "status": stage.status.value,
                        "started_at": stage.started_at.isoformat()
                        if stage.started_at
                        else None,
                        "completed_at": stage.completed_at.isoformat()
                        if stage.completed_at
                        else None,
                        "error": stage.error_message,
                    }
                    for name, stage in metadata.stages.items()
                },
                "target_formats": metadata.target_formats or ["markdown"],
                "worktrees": {
                    "base": metadata.worktrees.base if metadata.worktrees else None,
                    "head": metadata.worktrees.head if metadata.worktrees else None,
                }
                if metadata.worktrees
                else None,
            }
        )

    return analyses


@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict[str, Any]:
    """Get detailed information about an analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Load git analysis summary if available
    git_summary = None
    git_summary_path = (
        kb.get_analysis_path(analysis_id) / "git_analysis" / "summary.json"
    )
    if git_summary_path.exists():
        try:
            git_summary = json.loads(git_summary_path.read_text())
        except Exception:
            pass

    # Load technical facts count
    facts_dir = kb.get_analysis_path(analysis_id) / "technical_facts"
    facts_count = len(list(facts_dir.glob("*.json"))) if facts_dir.exists() else 0

    # Load document plans
    plans_dir = kb.get_analysis_path(analysis_id) / "plans"
    plans = []
    if plans_dir.exists():
        for plan_file in plans_dir.glob("*.json"):
            try:
                plan_data = json.loads(plan_file.read_text())
                plans.append(
                    {
                        "format": plan_file.stem,
                        "sections": len(plan_data.get("sections", [])),
                        "diagrams": len(plan_data.get("diagrams", [])),
                    }
                )
            except Exception:
                pass

    # Get worktree age
    config = get_config()
    wt_manager = WorktreeManager(config, Path(metadata.repo_path))
    worktree_age = wt_manager.get_worktree_age(analysis_id)

    return {
        "id": analysis_id,
        "name": metadata.name,
        "repo_path": metadata.repo_path,
        "commit_range": metadata.commit_range,
        "focus_commits": metadata.focus_commits,
        "created_at": metadata.created_at.isoformat(),
        "target_formats": metadata.target_formats,
        "storage_policy": metadata.storage_policy,
        "stages": {
            name: {
                "status": stage.status.value,
                "started_at": stage.started_at.isoformat()
                if stage.started_at
                else None,
                "completed_at": stage.completed_at.isoformat()
                if stage.completed_at
                else None,
                "error": stage.error_message,
                "output_path": stage.output_path,
            }
            for name, stage in metadata.stages.items()
        },
        "git_summary": git_summary,
        "facts_count": facts_count,
        "plans": plans,
        "worktrees": {
            "base": metadata.worktrees.base if metadata.worktrees else None,
            "head": metadata.worktrees.head if metadata.worktrees else None,
            "age_days": worktree_age,
        }
        if metadata.worktrees
        else None,
    }


@app.post("/api/analyses/{analysis_id}/resume")
async def resume_analysis(analysis_id: str) -> dict[str, Any]:
    """Resume an analysis."""
    config = get_config()
    kb = get_kb()

    metadata = kb.load_metadata(analysis_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    try:
        pipeline = AnalysisPipeline(config, analysis_id)
        success = pipeline.run_all_pending()

        # Broadcast update to all connected clients
        await manager.broadcast(
            {
                "type": "analysis_updated",
                "analysis_id": analysis_id,
                "status": "completed" if success else "incomplete",
            }
        )

        return {"success": success, "analysis_id": analysis_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/analyses/{analysis_id}/delete")
async def delete_analysis(analysis_id: str, remove_kb: bool = True) -> dict[str, Any]:
    """Delete an analysis."""
    config = get_config()
    kb = get_kb()

    metadata = kb.load_metadata(analysis_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    try:
        # Clean up worktrees
        wt_manager = WorktreeManager(config, Path(metadata.repo_path))
        wt_manager.cleanup(analysis_id)

        # Remove from KB if requested
        if remove_kb:
            kb.delete_analysis(analysis_id)

        # Broadcast deletion
        await manager.broadcast(
            {
                "type": "analysis_deleted",
                "analysis_id": analysis_id,
            }
        )

        return {"deleted": True, "analysis_id": analysis_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/analyses")
async def create_analysis(
    name: str,
    commit_range: str,
    focus_commits: list[str] | None = None,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new analysis."""
    import uuid

    config = get_config()
    kb = get_kb()

    analysis_id = str(uuid.uuid4())
    target_formats = formats or ["markdown"]

    try:
        metadata = kb.create_analysis(
            analysis_id=analysis_id,
            name=name,
            repo_path=Path(config.repo.path) if config.repo.path else Path.cwd(),
            commit_range=commit_range,
            focus_commits=focus_commits,
            target_formats=target_formats,
        )

        # Broadcast creation
        await manager.broadcast(
            {
                "type": "analysis_created",
                "analysis_id": analysis_id,
                "name": name,
            }
        )

        return {
            "id": analysis_id,
            "name": name,
            "commit_range": commit_range,
            "target_formats": target_formats,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/analyses/{analysis_id}/documents")
async def get_documents(analysis_id: str) -> list[dict[str, Any]]:
    """Get list of generated documents for an analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    documents = []

    # Look for generated documents in common locations
    docs_base = Path(metadata.repo_path) / "docs"
    if docs_base.exists():
        for fmt in metadata.target_formats or ["markdown"]:
            fmt_dir = docs_base / fmt
            if fmt_dir.exists():
                for doc_file in fmt_dir.glob(f"*{analysis_id}*"):
                    if doc_file.is_file():
                        documents.append(
                            {
                                "format": fmt,
                                "path": str(doc_file),
                                "name": doc_file.name,
                                "size": doc_file.stat().st_size,
                                "modified": datetime.fromtimestamp(
                                    doc_file.stat().st_mtime
                                ).isoformat(),
                            }
                        )

    return documents


@app.get("/api/analyses/{analysis_id}/documents/{format}/download")
async def download_document(analysis_id: str, format: str) -> FileResponse:
    """Download a generated document."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Find the document
    docs_base = Path(metadata.repo_path) / "docs" / format
    if not docs_base.exists():
        raise HTTPException(status_code=404, detail="Format not found")

    for doc_file in docs_base.glob(f"*{analysis_id}*"):
        if doc_file.is_file():
            return FileResponse(
                path=doc_file,
                filename=doc_file.name,
                media_type="application/octet-stream",
            )

    raise HTTPException(status_code=404, detail="Document not found")


@app.get("/api/analyses/{analysis_id}/diagrams")
async def get_diagrams(analysis_id: str) -> list[dict[str, Any]]:
    """Get list of diagrams for an analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    diagrams = []
    diagrams_dir = Path(metadata.repo_path) / "docs" / "diagrams"

    if diagrams_dir.exists():
        for diag_file in diagrams_dir.glob(f"*{analysis_id}*"):
            if diag_file.suffix in [".png", ".svg", ".pdf"]:
                diagrams.append(
                    {
                        "name": diag_file.name,
                        "path": str(diag_file),
                        "type": diag_file.suffix.lstrip("."),
                        "size": diag_file.stat().st_size,
                    }
                )

    return diagrams


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                # Handle subscription requests, etc.
                if message.get("action") == "subscribe":
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "analysis_id": message.get("analysis_id"),
                        }
                    )
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/stats")
async def get_stats() -> dict[str, Any]:
    """Get overall system statistics."""
    kb = get_kb()
    config = get_config()

    analyses = kb.list_analyses()
    total = len(analyses)

    completed = 0
    failed = 0
    in_progress = 0

    for _, metadata in analyses:
        stage_statuses = [s.status for s in metadata.stages.values()]
        if all(s == StageStatus.COMPLETED for s in stage_statuses):
            completed += 1
        elif any(s == StageStatus.FAILED for s in stage_statuses):
            failed += 1
        elif any(s == StageStatus.IN_PROGRESS for s in stage_statuses):
            in_progress += 1

    # Get worktree info
    wt_manager = WorktreeManager(
        config, Path(config.repo.path) if config.repo.path else Path.cwd()
    )
    all_worktrees = wt_manager.list_all()

    # Calculate total size of worktrees
    total_size = 0
    for _, base_path, head_path in all_worktrees:
        try:
            for path in [base_path, head_path]:
                if path.exists():
                    total_size += sum(
                        f.stat().st_size for f in path.rglob("*") if f.is_file()
                    )
        except Exception:
            pass

    return {
        "analyses": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
        },
        "worktrees": {
            "count": len(all_worktrees),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        },
        "config": {
            "repo_path": str(config.repo.path) if config.repo.path else None,
            "kb_path": str(config.paths.knowledge_base),
            "worktree_path": str(config.paths.worktrees),
        },
    }


@app.get("/api/worktrees/cleanup-preview")
async def preview_worktree_cleanup(
    days: int = Query(default=7, ge=1),
) -> dict[str, Any]:
    """Preview worktrees that would be cleaned up."""
    config = get_config()
    wt_manager = WorktreeManager(
        config, Path(config.repo.path) if config.repo.path else Path.cwd()
    )

    old_worktrees = wt_manager.cleanup_old_worktrees(max_age_days=days, dry_run=True)

    return {
        "would_cleanup": len(old_worktrees),
        "max_age_days": days,
        "worktrees": [
            {
                "analysis_id": analysis_id,
                "path": str(path),
                "age_days": round(age_days, 1),
            }
            for analysis_id, path, age_days in old_worktrees
        ],
    }


@app.post("/api/worktrees/cleanup")
async def cleanup_worktrees(days: int = Query(default=7, ge=1)) -> dict[str, Any]:
    """Clean up old worktrees."""
    config = get_config()
    wt_manager = WorktreeManager(
        config, Path(config.repo.path) if config.repo.path else Path.cwd()
    )

    cleaned = wt_manager.cleanup_old_worktrees(max_age_days=days, dry_run=False)

    return {
        "cleaned": len(cleaned),
        "max_age_days": days,
        "worktrees": [
            {
                "analysis_id": analysis_id,
                "path": str(path),
                "age_days": round(age_days, 1),
            }
            for analysis_id, path, age_days in cleaned
        ],
    }


# Simple HTML interface
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GGDes Web</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        header h1 { font-size: 2.5em; margin-bottom: 10px; }
        header p { opacity: 0.9; font-size: 1.1em; }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-card .number {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        .stat-card .label { color: #666; margin-top: 5px; }
        
        .section {
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .section h2 {
            margin-bottom: 20px;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .analysis-list {
            list-style: none;
        }
        .analysis-item {
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 15px;
            transition: box-shadow 0.2s;
        }
        .analysis-item:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .analysis-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .analysis-name {
            font-weight: bold;
            font-size: 1.1em;
            color: #333;
        }
        .analysis-id {
            color: #999;
            font-size: 0.85em;
            font-family: monospace;
        }
        .progress-bar {
            background: #e0e0e0;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.3s;
        }
        .status-badges {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            font-size: 0.85em;
        }
        .badge {
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 500;
        }
        .badge.completed { background: #d4edda; color: #155724; }
        .badge.failed { background: #f8d7da; color: #721c24; }
        .badge.pending { background: #fff3cd; color: #856404; }
        .badge.in-progress { background: #d1ecf1; color: #0c5460; }
        
        .actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover { background: #5a6fd6; }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover { background: #c82333; }
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        .btn-secondary:hover { background: #545b62; }
        
        .status-connected {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #28a745;
            border-radius: 50%;
            margin-right: 5px;
            animation: pulse 2s infinite;
        }
        .status-disconnected {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #dc3545;
            border-radius: 50%;
            margin-right: 5px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .analysis-header { flex-direction: column; align-items: flex-start; }
            .actions { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>GGDes Web</h1>
            <p>Git-based Design Documentation Generator - Web Interface</p>
            <div style="margin-top: 15px; font-size: 0.9em;">
                <span id="ws-status" class="status-disconnected"></span>
                <span id="ws-text">Disconnected</span>
            </div>
        </header>
        
        <div class="stats-grid" id="stats-container">
            <div class="loading">
                <div class="spinner"></div>
                <p>Loading statistics...</p>
            </div>
        </div>
        
        <div class="section">
            <h2>Analyses</h2>
            <div id="analyses-list">
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Loading analyses...</p>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>Quick Actions</h2>
            <div class="actions">
                <button class="btn btn-secondary" onclick="loadAnalyses()">Refresh</button>
                <button class="btn btn-secondary" onclick="previewCleanup()">Preview Cleanup</button>
                <button class="btn btn-danger" onclick="runCleanup()">Cleanup Old Worktrees</button>
            </div>
            <div id="cleanup-preview" style="margin-top: 15px; display: none;"></div>
        </div>
    </div>
    
    <script>
        let ws = null;
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('ws-status').className = 'status-connected';
                document.getElementById('ws-text').textContent = 'Connected';
            };
            
            ws.onclose = () => {
                document.getElementById('ws-status').className = 'status-disconnected';
                document.getElementById('ws-text').textContent = 'Disconnected';
                setTimeout(connectWebSocket, 3000);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
        }
        
        function handleWebSocketMessage(data) {
            if (data.type === 'analysis_updated' || data.type === 'analysis_created' || data.type === 'analysis_deleted') {
                loadAnalyses();
                loadStats();
            }
        }
        
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                document.getElementById('stats-container').innerHTML = `
                    <div class="stat-card">
                        <div class="number">${stats.analyses.total}</div>
                        <div class="label">Total Analyses</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.completed}</div>
                        <div class="label">Completed</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.in_progress}</div>
                        <div class="label">In Progress</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.failed}</div>
                        <div class="label">Failed</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.worktrees.count}</div>
                        <div class="label">Active Worktrees</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.worktrees.total_size_mb} MB</div>
                        <div class="label">Worktree Size</div>
                    </div>
                `;
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }
        
        async function loadAnalyses() {
            try {
                const response = await fetch('/api/analyses');
                const analyses = await response.json();
                
                if (analyses.length === 0) {
                    document.getElementById('analyses-list').innerHTML = `
                        <p style="text-align: center; color: #666; padding: 40px;">
                            No analyses yet. Use the CLI to create one:<br>
                            <code>ggdes analyze --feature &lt;name&gt; &lt;commits&gt;</code>
                        </p>
                    `;
                    return;
                }
                
                document.getElementById('analyses-list').innerHTML = analyses.map(a => `
                    <div class="analysis-item">
                        <div class="analysis-header">
                            <span class="analysis-name">${escapeHtml(a.name)}</span>
                            <span class="analysis-id">${a.id.substring(0, 8)}...</span>
                        </div>
                        <div style="color: #666; font-size: 0.9em; margin-bottom: 10px;">
                            <strong>Commits:</strong> ${escapeHtml(a.commit_range)}<br>
                            <strong>Created:</strong> ${new Date(a.created_at).toLocaleString()}
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${a.progress.percent}%"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.85em; color: #666;">
                            <span>${a.progress.completed}/${a.progress.total} stages</span>
                            <span>${Math.round(a.progress.percent)}%</span>
                        </div>
                        <div class="status-badges">
                            ${a.progress.completed > 0 ? `<span class="badge completed">${a.progress.completed} Complete</span>` : ''}
                            ${a.progress.failed > 0 ? `<span class="badge failed">${a.progress.failed} Failed</span>` : ''}
                            ${a.progress.pending > 0 ? `<span class="badge pending">${a.progress.pending} Pending</span>` : ''}
                        </div>
                        <div class="actions">
                            ${a.progress.pending > 0 ? `<button class="btn btn-primary" onclick="resumeAnalysis('${a.id}')">Resume</button>` : ''}
                            <button class="btn btn-secondary" onclick="viewDetails('${a.id}')">Details</button>
                            <button class="btn btn-danger" onclick="deleteAnalysis('${a.id}')">Delete</button>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Failed to load analyses:', error);
                document.getElementById('analyses-list').innerHTML = `
                    <p style="text-align: center; color: #721c24; padding: 40px;">
                        Failed to load analyses. Please try again.
                    </p>
                `;
            }
        }
        
        async function resumeAnalysis(id) {
            if (!confirm('Resume this analysis?')) return;
            
            try {
                const response = await fetch(`/api/analyses/${id}/resume`, {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('Analysis completed successfully!');
                } else {
                    alert('Analysis did not complete. Check logs for details.');
                }
                loadAnalyses();
            } catch (error) {
                alert('Failed to resume analysis: ' + error.message);
            }
        }
        
        async function deleteAnalysis(id) {
            if (!confirm('Delete this analysis? This cannot be undone.')) return;
            
            try {
                const response = await fetch(`/api/analyses/${id}/delete`, {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (result.deleted) {
                    loadAnalyses();
                    loadStats();
                }
            } catch (error) {
                alert('Failed to delete analysis: ' + error.message);
            }
        }
        
        function viewDetails(id) {
            window.open(`/api/analyses/${id}`, '_blank');
        }
        
        async function previewCleanup() {
            try {
                const response = await fetch('/api/worktrees/cleanup-preview?days=7');
                const preview = await response.json();
                
                const previewDiv = document.getElementById('cleanup-preview');
                
                if (preview.would_cleanup === 0) {
                    previewDiv.innerHTML = '<p style="color: #155724;">No old worktrees to clean up.</p>';
                } else {
                    previewDiv.innerHTML = `
                        <p style="color: #856404;">Would clean up ${preview.would_cleanup} worktree(s):</p>
                        <ul style="margin-left: 20px; color: #666;">
                            ${preview.worktrees.map(w => `<li>${w.analysis_id} (${w.age_days} days old)</li>`).join('')}
                        </ul>
                    `;
                }
                previewDiv.style.display = 'block';
            } catch (error) {
                alert('Failed to preview cleanup: ' + error.message);
            }
        }
        
        async function runCleanup() {
            if (!confirm('Clean up worktrees older than 7 days?')) return;
            
            try {
                const response = await fetch('/api/worktrees/cleanup?days=7', {
                    method: 'POST'
                });
                const result = await response.json();
                
                alert(`Cleaned up ${result.cleaned} worktree(s)`);
                loadStats();
                document.getElementById('cleanup-preview').style.display = 'none';
            } catch (error) {
                alert('Failed to cleanup: ' + error.message);
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Initialize
        connectWebSocket();
        loadStats();
        loadAnalyses();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
