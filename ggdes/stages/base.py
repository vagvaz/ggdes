"""Base class and result type for pipeline stages."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from rich.console import Console

from ggdes.config import GGDesConfig
from ggdes.kb import AnalysisMetadata, KnowledgeBaseManager


@dataclass
class StageResult:
    """Result of running a pipeline stage.

    Attributes:
        success: True if the stage completed successfully.
        error: Error message if the stage failed.
        skipped: True if the stage had nothing to do (not a failure).
    """
    success: bool = True
    error: str | None = None
    skipped: bool = False


class Stage(ABC):
    """Base class for pipeline stages.

    Each stage wraps a single step in the GGDes analysis pipeline.
    Stages receive all their dependencies as explicit parameters
    and write their outputs to the knowledge base.

    Subclasses must set ``name`` as a class variable and implement ``run()``.
    """

    name: str = ""

    @abstractmethod
    async def run(
        self,
        metadata: AnalysisMetadata,
        config: GGDesConfig,
        kb: KnowledgeBaseManager,
        console: Console,
        feedback: str | None = None,
    ) -> StageResult:
        """Execute this stage.

        Args:
            metadata: Analysis metadata (mutable — stages can update it).
            config: Global GGDes configuration.
            kb: Knowledge base manager for reading/writing artifacts.
            console: Rich console for progress output.
            feedback: Optional review feedback string from a prior run.

        Returns:
            StageResult indicating success, failure, or skip.
        """
        ...
