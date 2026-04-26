"""Tests for the feedback and revision management module."""

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ggdes.config import GGDesConfig
from ggdes.feedback import (
    FeedbackBatch,
    FeedbackManager,
    Revision,
    SectionFeedback,
)
from ggdes.kb import KnowledgeBaseManager, StageStatus


class TestDataModels:
    """Test feedback data models."""

    def test_section_feedback_defaults(self) -> None:
        fb = SectionFeedback(text="Fix this section")
        assert fb.text == "Fix this section"
        assert fb.action == "refine"

    def test_section_feedback_rewrite(self) -> None:
        fb = SectionFeedback(text="Rewrite this", action="rewrite")
        assert fb.text == "Rewrite this"
        assert fb.action == "rewrite"

    def test_feedback_batch_defaults(self) -> None:
        batch = FeedbackBatch(analysis_id="test-123")
        assert batch.analysis_id == "test-123"
        assert batch.section_feedback == {}
        assert batch.stage_feedback is None
        assert batch.affects_structure is False
        assert batch.parent_revision is None

    def test_feedback_batch_with_sections(self) -> None:
        batch = FeedbackBatch(
            analysis_id="test-123",
            section_feedback={
                "Overview": SectionFeedback(text="Add summary"),
                "API": SectionFeedback(text="Fix examples", action="rewrite"),
            },
            stage_feedback="Make it better overall",
        )
        assert len(batch.section_feedback) == 2
        assert batch.section_feedback["Overview"].text == "Add summary"
        assert batch.section_feedback["API"].action == "rewrite"
        assert batch.stage_feedback == "Make it better overall"

    def test_revision_dataclass(self) -> None:
        now = datetime.now()
        batch = FeedbackBatch(analysis_id="test-123")
        rev = Revision(
            revision_id="v1",
            parent=None,
            created_at=now,
            feedback_summary="Initial generation",
            feedback_batch=batch,
            outputs={"markdown": Path("/tmp/output/v1/doc.md")},
        )
        assert rev.revision_id == "v1"
        assert rev.parent is None
        assert rev.feedback_summary == "Initial generation"
        assert rev.outputs["markdown"] == Path("/tmp/output/v1/doc.md")

    def test_revision_with_parent(self) -> None:
        now = datetime.now()
        child_batch = FeedbackBatch(
            analysis_id="test-123",
            section_feedback={"Overview": SectionFeedback(text="Fix it")},
            parent_revision="v1",
        )
        child = Revision(
            revision_id="v2",
            parent="v1",
            created_at=now,
            feedback_summary="Feedback fix",
            feedback_batch=child_batch,
            outputs={},
        )
        assert child.revision_id == "v2"
        assert child.parent == "v1"
        assert child.feedback_batch.parent_revision == "v1"


class TestFeedbackManager:
    """Test FeedbackManager operations."""

    @pytest.fixture
    def config(self):  # type: ignore[no-untyped-def]
        """Create config with temp KB path."""
        temp_dir = tempfile.mkdtemp()
        cfg = GGDesConfig()
        cfg.paths.knowledge_base = temp_dir
        cfg.paths.output = tempfile.mkdtemp()
        yield cfg
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(cfg.paths.output, ignore_errors=True)

    @pytest.fixture
    def analysis(self, config):  # type: ignore[no-untyped-def]
        """Create a completed analysis in KB."""
        kb = KnowledgeBaseManager(config)
        metadata = kb.create_analysis(
            analysis_id="feedback-test",
            name="Feedback Test",
            repo_path=Path("/tmp/repo"),
            commit_range="abc..def",
            target_formats=["markdown", "docx"],
        )
        # Mark all stages as completed
        all_stages = [
            "worktree_setup",
            "git_analysis",
            "change_filter",
            "ast_parsing_base",
            "ast_parsing_head",
            "semantic_diff",
            "technical_author",
            "coordinator_plan",
            "output_generation",
        ]
        for stage in all_stages:
            metadata.stages[stage].status = StageStatus.COMPLETED
            metadata.stages[stage].completed_at = datetime.now()
        kb.save_metadata("feedback-test", metadata)
        return "feedback-test"

    def test_collect_empty_when_no_revisions(self, config, analysis) -> None:
        mgr = FeedbackManager(config, analysis)
        batch = mgr.collect()
        assert batch.analysis_id == analysis
        assert batch.section_feedback == {}
        assert batch.stage_feedback is None
        assert batch.parent_revision is None

    def test_estimate_scope_output_only(self, config, analysis) -> None:
        mgr = FeedbackManager(config, analysis)
        batch = FeedbackBatch(
            analysis_id=analysis,
            affects_structure=False,
        )
        scope = mgr.estimate_scope(batch)
        assert scope == ["output_generation"]

    def test_estimate_scope_with_structural(self, config, analysis) -> None:
        mgr = FeedbackManager(config, analysis)
        batch = FeedbackBatch(
            analysis_id=analysis,
            affects_structure=True,
        )
        scope = mgr.estimate_scope(batch)
        assert scope == ["coordinator_plan", "output_generation"]

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_regenerate_saves_batch_and_creates_revision(
        self, mock_pipeline_class, config, analysis
    ) -> None:
        """Test that regenerate() saves feedback and creates revision index entry."""
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        batch = FeedbackBatch(
            analysis_id=analysis,
            section_feedback={
                "Overview": SectionFeedback(text="Add intro paragraph"),
            },
            stage_feedback="Overall improvements needed",
            affects_structure=False,
        )
        rev_id = mgr.regenerate(batch, summary="Fix overview")

        assert rev_id == "v1"

        # Check batch was saved
        batch_path = mgr._revision_dir("v1") / "batch.json"
        assert batch_path.exists()
        saved = json.loads(batch_path.read_text())
        assert "Overview" in saved["section_feedback"]
        assert saved["section_feedback"]["Overview"]["text"] == "Add intro paragraph"
        assert saved["stage_feedback"] == "Overall improvements needed"
        assert saved["affects_structure"] is False

        # Check index was created
        index = mgr._load_index()
        assert index["current"] == "v1"
        assert len(index["revisions"]) == 1
        assert index["revisions"][0]["id"] == "v1"
        assert index["revisions"][0]["summary"] == "Fix overview"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_regenerate_increments_revision(self, mock_pipeline_class, config, analysis) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(
            FeedbackBatch(analysis_id=analysis),
            summary="First gen",
        )

        rev2 = mgr.regenerate(
            FeedbackBatch(analysis_id=analysis),
            summary="Second gen",
        )
        assert rev2 == "v2"

        index = mgr._load_index()
        assert index["current"] == "v2"
        assert len(index["revisions"]) == 2

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_list_revisions_order(self, mock_pipeline_class, config, analysis) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(FeedbackBatch(analysis_id=analysis), summary="v1 docs")
        mgr.regenerate(FeedbackBatch(analysis_id=analysis), summary="v2 docs")

        revisions = mgr.list_revisions()
        # Newest first
        assert len(revisions) == 2
        assert revisions[0].revision_id == "v2"
        assert revisions[1].revision_id == "v1"
        assert revisions[0].feedback_summary == "v2 docs"
        assert revisions[1].feedback_summary == "v1 docs"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_get_revision_by_id(self, mock_pipeline_class, config, analysis) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(
            FeedbackBatch(analysis_id=analysis, stage_feedback="fix"),
            summary="First",
        )

        rev = mgr.get_revision("v1")
        assert rev is not None
        assert rev.revision_id == "v1"
        assert rev.feedback_summary == "First"

        # Non-existent revision
        assert mgr.get_revision("v999") is None

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_set_current_revision(self, mock_pipeline_class, config, analysis) -> None:
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(FeedbackBatch(analysis_id=analysis), summary="v1")
        mgr.regenerate(FeedbackBatch(analysis_id=analysis), summary="v2")

        # Current should be v2
        index = mgr._load_index()
        assert index["current"] == "v2"

        # Switch back to v1
        assert mgr.set_current("v1") is True
        index = mgr._load_index()
        assert index["current"] == "v1"

        # Try invalid revision
        assert mgr.set_current("v999") is False
        index = mgr._load_index()
        assert index["current"] == "v1"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_collect_after_regenerate(self, mock_pipeline_class, config, analysis) -> None:
        """collect() should load the latest revision's feedback for editing."""
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = True
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(
            FeedbackBatch(
                analysis_id=analysis,
                section_feedback={"Overview": SectionFeedback(text="Add more")},
                stage_feedback="Fix formatting",
            ),
            summary="Initial",
        )

        collected = mgr.collect()
        assert collected.parent_revision == "v1"
        assert "Overview" in collected.section_feedback
        assert collected.section_feedback["Overview"].text == "Add more"
        assert collected.stage_feedback == "Fix formatting"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_regenerate_failure_does_not_set_current(
        self, mock_pipeline_class, config, analysis
    ) -> None:
        """If pipeline fails, revision should not be set as current."""
        mock_pipeline = MagicMock()
        mock_pipeline.run_all_pending.return_value = False
        mock_pipeline_class.return_value = mock_pipeline

        mgr = FeedbackManager(config, analysis)
        rev_id = mgr.regenerate(
            FeedbackBatch(analysis_id=analysis),
            summary="Failed attempt",
        )
        assert rev_id is not None  # revision is still created

        index = mgr._load_index()
        assert "current" not in index or index["current"] is None


class TestFeedbackManagerIntegration:
    """Integration tests with real KB storage.

    Uses @patch to avoid running the real pipeline (which requires
    git repos, worktrees, etc.). Focus is on validating that feedback
    data and revision index persist correctly across FeedbackManager instances.
    """

    @pytest.fixture
    def config(self):  # type: ignore[no-untyped-def]
        temp_dir = tempfile.mkdtemp()
        cfg = GGDesConfig()
        cfg.paths.knowledge_base = temp_dir
        cfg.paths.output = tempfile.mkdtemp()
        yield cfg
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(cfg.paths.output, ignore_errors=True)

    @pytest.fixture
    def analysis(self, config):  # type: ignore[no-untyped-def]
        repo_dir = Path(tempfile.mkdtemp())
        kb = KnowledgeBaseManager(config)
        kb.create_analysis(
            analysis_id="integ-test",
            name="Integration Test",
            repo_path=repo_dir,
            commit_range="a..b",
            target_formats=["markdown"],
        )
        return "integ-test"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_revision_persistence_across_instances(self, mock_pipeline_cls, config, analysis) -> None:
        """Revisions should persist when creating a new FeedbackManager."""
        mgr1 = FeedbackManager(config, analysis)
        mgr1.regenerate(
            FeedbackBatch(analysis_id=analysis, stage_feedback="first"),
            summary="Gen 1",
        )

        # New FeedbackManager instance reads same data
        mgr2 = FeedbackManager(config, analysis)
        revisions = mgr2.list_revisions()
        assert len(revisions) == 1
        assert revisions[0].revision_id == "v1"
        assert revisions[0].feedback_summary == "Gen 1"

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_multiple_revisions_persist(self, mock_pipeline_cls, config, analysis) -> None:
        mgr = FeedbackManager(config, analysis)
        for i in range(3):
            mgr.regenerate(
                FeedbackBatch(
                    analysis_id=analysis,
                    section_feedback={"S1": SectionFeedback(text=f"fix {i}")},
                ),
                summary=f"Round {i + 1}",
            )

        revisions = mgr.list_revisions()
        assert len(revisions) == 3
        summaries = [r.feedback_summary for r in revisions]
        assert summaries == ["Round 3", "Round 2", "Round 1"]

    @patch("ggdes.pipeline.AnalysisPipeline")
    def test_metadata_updated_on_regenerate(self, mock_pipeline_cls, config, analysis) -> None:
        mgr = FeedbackManager(config, analysis)
        mgr.regenerate(
            FeedbackBatch(analysis_id=analysis),
            summary="First",
        )

        kb = KnowledgeBaseManager(config)
        metadata = kb.load_metadata(analysis)
        assert metadata is not None
        assert metadata.current_revision == "v1"


class TestSectionFeedback:
    """Test SectionFeedback model validation."""

    def test_action_values(self) -> None:
        for action in ("refine", "rewrite", "keep"):
            fb = SectionFeedback(text="test", action=action)  # type: ignore[arg-type]
            assert fb.action == action

    def test_empty_text(self) -> None:
        fb = SectionFeedback(text="")
        assert fb.text == ""
