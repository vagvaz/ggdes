"""Worktree management and stats routes."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from ggdes.kb import StageStatus
from ggdes.web.manager import get_config, get_kb
from ggdes.worktree import WorktreeManager

router = APIRouter()


@router.get("/api/stats")
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


@router.get("/api/worktrees/cleanup-preview")
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


@router.post("/api/worktrees/cleanup")
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
