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

    @abstractmethod
    def generate(self) -> Path:
        """Generate output document.

        Returns:
            Path to generated file
        """
        pass
