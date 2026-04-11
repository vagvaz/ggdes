"""Skill loading utilities for agents."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_skill(skill_name: str, repo_path: Path | None = None) -> str | None:
    """Load skill documentation from skills directory.

    Args:
        skill_name: Name of the skill (e.g., 'doc-coauthoring', 'python-expert', 'cpp-expert', 'docx', 'pdf', 'pptx')
        repo_path: Optional repository path for context

    Returns:
        Content of the skill's SKILL.md file, or None if not found
    """
    # Find skills directory - check multiple locations
    possible_paths = [
        Path(__file__).parent.parent / "skills" / skill_name / "SKILL.md",
        Path(__file__).parent.parent.parent / "skills" / skill_name / "SKILL.md",
        Path.cwd() / "ggdes" / "skills" / skill_name / "SKILL.md",
        Path.cwd() / "skills" / skill_name / "SKILL.md",
    ]

    for skill_path in possible_paths:
        if skill_path.exists():
            try:
                content = skill_path.read_text(encoding="utf-8")
                logger.debug(f"Loaded skill '{skill_name}' from {skill_path}")
                return content
            except Exception as e:
                logger.warning(
                    f"Failed to read skill '{skill_name}' from {skill_path}: {e}"
                )
                continue

    logger.warning(
        f"Skill '{skill_name}' not found at any location. Skipping skill loading."
    )
    return None


def detect_primary_language(repo_path: Path) -> str | None:
    """Detect the primary programming language in a repository.

    Analyzes file extensions to determine the dominant language.

    Args:
        repo_path: Path to the repository

    Returns:
        Language identifier ('python', 'cpp', etc.) or None if can't determine
    """
    if not repo_path.exists():
        return None

    # Count files by extension
    extension_counts: dict[str, int] = {}

    for file_path in repo_path.rglob("*"):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext:
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

    # Language mapping
    language_extensions = {
        "python": [".py"],
        "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h", ".hh", ".hxx"],
        "javascript": [".js", ".jsx", ".mjs"],
        "typescript": [".ts", ".tsx"],
        "java": [".java"],
        "go": [".go"],
        "rust": [".rs"],
        "c": [".c", ".h"],
    }

    # Score each language
    language_scores = {}
    for lang, extensions in language_extensions.items():
        score = sum(extension_counts.get(ext, 0) for ext in extensions)
        if score > 0:
            language_scores[lang] = score

    if not language_scores:
        return None

    # Return the language with highest count
    primary_lang = max(language_scores.items(), key=lambda x: x[1])[0]
    logger.debug(
        f"Detected primary language: {primary_lang} (counts: {language_scores})"
    )
    return primary_lang


def get_expert_skill_for_language(language: str) -> str | None:
    """Get the expert skill name for a programming language.

    Args:
        language: Language identifier (e.g., 'python', 'cpp')

    Returns:
        Skill name (e.g., 'python-expert', 'cpp-expert') or None
    """
    skill_map = {
        "python": "python-expert",
        "cpp": "cpp-expert",
        "c": "cpp-expert",  # C uses C++ expert skill
    }

    return skill_map.get(language)


def build_user_context_guidance(user_context: dict[str, Any] | None) -> str:
    """Build guidance text from user context for LLM prompts.

    This is a shared utility used by GitAnalyzer, TechnicalAuthor,
    Coordinator, and output agents to format user context into
    a consistent guidance string.

    Args:
        user_context: Dictionary with keys like 'focus_areas', 'audience',
                      'purpose', 'detail_level', 'additional_context'

    Returns:
        Formatted guidance string, or empty string if no context
    """
    if not user_context:
        return ""

    guidance_parts = []

    if "focus_areas" in user_context:
        guidance_parts.append(f"Focus Areas: {user_context['focus_areas']}")

    if "audience" in user_context:
        guidance_parts.append(f"Target Audience: {user_context['audience']}")

    if "purpose" in user_context:
        purposes = user_context["purpose"]
        if isinstance(purposes, list):
            guidance_parts.append(f"Document Purpose: {', '.join(purposes)}")
        else:
            guidance_parts.append(f"Document Purpose: {purposes}")

    if "detail_level" in user_context:
        guidance_parts.append(f"Detail Level: {user_context['detail_level']}")

    if "additional_context" in user_context:
        guidance_parts.append(
            f"Additional Context: {user_context['additional_context']}"
        )

    return "\n".join(guidance_parts)
