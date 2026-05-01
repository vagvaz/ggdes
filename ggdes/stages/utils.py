"""Shared utilities for pipeline stages."""

import json
from pathlib import Path
from typing import Any

from ggdes.config import GGDesConfig
from ggdes.kb import KnowledgeBaseManager


def get_summary_path(kb: KnowledgeBaseManager, analysis_id: str) -> Path:
    """Get the path to the change summary, preferring filtered over raw.

    Returns the ``change_filter`` summary if it exists (filtered output),
    otherwise falls back to the raw ``git_analysis`` summary.
    """
    filtered_path = (
        kb.get_analysis_path(analysis_id) / "change_filter" / "summary.json"
    )
    if filtered_path.exists():
        return filtered_path

    return (
        kb.get_analysis_path(analysis_id) / "git_analysis" / "summary.json"
    )


def get_changed_files_from_analysis(
    kb: KnowledgeBaseManager, analysis_id: str
) -> list[str]:
    """Get list of changed file paths from git analysis results."""
    analysis_path = get_summary_path(kb, analysis_id)

    if not analysis_path.exists():
        return []

    try:
        data = json.loads(analysis_path.read_text())
        files_changed = data.get("files_changed", [])
        return [f["path"] for f in files_changed if isinstance(f, dict) and "path" in f]
    except (json.JSONDecodeError, ValueError, OSError):
        return []


def get_changed_files_detailed(
    kb: KnowledgeBaseManager, analysis_id: str
) -> list[dict[str, Any]]:
    """Get detailed changed file info from git analysis results."""
    analysis_path = get_summary_path(kb, analysis_id)

    if not analysis_path.exists():
        return []

    try:
        data = json.loads(analysis_path.read_text())
        files_changed = data.get("files_changed", [])
        result = []
        for f in files_changed:
            if isinstance(f, dict):
                result.append(
                    {
                        "path": f.get("path", ""),
                        "change_type": f.get("change_type", "modified"),
                        "lines_added": f.get("lines_added", 0),
                        "lines_deleted": f.get("lines_deleted", 0),
                        "summary": f.get("summary", ""),
                        "relevant_line_ranges": f.get("relevant_line_ranges"),
                    }
                )
        return result
    except (json.JSONDecodeError, ValueError, OSError):
        return []


def load_ast_elements(
    kb: KnowledgeBaseManager, analysis_id: str, variant: str = "head"
) -> dict[str, list[Any]]:
    """Load AST elements from knowledge base.

    Args:
        kb: Knowledge base manager.
        analysis_id: Analysis identifier.
        variant: ``"head"`` or ``"base"``.

    Returns:
        Dict mapping file paths to lists of code element dicts.
    """
    ast_elements: dict[str, list[Any]] = {}
    ast_dir = kb.get_analysis_path(analysis_id) / f"ast_{variant}"

    if ast_dir.exists():
        for json_file in ast_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text())
                elements = data.get("elements", [])
                if elements:
                    file_path = data.get("file_path", json_file.stem)
                    ast_elements[file_path] = elements
            except (json.JSONDecodeError, ValueError):
                continue

    return ast_elements


def build_tool_executor(
    config: GGDesConfig,
    kb: KnowledgeBaseManager,
    analysis_id: str,
    repo_path: Path,
    metadata: Any,
) -> Any:
    """Build a ToolExecutor for grounded LLM calls.

    Returns ``None`` if required data is unavailable.
    """
    from ggdes.tools import ToolExecutor

    changed_files = get_changed_files_detailed(kb, analysis_id)
    ast_elements = load_ast_elements(kb, analysis_id, "head")
    commit_range = metadata.commit_range
    focus_commits = getattr(metadata, "focus_commits", None)

    return ToolExecutor(
        repo_path=repo_path,
        changed_files=changed_files,
        ast_elements=ast_elements,
        commit_range=commit_range,
        focus_commits=focus_commits,
    )
