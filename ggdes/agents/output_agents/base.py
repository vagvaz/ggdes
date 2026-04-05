"""Base class for output agents."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class OutputAgent(ABC):
    """Abstract base class for document output agents."""

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize output agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id

    def _load_skill(self, skill_name: str) -> str:
        """Load skill documentation from skills directory.

        Args:
            skill_name: Name of the skill (e.g., 'docx', 'pdf', 'pptx')

        Returns:
            Content of the skill's SKILL.md file
        """
        # Find skills directory - check multiple locations
        possible_paths = [
            Path(__file__).parent.parent.parent / "skills" / skill_name / "SKILL.md",
            Path(__file__).parent.parent.parent.parent
            / "skills"
            / skill_name
            / "SKILL.md",
            Path.cwd() / "ggdes" / "skills" / skill_name / "SKILL.md",
            Path.cwd() / "skills" / skill_name / "SKILL.md",
        ]

        for skill_path in possible_paths:
            if skill_path.exists():
                return skill_path.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Could not find skill '{skill_name}' at any of: {[str(p) for p in possible_paths]}"
        )

    @abstractmethod
    def generate(self) -> Path:
        """Generate output document.

        Returns:
            Path to generated file
        """
        pass
