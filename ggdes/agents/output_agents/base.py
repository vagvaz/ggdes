"""Base class for output agents."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


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
        self.user_context: Optional[dict] = None

    def _load_user_context(self) -> None:
        """Load user context from document plan or metadata."""
        try:
            from ggdes.agents.coordinator import Coordinator
            from ggdes.config import get_kb_path

            kb_path = get_kb_path(self.config, self.analysis_id)

            # Try to find the plan for this agent's format
            format_name = getattr(self, "format_name", None)
            if format_name:
                plan = Coordinator.load_plan(kb_path, format_name)
                if plan and plan.user_context:
                    self.user_context = plan.user_context
                    return

            # Fallback: try to load from metadata
            from ggdes.kb import KnowledgeBaseManager

            kb_manager = KnowledgeBaseManager(self.config)
            metadata = kb_manager.load_metadata(self.analysis_id)
            if metadata and metadata.user_context:
                self.user_context = metadata.user_context

        except Exception as e:
            console.print(f"  [dim]Could not load user context: {e}[/dim]")
            self.user_context = None

    def _load_skill(self, skill_name: str) -> str:
        """Load skill documentation from skills directory.

        Args:
            skill_name: Name of the skill (e.g., 'docx', 'pdf', 'pptx')

        Returns:
            Content of the skill's SKILL.md file
        """
        from ggdes.agents.skill_utils import load_skill

        content = load_skill(skill_name)
        if content:
            return content

        raise FileNotFoundError(f"Could not find skill '{skill_name}'")

    @abstractmethod
    def generate(self) -> Path:
        """Generate output document.

        Returns:
            Path to generated file
        """
        pass
