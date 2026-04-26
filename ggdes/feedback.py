"""Feedback and revision management for GGDes.

Provides a unified FeedbackManager that owns the feedback lifecycle:
collect feedback → estimate scope → save → regenerate → version outputs.
Each regeneration creates a numbered revision (v1, v2, ...) with its own
feedback snapshot and output files. Previous revisions are never deleted.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from rich.console import Console

from ggdes.config import GGDesConfig, get_kb_path
from ggdes.kb import KnowledgeBaseManager, StageStatus

console = Console()


@dataclass
class SectionFeedback:
    """Feedback for a single document section."""

    text: str
    action: Literal["refine", "rewrite", "keep"] = "refine"


@dataclass
class FeedbackBatch:
    """Unified feedback payload — merges per-section and stage-level feedback."""

    analysis_id: str
    section_feedback: dict[str, SectionFeedback] = field(default_factory=dict)
    stage_feedback: str | None = None
    affects_structure: bool = False
    parent_revision: str | None = None


@dataclass
class Revision:
    """A numbered document revision produced by one regeneration."""

    revision_id: str
    parent: str | None
    created_at: datetime
    feedback_summary: str
    feedback_batch: FeedbackBatch
    outputs: dict[str, Path]


REVISION_INDEX_FILE = "revision_index.json"
REVISIONS_DIR = "revisions"


class FeedbackManager:
    """Unified feedback lifecycle: collect → estimate → regenerate → version.

    Each regeneration creates a new Revision in ``revisions/v<N>/`` under the
    KB directory.  Output files land in ``~/ggdes-output/<analysis_id>/v<N>/``.
    Previous revisions and their output files are never deleted.
    """

    def __init__(self, config: GGDesConfig, analysis_id: str):
        self.config = config
        self.analysis_id = analysis_id
        self.kb_path = get_kb_path(config, analysis_id)
        self.kb_manager = KnowledgeBaseManager(config)

    # ── paths ──────────────────────────────────────────────────────────

    def _revisions_dir(self) -> Path:
        return self.kb_path / REVISIONS_DIR

    def _revision_dir(self, rev: str) -> Path:
        return self._revisions_dir() / rev

    def _index_path(self) -> Path:
        return self._revisions_dir() / REVISION_INDEX_FILE

    def _get_output_base(self) -> Path:
        from ggdes.config import get_output_path
        return get_output_path(self.config, self.analysis_id)

    # ── index ops ──────────────────────────────────────────────────────

    def _load_index(self) -> dict[str, Any]:
        path = self._index_path()
        if path.exists():
            try:
                result: dict[str, Any] = json.loads(path.read_text())
                return result
            except (json.JSONDecodeError, OSError):
                pass
        return {"current": None, "revisions": []}

    def _save_index(self, index: dict[str, Any]) -> None:
        self._index_path().parent.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(index, indent=2, default=str))

    def _next_revision_id(self, index: dict[str, Any]) -> str:
        existing = index.get("revisions", [])
        max_num = 0
        for rev in existing:
            rid = rev.get("id", "")
            if rid.startswith("v") and rid[1:].isdigit():
                max_num = max(max_num, int(rid[1:]))
        return f"v{max_num + 1}"

    # ── public API ─────────────────────────────────────────────────────

    def collect(self) -> FeedbackBatch:
        """Load feedback from the latest revision for editing.

        Returns an empty batch if no prior feedback exists.
        """
        index = self._load_index()
        current = index.get("current")
        if current:
            batch_path = self._revision_dir(current) / "batch.json"
            if batch_path.exists():
                data = json.loads(batch_path.read_text())
                sections = {
                    k: SectionFeedback(**v)
                    for k, v in data.get("section_feedback", {}).items()
                }
                return FeedbackBatch(
                    analysis_id=self.analysis_id,
                    section_feedback=sections,
                    stage_feedback=data.get("stage_feedback"),
                    affects_structure=data.get("affects_structure", False),
                    parent_revision=current,
                )
        return FeedbackBatch(analysis_id=self.analysis_id)

    def estimate_scope(self, batch: FeedbackBatch) -> list[str]:
        """Return which pipeline stages will re-run for this feedback.

        - ``affects_structure=False``: only ``output_generation``
        - ``affects_structure=True``: also ``coordinator_plan``
        """
        if batch.affects_structure:
            return ["coordinator_plan", "output_generation"]
        return ["output_generation"]

    def regenerate(
        self,
        batch: FeedbackBatch,
        summary: str = "",
    ) -> str | None:
        """Save feedback, invalidate stages, and run the pipeline.

        Returns the new revision ID (e.g. ``"v3"``) or ``None`` on failure.
        """
        from ggdes.pipeline import AnalysisPipeline

        # 1. Determine next revision number
        index = self._load_index()
        rev_id = self._next_revision_id(index)

        # 2. Save feedback batch
        rev_dir = self._revision_dir(rev_id)
        rev_dir.mkdir(parents=True, exist_ok=True)
        batch_data = {
            "section_feedback": {
                k: {"text": v.text, "action": v.action}
                for k, v in batch.section_feedback.items()
            },
            "stage_feedback": batch.stage_feedback,
            "affects_structure": batch.affects_structure,
            "parent_revision": batch.parent_revision,
            "created_at": datetime.now().isoformat(),
        }
        (rev_dir / "batch.json").write_text(
            json.dumps(batch_data, indent=2, default=str)
        )

        # 3. Update metadata with current revision
        metadata = self.kb_manager.load_metadata(self.analysis_id)
        if not metadata:
            logger.error("Analysis not found: %s", self.analysis_id)
            return None

        metadata.current_revision = rev_id
        # Also store the revision-scoped output path
        rev_output = self._get_output_base() / rev_id
        self.kb_manager.save_metadata(self.analysis_id, metadata)

        # 4. Invalidate stages based on scope
        stages_to_reset = self.estimate_scope(batch)
        for stage_name in stages_to_reset:
            if stage_name in metadata.stages:
                stage = metadata.stages[stage_name]
                if stage.status in (StageStatus.COMPLETED, StageStatus.FAILED):
                    stage.status = StageStatus.PENDING
                    stage.output_path = None
                    stage.error_message = None
                    stage.completed_at = None
        self.kb_manager.save_metadata(self.analysis_id, metadata)

        # 5. Run pipeline
        pipeline = AnalysisPipeline(self.config, self.analysis_id)
        success = pipeline.run_all_pending()

        # 6. Collect generated output files
        outputs: dict[str, Path] = {}
        if rev_output.exists():
            for f in rev_output.iterdir():
                if f.is_file() and f.suffix in {".md", ".docx", ".pdf", ".pptx"}:
                    fmt = f.suffix.lstrip(".")
                    outputs[fmt] = f

        # 7. Index the new revision
        index["revisions"].append({
            "id": rev_id,
            "parent": batch.parent_revision,
            "created_at": datetime.now().isoformat(),
            "summary": summary or f"Regeneration {rev_id}",
            "outputs": {fmt: str(p) for fmt, p in outputs.items()},
        })
        if success:
            index["current"] = rev_id
        self._save_index(index)

        if success:
            console.print(
                f"\n[green]✓ Created revision {rev_id}[/green]"
            )
            for fmt, path in outputs.items():
                console.print(f"  [dim]{fmt}: {path}[/dim]")
        else:
            console.print(
                f"\n[yellow]Revision {rev_id} created but pipeline incomplete.[/yellow]"
            )

        return rev_id

    # ── revision querying ──────────────────────────────────────────────

    def list_revisions(self) -> list[Revision]:
        """All revisions, newest first."""
        index = self._load_index()
        result: list[Revision] = []
        for entry in reversed(index.get("revisions", [])):
            rev_id = entry["id"]
            batch_path = self._revision_dir(rev_id) / "batch.json"
            batch = FeedbackBatch(analysis_id=self.analysis_id)
            if batch_path.exists():
                data = json.loads(batch_path.read_text())
                sections = {
                    k: SectionFeedback(**v)
                    for k, v in data.get("section_feedback", {}).items()
                }
                batch = FeedbackBatch(
                    analysis_id=self.analysis_id,
                    section_feedback=sections,
                    stage_feedback=data.get("stage_feedback"),
                    affects_structure=data.get("affects_structure", False),
                    parent_revision=data.get("parent_revision"),
                )
            created = datetime.fromisoformat(entry["created_at"])
            output_base = self._get_output_base() / rev_id
            outputs = {}
            if output_base.exists():
                for f in output_base.iterdir():
                    if f.is_file() and f.suffix in {".md", ".docx", ".pdf", ".pptx"}:
                        outputs[f.suffix.lstrip(".")] = f
            result.append(Revision(
                revision_id=rev_id,
                parent=entry.get("parent"),
                created_at=created,
                feedback_summary=entry.get("summary", ""),
                feedback_batch=batch,
                outputs=outputs,
            ))
        return result

    def get_revision(self, revision_id: str) -> Revision | None:
        """Get a specific revision by ID."""
        for rev in self.list_revisions():
            if rev.revision_id == revision_id:
                return rev
        return None

    def set_current(self, revision_id: str) -> bool:
        """Set which revision to treat as current.

        Does NOT regenerate — just updates the index pointer.
        The current revision's output directory is used as the default
        when viewing/downloading documents.
        """
        index = self._load_index()
        for entry in index.get("revisions", []):
            if entry["id"] == revision_id:
                index["current"] = revision_id
                self._save_index(index)

                metadata = self.kb_manager.load_metadata(self.analysis_id)
                if metadata:
                    metadata.current_revision = revision_id
                    self.kb_manager.save_metadata(self.analysis_id, metadata)
                console.print(f"[green]✓ Current revision set to {revision_id}[/green]")
                return True
        console.print(f"[red]Revision {revision_id} not found[/red]")
        return False
