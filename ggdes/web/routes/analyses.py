"""Analysis-related API routes."""

import json
import contextlib
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ggdes.config import GGDesConfig, load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.pipeline import AnalysisPipeline
from ggdes.worktree import WorktreeManager
from ggdes.web.manager import get_config, get_kb, manager

router = APIRouter()


class ResumeRequest(BaseModel):
    """Request body for resuming an analysis."""

    formats: list[str] | None = None


class RegenerateRequest(BaseModel):
    """Request body for feedback-driven regeneration."""

    section_feedback: dict[str, str] = {}  # section_title -> feedback text
    stage_feedback: str | None = None
    affects_structure: bool = False
    summary: str = ""


class SetRevisionRequest(BaseModel):
    """Request body for setting the current revision."""

    revision_id: str


@router.get("/api/analyses")  # type: ignore[untyped-decorator]
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


@router.get("/api/analyses/{analysis_id}")  # type: ignore[untyped-decorator]
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
        with contextlib.suppress(Exception):
            git_summary = json.loads(git_summary_path.read_text())

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


@router.post("/api/analyses/{analysis_id}/resume")  # type: ignore[untyped-decorator]
async def resume_analysis(
    analysis_id: str, body: ResumeRequest | None = None
) -> dict[str, Any]:
    """Resume an analysis. Optionally accepts new formats to regenerate documents."""
    config = get_config()
    kb = get_kb()

    metadata = kb.load_metadata(analysis_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    try:
        # If formats are specified, update metadata and reset relevant stages
        if body and body.formats is not None:
            old_formats = set(metadata.target_formats or ["markdown"])
            new_formats = set(body.formats)
            metadata.target_formats = body.formats
            formats_changed = old_formats != new_formats

            for stage_name in metadata.stages:
                stage = metadata.stages[stage_name]
                should_reset = stage_name == "output_generation" or (
                    formats_changed and stage_name == "coordinator_plan"
                )
                if should_reset and stage.status in (
                    StageStatus.COMPLETED,
                    StageStatus.FAILED,
                ):
                    stage.status = StageStatus.PENDING
                    stage.output_path = None
                    stage.error_message = None
                    stage.completed_at = None

            kb.save_metadata(analysis_id, metadata)

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


@router.get("/api/analyses/{analysis_id}/revisions")  # type: ignore[untyped-decorator]
async def list_revisions(analysis_id: str) -> dict[str, Any]:
    """List all revisions for an analysis."""
    config = get_config()
    try:
        from ggdes.feedback import FeedbackManager

        mgr = FeedbackManager(config, analysis_id)
        revisions = []
        for rev in mgr.list_revisions():
            revisions.append(
                {
                    "id": rev.revision_id,
                    "parent": rev.parent,
                    "created_at": rev.created_at.isoformat(),
                    "summary": rev.feedback_summary,
                    "outputs": {fmt: str(p) for fmt, p in rev.outputs.items()},
                }
            )
        kb = get_kb()
        metadata = kb.load_metadata(analysis_id)
        current = getattr(metadata, "current_revision", None) if metadata else None
        return {"revisions": revisions, "current": current}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/analyses/{analysis_id}/regenerate")  # type: ignore[untyped-decorator]
async def regenerate_from_feedback(
    analysis_id: str, body: RegenerateRequest
) -> dict[str, Any]:
    """Save feedback and regenerate documents."""
    config = get_config()
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    try:
        # Save section feedback to KB for agent consumption
        for section_title, fb_text in body.section_feedback.items():
            if fb_text.strip():
                kb.save_section_feedback(analysis_id, section_title, fb_text)

        # Use FeedbackManager for the regeneration lifecycle
        from ggdes.feedback import FeedbackBatch, FeedbackManager, SectionFeedback

        mgr = FeedbackManager(config, analysis_id)
        batch = FeedbackBatch(
            analysis_id=analysis_id,
            section_feedback={
                k: SectionFeedback(text=v, action="refine")
                for k, v in body.section_feedback.items()
                if v.strip()
            },
            stage_feedback=body.stage_feedback,
            affects_structure=body.affects_structure,
        )
        rev_id = mgr.regenerate(batch, summary=body.summary)

        # Broadcast update
        await manager.broadcast(
            {
                "type": "analysis_updated",
                "analysis_id": analysis_id,
                "status": "completed" if rev_id else "incomplete",
            }
        )

        return {
            "success": rev_id is not None,
            "analysis_id": analysis_id,
            "revision_id": rev_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/api/analyses/{analysis_id}/revisions/current")  # type: ignore[untyped-decorator]
async def set_current_revision(
    analysis_id: str, body: SetRevisionRequest
) -> dict[str, Any]:
    """Set the current revision (does NOT regenerate)."""
    config = get_config()
    try:
        from ggdes.feedback import FeedbackManager

        mgr = FeedbackManager(config, analysis_id)
        success = mgr.set_current(body.revision_id)
        return {
            "success": success,
            "analysis_id": analysis_id,
            "revision_id": body.revision_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/analyses/{analysis_id}/delete")  # type: ignore[untyped-decorator]
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


@router.post("/api/analyses")  # type: ignore[untyped-decorator]
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
        kb.create_analysis(
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


@router.get("/api/analyses/{analysis_id}/documents")  # type: ignore[untyped-decorator]
async def get_documents(analysis_id: str) -> list[dict[str, Any]]:
    """Get list of generated documents for an analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    documents = []

    # Look for generated documents in the output directory
    from ggdes.config import get_output_path

    output_base = get_output_path(get_config(), analysis_id)
    if output_base.exists():
        for fmt in metadata.target_formats or ["markdown"]:
            fmt_dir = output_base / fmt
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


@router.get("/api/analyses/{analysis_id}/documents/{format}/download")  # type: ignore[untyped-decorator]
async def download_document(analysis_id: str, format: str) -> FileResponse:
    """Download a generated document."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Find the document in the output directory
    from ggdes.config import get_output_path

    output_base = get_output_path(get_config(), analysis_id) / format
    if not output_base.exists():
        raise HTTPException(status_code=404, detail="Format not found")

    for doc_file in output_base.glob(f"*{analysis_id}*"):
        if doc_file.is_file():
            return FileResponse(
                path=doc_file,
                filename=doc_file.name,
                media_type="application/octet-stream",
            )

    raise HTTPException(status_code=404, detail="Document not found")


@router.get("/api/analyses/{analysis_id}/diagrams")  # type: ignore[untyped-decorator]
async def get_diagrams(analysis_id: str) -> list[dict[str, Any]]:
    """Get list of diagrams for an analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    diagrams = []
    from ggdes.config import get_output_path

    diagrams_dir = get_output_path(get_config(), analysis_id) / "diagrams"

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


@router.get("/api/analyses/{analysis_id}/plan")  # type: ignore[untyped-decorator]
async def get_document_plan(analysis_id: str) -> dict[str, Any]:
    """Get document plan with sections for an analysis."""
    kb = get_kb()
    plan = kb.load_document_plan(analysis_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get("/api/analyses/{analysis_id}/stage-preview/{stage_name}")  # type: ignore[untyped-decorator]
async def get_stage_preview(analysis_id: str, stage_name: str) -> dict[str, Any]:
    """Get a preview of a stage's output for review."""
    from ggdes.review.reviewer import StageReviewer

    config = get_config()
    reviewer = StageReviewer(config, analysis_id)
    preview = reviewer.generate_preview(stage_name)
    if not preview:
        raise HTTPException(
            status_code=404, detail=f"No preview available for stage: {stage_name}"
        )
    return {
        "stage_name": preview.stage_name,
        "display_name": preview.display_name,
        "summary": preview.summary,
        "item_count": preview.item_count,
        "key_items": preview.key_items,
    }


@router.get("/api/analyses/{analysis_id}/outputs")  # type: ignore[untyped-decorator]
async def list_outputs(analysis_id: str) -> dict[str, Any]:
    """List all output files for an analysis."""
    kb = get_kb()
    analysis_path = kb.get_analysis_path(analysis_id)
    if not analysis_path.exists():
        return {"files": []}

    files: list[dict[str, Any]] = []
    for f in analysis_path.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".md", ".txt", ".yaml", ".yml"):
            rel = f.relative_to(analysis_path)
            files.append(
                {
                    "path": str(f),
                    "relative": str(rel),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                }
            )

    return {"files": sorted(files, key=lambda x: x["relative"])}


@router.get("/api/analyses/{analysis_id}/outputs/content")  # type: ignore[untyped-decorator]
async def get_output_content(
    analysis_id: str, path: str = Query(...)
) -> dict[str, Any]:
    """Get content of a specific output file."""
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        text = file_path.read_text()
        if file_path.suffix == ".json":
            parsed = json.loads(text)
            text = json.dumps(parsed, indent=2)
        return {"content": text, "name": file_path.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
