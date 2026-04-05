"""Tests for GGDes."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ggdes.config import GGDesConfig
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.schemas import StoragePolicy


class TestStoragePolicy:
    """Test storage policy enum."""

    def test_storage_policy_values(self):
        """Test storage policy has correct values."""
        assert StoragePolicy.RAW == "raw"
        assert StoragePolicy.SUMMARY == "summary"
        assert StoragePolicy.NONE == "none"

    def test_storage_policy_from_string(self):
        """Test creating storage policy from string."""
        assert StoragePolicy("raw") == StoragePolicy.RAW
        assert StoragePolicy("summary") == StoragePolicy.SUMMARY
        assert StoragePolicy("none") == StoragePolicy.NONE


class TestKnowledgeBaseManager:
    """Test knowledge base manager."""

    @pytest.fixture
    def temp_kb(self):
        """Create temporary KB directory."""
        temp_dir = tempfile.mkdtemp()
        config = GGDesConfig()
        config.paths.knowledge_base = temp_dir
        yield config
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_analysis(self, temp_kb):
        """Test creating an analysis."""
        kb = KnowledgeBaseManager(temp_kb)

        metadata = kb.create_analysis(
            analysis_id="test-123",
            name="test-analysis",
            repo_path=Path("/tmp/test-repo"),
            commit_range="HEAD~1..HEAD",
            focus_commits=None,
            prompt_version="v1.0.0",
            target_formats=["markdown"],
            storage_policy="summary",
        )

        assert metadata.id == "test-123"
        assert metadata.name == "test-analysis"
        assert metadata.commit_range == "HEAD~1..HEAD"
        assert metadata.target_formats == ["markdown"]
        assert metadata.storage_policy == "summary"

        # Check directories were created
        analysis_path = kb.get_analysis_path("test-123")
        assert analysis_path.exists()
        assert (analysis_path / "git_analysis").exists()
        assert (analysis_path / "ast_base").exists()
        assert (analysis_path / "ast_head").exists()

    def test_load_metadata(self, temp_kb):
        """Test loading metadata."""
        kb = KnowledgeBaseManager(temp_kb)

        # Create analysis
        kb.create_analysis(
            analysis_id="test-load",
            name="test",
            repo_path=Path("/tmp/test"),
            commit_range="HEAD~1..HEAD",
        )

        # Load it back
        metadata = kb.load_metadata("test-load")
        assert metadata is not None
        assert metadata.id == "test-load"
        assert metadata.name == "test"

    def test_stage_tracking(self, temp_kb):
        """Test stage status tracking."""
        kb = KnowledgeBaseManager(temp_kb)

        metadata = kb.create_analysis(
            analysis_id="test-stages",
            name="test",
            repo_path=Path("/tmp/test"),
            commit_range="HEAD~1..HEAD",
        )

        # Test initial state
        assert not metadata.is_stage_completed("worktree_setup")

        # Test completing a stage
        metadata.complete_stage("worktree_setup")
        assert metadata.is_stage_completed("worktree_setup")

        # Test failing a stage
        metadata.fail_stage("git_analysis", "Test error")
        stage = metadata.get_stage("git_analysis")
        assert stage.status == StageStatus.FAILED
        assert stage.error_message == "Test error"

        # Test resetting a stage
        metadata.reset_stage("git_analysis")
        stage = metadata.get_stage("git_analysis")
        assert stage.status == StageStatus.PENDING
        assert stage.error_message is None

    def test_can_resume(self, temp_kb):
        """Test can_resume logic."""
        kb = KnowledgeBaseManager(temp_kb)

        # Create analysis
        kb.create_analysis(
            analysis_id="test-resume",
            name="test",
            repo_path=Path("/tmp/test"),
            commit_range="HEAD~1..HEAD",
        )

        # Should be able to resume fresh analysis
        can_resume, reason = kb.can_resume("test-resume")
        assert can_resume is True
        assert reason is None

        # Fail a stage
        metadata = kb.load_metadata("test-resume")
        metadata.fail_stage("worktree_setup", "Failed")
        kb.save_metadata("test-resume", metadata)

        # Should NOT be able to resume without retry_failed
        can_resume, reason = kb.can_resume("test-resume")
        assert can_resume is False
        assert "failed" in reason.lower()

        # SHOULD be able to resume with retry_failed
        can_resume, reason = kb.can_resume("test-resume", retry_failed=True)
        assert can_resume is True

    def test_reset_failed_stages(self, temp_kb):
        """Test resetting failed stages."""
        kb = KnowledgeBaseManager(temp_kb)

        # Create analysis with failed stages
        metadata = kb.create_analysis(
            analysis_id="test-reset",
            name="test",
            repo_path=Path("/tmp/test"),
            commit_range="HEAD~1..HEAD",
        )
        metadata.fail_stage("worktree_setup", "Error 1")
        metadata.fail_stage("git_analysis", "Error 2")
        kb.save_metadata("test-reset", metadata)

        # Reset failed stages
        reset = kb.reset_failed_stages("test-reset")
        assert len(reset) == 2
        assert "worktree_setup" in reset
        assert "git_analysis" in reset

        # Verify stages are now pending
        metadata = kb.load_metadata("test-reset")
        assert metadata.get_stage("worktree_setup").status == StageStatus.PENDING
        assert metadata.get_stage("git_analysis").status == StageStatus.PENDING


class TestCLICommitParsing:
    """Test CLI commit range parsing logic."""

    def test_valid_commit_range(self):
        """Test valid commit range formats."""
        valid_ranges = [
            "HEAD~1..HEAD",
            "HEAD~5..HEAD",
            "abc123..def456",
            "a578c0e659..HEAD",
            "v1.0.0..v2.0.0",
        ]

        for range_str in valid_ranges:
            assert ".." in range_str
            parts = range_str.split("..", 1)
            assert len(parts) == 2
            assert parts[0]

    def test_commit_range_parsing(self):
        """Test parsing commit range into base and head."""
        test_cases = [
            ("HEAD~5..HEAD", ("HEAD~5", "HEAD")),
            ("abc123..def456", ("abc123", "def456")),
            ("a578c0e659..HEAD", ("a578c0e659", "HEAD")),
        ]

        for range_str, expected in test_cases:
            base, head = range_str.split("..", 1)
            assert base == expected[0]
            assert head == expected[1]


class TestOutputAgents:
    """Test output agents skill loading."""

    def test_skill_loading(self):
        """Test that skills can be loaded."""
        from ggdes.agents.output_agents import DocxAgent, PdfAgent, PptxAgent

        config = MagicMock()
        config.paths.knowledge_base = tempfile.mkdtemp()

        # These should load skills without error
        docx_agent = DocxAgent(Path("."), config, "test")
        pdf_agent = PdfAgent(Path("."), config, "test")
        pptx_agent = PptxAgent(Path("."), config, "test")

        # Verify skills were loaded
        assert hasattr(docx_agent, "skill_content")
        assert hasattr(pdf_agent, "skill_content")
        assert hasattr(pptx_agent, "skill_content")

        assert len(docx_agent.skill_content) > 0
        assert len(pdf_agent.skill_content) > 0
        assert len(pptx_agent.skill_content) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
