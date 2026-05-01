"""Feedback-related API routes."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ggdes.web.manager import get_kb

router = APIRouter()


@router.get("/api/analyses/{analysis_id}/feedback")  # type: ignore[untyped-decorator]
async def get_feedback(analysis_id: str) -> dict[str, str]:
    """Get section-level feedback for an analysis."""
    kb = get_kb()
    return kb.load_section_feedback(analysis_id)


@router.post("/api/analyses/{analysis_id}/feedback")  # type: ignore[untyped-decorator]
async def save_feedback(
    analysis_id: str,
    section_title: str = Query(...),
    feedback: str = Query(...),
) -> dict[str, Any]:
    """Save feedback for a specific section."""
    kb = get_kb()
    kb.save_section_feedback(analysis_id, section_title, feedback)
    return {"success": True, "section": section_title}


@router.post("/api/analyses/{analysis_id}/feedback/bulk")  # type: ignore[untyped-decorator]
async def save_feedback_bulk(
    analysis_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Save feedback for multiple sections at once."""
    kb = get_kb()
    count = 0
    for item in request.get("feedback_items", []):
        section = item.get("section", "")
        feedback_text = item.get("feedback", "")
        if section and feedback_text:
            kb.save_section_feedback(analysis_id, section, feedback_text)
            count += 1
    return {"success": True, "count": count}
