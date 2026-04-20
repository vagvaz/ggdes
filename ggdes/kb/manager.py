"""Knowledge base management for analysis state and data."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ggdes.config import GGDesConfig, get_kb_path
from ggdes.schemas import StoragePolicy


class StageStatus(str, Enum):
    """Status of a stage in the analysis pipeline."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageInfo(BaseModel):
    """Information about a stage in the analysis pipeline."""

    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_path: str | None = None
    error_message: str | None = None


class WorktreeInfo(BaseModel):
    """Information about worktrees for an analysis."""

    base: str
    head: str
    created_at: datetime = Field(default_factory=datetime.now)
    cleanup_policy: str = "on_completion"  # or "manual", "immediate"


class DocumentInfo(BaseModel):
    """Information about a generated document."""

    format: str
    path: str | None = None
    generated_at: datetime | None = None


class AnalysisMetadata(BaseModel):
    """Metadata for an analysis stored in knowledge base."""

    # Analysis identification
    id: str
    name: str
    repo_path: str
    commit_range: str
    focus_commits: list[str] | None = None  # For non-contiguous analysis
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Prompt version tracking
    prompt_version: str = "current"

    # Target output formats for this analysis
    target_formats: list[str] = Field(default_factory=list)

    # Conversation storage policy
    storage_policy: StoragePolicy = StoragePolicy.SUMMARY

    # User-provided context for all agents
    user_context: dict[str, Any] | None = None

    # Feature description for semantic change filtering
    feature_description: str | None = None

    # Whether to disable semantic filtering
    no_filter: bool = False

    # Worktree information
    worktrees: WorktreeInfo | None = None

    # Stage tracking
    stages: dict[str, StageInfo] = Field(default_factory=dict)

    # Generated documents tracking
    documents: list[DocumentInfo] = Field(default_factory=list)

    # Render markdown to PNG images
    render_png: bool = False

    @field_validator("updated_at", mode="before")
    @classmethod
    def update_timestamp(cls, v: datetime, info: Any) -> datetime:
        """Auto-update timestamp on modification."""
        return datetime.now()

    def get_stage(self, stage_name: str) -> StageInfo:
        """Get stage info, creating if it doesn't exist."""
        if stage_name not in self.stages:
            self.stages[stage_name] = StageInfo()
        return self.stages[stage_name]

    def start_stage(self, stage_name: str) -> None:
        """Mark a stage as started."""
        stage = self.get_stage(stage_name)
        stage.status = StageStatus.IN_PROGRESS
        stage.started_at = datetime.now()
        stage.completed_at = None
        stage.error_message = None
        self.updated_at = datetime.now()

    def complete_stage(self, stage_name: str, output_path: str | None = None) -> None:
        """Mark a stage as completed."""
        stage = self.get_stage(stage_name)
        stage.status = StageStatus.COMPLETED
        stage.completed_at = datetime.now()
        if output_path:
            stage.output_path = output_path
        self.updated_at = datetime.now()

    def fail_stage(self, stage_name: str, error_message: str) -> None:
        """Mark a stage as failed."""
        stage = self.get_stage(stage_name)
        stage.status = StageStatus.FAILED
        stage.completed_at = datetime.now()
        stage.error_message = error_message
        self.updated_at = datetime.now()

    def reset_stage(self, stage_name: str) -> None:
        """Reset a stage to pending status (for retry)."""
        stage = self.get_stage(stage_name)
        stage.status = StageStatus.PENDING
        stage.started_at = None
        stage.completed_at = None
        stage.error_message = None
        self.updated_at = datetime.now()

    def skip_stage(self, stage_name: str) -> None:
        """Mark a stage as skipped."""
        stage = self.get_stage(stage_name)
        stage.status = StageStatus.SKIPPED
        stage.completed_at = datetime.now()
        self.updated_at = datetime.now()

    def is_stage_completed(self, stage_name: str) -> bool:
        """Check if a stage is completed."""
        if stage_name not in self.stages:
            return False
        return self.stages[stage_name].status == StageStatus.COMPLETED

    def get_completed_stages(self) -> list[str]:
        """Get list of completed stage names."""
        return [
            name
            for name, stage in self.stages.items()
            if stage.status == StageStatus.COMPLETED
        ]

    def get_pending_stages(self) -> list[str]:
        """Get list of pending stage names."""
        return [
            name
            for name, stage in self.stages.items()
            if stage.status in (StageStatus.PENDING, StageStatus.IN_PROGRESS)
        ]


class KnowledgeBaseManager:
    """Manage the knowledge base for analyses."""

    # Standard stage names
    STAGE_WORKTREE_SETUP = "worktree_setup"
    STAGE_GIT_ANALYSIS = "git_analysis"
    STAGE_CHANGE_FILTER = "change_filter"
    STAGE_AST_PARSING_BASE = "ast_parsing_base"
    STAGE_AST_PARSING_HEAD = "ast_parsing_head"
    STAGE_SEMANTIC_DIFF = "semantic_diff"
    STAGE_TECHNICAL_AUTHOR = "technical_author"
    STAGE_COORDINATOR_PLAN = "coordinator_plan"
    STAGE_OUTPUT_GENERATION = "output_generation"

    ALL_STAGES = [
        STAGE_WORKTREE_SETUP,
        STAGE_GIT_ANALYSIS,
        STAGE_CHANGE_FILTER,
        STAGE_AST_PARSING_BASE,
        STAGE_AST_PARSING_HEAD,
        STAGE_SEMANTIC_DIFF,
        STAGE_TECHNICAL_AUTHOR,
        STAGE_COORDINATOR_PLAN,
        STAGE_OUTPUT_GENERATION,
    ]

    def __init__(self, config: GGDesConfig):
        """Initialize KB manager.

        Args:
            config: GGDes configuration
        """
        self.config = config
        self.kb_base = Path(config.paths.knowledge_base).expanduser()

    def create_analysis(
        self,
        analysis_id: str,
        name: str,
        repo_path: Path,
        commit_range: str,
        focus_commits: list[str] | None = None,
        prompt_version: str = "current",
        target_formats: list[str] | None = None,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
    ) -> AnalysisMetadata:
        """Create a new analysis in the knowledge base.

        Args:
            analysis_id: Unique identifier for the analysis
            name: User-provided name for the analysis
            repo_path: Path to the repository
            commit_range: Git commit range (e.g., "abc123..def456")
            focus_commits: Optional list of focus commits for non-contiguous
            prompt_version: Version of prompts to use
            target_formats: List of output formats to generate (e.g., ["markdown", "docx"])
            storage_policy: Conversation storage level

        Returns:
            AnalysisMetadata for the new analysis
        """
        analysis_path = get_kb_path(self.config, analysis_id)
        analysis_path.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (analysis_path / "git_analysis").mkdir(exist_ok=True)
        (analysis_path / "ast_base").mkdir(exist_ok=True)
        (analysis_path / "ast_head").mkdir(exist_ok=True)
        (analysis_path / "semantic_descriptions").mkdir(exist_ok=True)
        (analysis_path / "technical_facts").mkdir(exist_ok=True)
        (analysis_path / "plans").mkdir(exist_ok=True)
        (analysis_path / "diagrams").mkdir(exist_ok=True)

        metadata = AnalysisMetadata(
            id=analysis_id,
            name=name,
            repo_path=str(Path(repo_path).resolve()),
            commit_range=commit_range,
            focus_commits=focus_commits,
            prompt_version=prompt_version,
            target_formats=target_formats
            or ["markdown"],  # Default to markdown if not specified
            storage_policy=storage_policy,
        )

        # Initialize all stages as pending
        for stage in self.ALL_STAGES:
            metadata.stages[stage] = StageInfo(status=StageStatus.PENDING)

        self._save_metadata(analysis_id, metadata)
        return metadata

    def load_metadata(self, analysis_id: str) -> AnalysisMetadata | None:
        """Load metadata for an analysis.

        Args:
            analysis_id: Analysis identifier

        Returns:
            AnalysisMetadata if exists, None otherwise
        """
        metadata_path = self._get_metadata_path(analysis_id)
        if not metadata_path.exists():
            return None

        with open(metadata_path) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError:
                return None

        if not data:
            return None

        return AnalysisMetadata(**data)

    def save_metadata(self, analysis_id: str, metadata: AnalysisMetadata) -> None:
        """Save metadata for an analysis.

        Args:
            analysis_id: Analysis identifier
            metadata: Metadata to save
        """
        self._save_metadata(analysis_id, metadata)

    def _save_metadata(self, analysis_id: str, metadata: AnalysisMetadata) -> None:
        """Internal save method."""
        metadata_path = self._get_metadata_path(analysis_id)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and handle enums
        data = metadata.model_dump()

        # Convert StageStatus enum to string
        if "stages" in data:
            for _stage_name, stage_data in data["stages"].items():
                if "status" in stage_data and hasattr(stage_data["status"], "value"):
                    stage_data["status"] = stage_data["status"].value

        # Convert StoragePolicy enum to string
        if "storage_policy" in data and hasattr(data["storage_policy"], "value"):
            data["storage_policy"] = data["storage_policy"].value

        with open(metadata_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _get_metadata_path(self, analysis_id: str) -> Path:
        """Get path to metadata file for an analysis."""
        return get_kb_path(self.config, analysis_id) / "metadata.yaml"

    def get_analysis_path(self, analysis_id: str) -> Path:
        """Get base path for an analysis."""
        return get_kb_path(self.config, analysis_id)

    def list_analyses(self) -> list[tuple[str, AnalysisMetadata]]:
        """List all analyses in the knowledge base.

        Returns:
            List of (analysis_id, metadata) tuples
        """
        analyses: list[tuple[str, AnalysisMetadata]] = []
        kb_path = self.kb_base / "analyses"

        if not kb_path.exists():
            return analyses

        for analysis_dir in kb_path.iterdir():
            if analysis_dir.is_dir():
                metadata = self.load_metadata(analysis_dir.name)
                if metadata:
                    analyses.append((analysis_dir.name, metadata))

        return analyses

    def delete_analysis(self, analysis_id: str) -> bool:
        """Delete an analysis from the knowledge base.

        Args:
            analysis_id: Analysis identifier

        Returns:
            True if deleted, False if not found
        """
        import shutil

        analysis_path = get_kb_path(self.config, analysis_id)
        if not analysis_path.exists():
            return False

        shutil.rmtree(analysis_path)
        return True

    def analysis_exists(self, analysis_id: str) -> bool:
        """Check if an analysis exists.

        Args:
            analysis_id: Analysis identifier

        Returns:
            True if exists, False otherwise
        """
        return self._get_metadata_path(analysis_id).exists()

    def can_resume(
        self, analysis_id: str, retry_failed: bool = False
    ) -> tuple[bool, str | None]:
        """Check if an analysis can be resumed.

        Args:
            analysis_id: Analysis identifier
            retry_failed: If True, allow retrying failed stages

        Returns:
            Tuple of (can_resume, reason_if_not)
        """
        metadata = self.load_metadata(analysis_id)
        if not metadata:
            return False, "Analysis not found"

        if not retry_failed:
            # Check if any stage failed
            for stage_name, stage in metadata.stages.items():
                if stage.status == StageStatus.FAILED:
                    return (
                        False,
                        f"Stage '{stage_name}' failed (use --retry-failed to retry)",
                    )

        # Completed analyses can be resumed (e.g., to add new formats or re-run stages)
        # The caller decides whether to proceed based on what needs to be done
        return True, None

    def reset_failed_stages(self, analysis_id: str) -> list[str]:
        """Reset all failed stages to pending.

        Args:
            analysis_id: Analysis identifier

        Returns:
            List of stage names that were reset
        """
        metadata = self.load_metadata(analysis_id)
        if not metadata:
            return []

        reset_stages = []
        for stage_name, stage in metadata.stages.items():
            if stage.status == StageStatus.FAILED:
                metadata.reset_stage(stage_name)
                reset_stages.append(stage_name)

        if reset_stages:
            self.save_metadata(analysis_id, metadata)

        return reset_stages

    def save_review_session(self, analysis_id: str, review_data: dict[str, Any]) -> None:
        """Save review session data to KB.

        Args:
            analysis_id: Analysis identifier
            review_data: Serialized ReviewSession data
        """
        review_path = get_kb_path(self.config, analysis_id) / "review_session.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        review_path.write_text(json.dumps(review_data, indent=2, default=str))

    def load_review_session(self, analysis_id: str) -> dict[str, Any] | None:
        """Load review session data from KB.

        Args:
            analysis_id: Analysis identifier

        Returns:
            Review session data or None if not found
        """
        import json
        review_path = get_kb_path(self.config, analysis_id) / "review_session.json"
        if not review_path.exists():
            return None
        try:
            return json.loads(review_path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None
