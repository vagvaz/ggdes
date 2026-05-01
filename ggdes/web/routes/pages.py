"""HTML page-serving routes."""

import json
import contextlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ggdes.web.manager import get_kb
from ggdes.web.templates import INDEX_HTML, FEEDBACK_HTML, DETAIL_HTML

router = APIRouter()


@router.get("/", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def root() -> HTMLResponse:
    """Serve the main web interface."""
    return HTMLResponse(content=INDEX_HTML, status_code=200)


@router.get("/feedback/{analysis_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def feedback_page(analysis_id: str) -> HTMLResponse:
    """Serve the feedback interface for a specific analysis."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    plan = kb.load_document_plan(analysis_id)
    existing_feedback = kb.load_section_feedback(analysis_id)

    return HTMLResponse(
        content=FEEDBACK_HTML.format(
            analysis_id=analysis_id,
            analysis_name=metadata.name,
            plan_json=json.dumps(plan or {}),
            feedback_json=json.dumps(existing_feedback or {}),
        ),
        status_code=200,
    )


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def analysis_detail_page(analysis_id: str) -> HTMLResponse:
    """Serve the analysis detail page."""
    kb = get_kb()
    metadata = kb.load_metadata(analysis_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Build stage info
    stages = []
    for name, stage in metadata.stages.items():
        stages.append(
            {
                "name": name,
                "status": stage.status.value,
                "started_at": stage.started_at.isoformat()
                if stage.started_at
                else None,
                "completed_at": stage.completed_at.isoformat()
                if stage.completed_at
                else None,
                "error": stage.error_message,
            }
        )

    # Load git summary
    git_summary = None
    git_summary_path = (
        kb.get_analysis_path(analysis_id) / "git_analysis" / "summary.json"
    )
    if git_summary_path.exists():
        with contextlib.suppress(Exception):
            git_summary = json.loads(git_summary_path.read_text())

    # Load facts count
    facts_dir = kb.get_analysis_path(analysis_id) / "technical_facts"
    facts_count = len(list(facts_dir.glob("*.json"))) if facts_dir.exists() else 0

    # Load plans
    plans_dir = kb.get_analysis_path(analysis_id) / "plans"
    plans = []
    if plans_dir.exists():
        for plan_file in plans_dir.glob("*.json"):
            with contextlib.suppress(Exception):
                plan_data = json.loads(plan_file.read_text())
                plans.append(
                    {
                        "format": plan_file.stem,
                        "sections": len(plan_data.get("sections", [])),
                        "diagrams": len(plan_data.get("diagrams", [])),
                    }
                )

    # Load documents
    documents = []
    output_dir = kb.get_analysis_path(analysis_id) / "outputs"
    if output_dir.exists():
        for doc_file in output_dir.iterdir():
            if doc_file.is_file() and doc_file.suffix in {
                ".md",
                ".docx",
                ".pdf",
                ".pptx",
            }:
                documents.append(
                    {
                        "name": doc_file.name,
                        "format": doc_file.suffix[1:],
                        "size": doc_file.stat().st_size,
                    }
                )

    return HTMLResponse(
        content=DETAIL_HTML.format(
            analysis_id=analysis_id,
            analysis_name=metadata.name,
            repo_path=metadata.repo_path,
            commit_range=metadata.commit_range or "",
            created_at=metadata.created_at.isoformat(),
            target_formats=", ".join(metadata.target_formats or ["markdown"]),
            stages_json=json.dumps(stages),
            git_summary_json=json.dumps(git_summary or {}),
            facts_count=facts_count,
            plans_json=json.dumps(plans),
            documents_json=json.dumps(documents),
        ),
        status_code=200,
    )
