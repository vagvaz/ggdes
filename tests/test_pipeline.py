"""Comprehensive tests for GGDes pipeline module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from ggdes.config import (
    FeaturesConfig,
    GGDesConfig,
    ParsingConfig,
    ParsingMode,
    PathsConfig,
)
from ggdes.kb.manager import (
    AnalysisMetadata,
    KnowledgeBaseManager,
    WorktreeInfo,
)
from ggdes.pipeline import AnalysisPipeline
from ggdes.schemas import StoragePolicy


@pytest.fixture
def mock_config() -> GGDesConfig:
    """Create a mock GGDesConfig for testing."""
    config = MagicMock(spec=GGDesConfig)
    config.paths = MagicMock(spec=PathsConfig)
    config.paths.knowledge_base = "~/test-kb"
    config.paths.worktrees = "~/test-worktrees"
    config.features = MagicMock(spec=FeaturesConfig)
    config.features.auto_cleanup = True
    config.features.worktree_retention_days = 7
    config.parsing = MagicMock(spec=ParsingConfig)
    config.parsing.mode = ParsingMode.FULL
    config.parsing.include_referenced = True
    config.parsing.max_referenced_depth = 1
    return config


@pytest.fixture
def mock_metadata() -> AnalysisMetadata:
    """Create a mock AnalysisMetadata for testing."""
    metadata = MagicMock(spec=AnalysisMetadata)
    metadata.id = "test_analysis_001"
    metadata.name = "Test Analysis"
    metadata.repo_path = "/test/repo"
    metadata.commit_range = "abc123..def456"
    metadata.focus_commits = None
    metadata.target_formats = ["markdown"]
    metadata.storage_policy = StoragePolicy.SUMMARY
    metadata.user_context = None
    metadata.worktrees = None
    metadata.stages = {}
    metadata.created_at = datetime.now()
    metadata.updated_at = datetime.now()
    return metadata


@pytest.fixture
def mock_kb_manager(mock_metadata: AnalysisMetadata) -> MagicMock:
    """Create a mock KnowledgeBaseManager for testing."""
    kb_manager = MagicMock(spec=KnowledgeBaseManager)
    kb_manager.load_metadata.return_value = mock_metadata
    kb_manager.get_analysis_path.return_value = Path(
        "/test/kb/analyses/test_analysis_001"
    )
    kb_manager.STAGE_WORKTREE_SETUP = "worktree_setup"
    kb_manager.STAGE_GIT_ANALYSIS = "git_analysis"
    kb_manager.STAGE_AST_PARSING_BASE = "ast_parsing_base"
    kb_manager.STAGE_AST_PARSING_HEAD = "ast_parsing_head"
    kb_manager.STAGE_SEMANTIC_DIFF = "semantic_diff"
    kb_manager.STAGE_TECHNICAL_AUTHOR = "technical_author"
    kb_manager.STAGE_COORDINATOR_PLAN = "coordinator_plan"
    kb_manager.STAGE_OUTPUT_GENERATION = "output_generation"
    kb_manager.ALL_STAGES = [
        "worktree_setup",
        "git_analysis",
        "ast_parsing_base",
        "ast_parsing_head",
        "semantic_diff",
        "technical_author",
        "coordinator_plan",
        "output_generation",
    ]
    return kb_manager


class TestAnalysisPipelineInitialization:
    """Tests for AnalysisPipeline initialization."""

    def test_pipeline_init_with_valid_analysis_id(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test pipeline initialization with valid analysis ID."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager") as mock_wt_class:
                mock_wt_instance = MagicMock()
                mock_wt_class.return_value = mock_wt_instance

                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                assert pipeline.config == mock_config
                assert pipeline.analysis_id == "test_analysis_001"
                assert pipeline.metadata == mock_metadata
                # repo_path is a Path object created from metadata.repo_path
                assert str(pipeline.repo_path) == "/test/repo"
                # Check that _metadata_lock exists and has acquire/release methods (Lock interface)
                assert hasattr(pipeline._metadata_lock, "acquire")
                assert hasattr(pipeline._metadata_lock, "release")

                mock_kb_instance.load_metadata.assert_called_once_with(
                    "test_analysis_001"
                )

    def test_pipeline_init_with_invalid_analysis_id(
        self, mock_config: GGDesConfig
    ) -> None:
        """Test pipeline initialization raises ValueError for invalid analysis ID."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = None
            mock_kb_class.return_value = mock_kb_instance

            with pytest.raises(ValueError, match="Analysis not found: invalid_id"):
                AnalysisPipeline(mock_config, "invalid_id")


class TestRunStage:
    """Tests for run_stage method."""

    def test_run_stage_already_completed(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test that completed stages are skipped."""
        mock_metadata.is_stage_completed.return_value = True

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.console") as mock_console:
                    result = pipeline.run_stage("worktree_setup")

                    assert result is True
                    mock_console.print.assert_called_with(
                        "[dim]Stage 'worktree_setup' already completed, skipping[/dim]"
                    )

    def test_run_stage_pending_stage_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test running a pending stage successfully."""
        mock_metadata.is_stage_completed.return_value = False
        mock_metadata.start_stage = MagicMock()
        mock_metadata.complete_stage = MagicMock()

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.STAGE_WORKTREE_SETUP = "worktree_setup"
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock the specific stage method
                with patch.object(pipeline, "_run_worktree_setup", return_value=True):
                    result = pipeline.run_stage("worktree_setup")

                    assert result is True
                    mock_metadata.start_stage.assert_called_once_with("worktree_setup")
                    mock_metadata.complete_stage.assert_called_once_with(
                        "worktree_setup"
                    )

    def test_run_stage_pending_stage_failure(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test running a pending stage that fails."""
        mock_metadata.is_stage_completed.return_value = False
        mock_metadata.start_stage = MagicMock()
        mock_metadata.fail_stage = MagicMock()

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.STAGE_WORKTREE_SETUP = "worktree_setup"
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch.object(pipeline, "_run_worktree_setup", return_value=False):
                    result = pipeline.run_stage("worktree_setup")

                    assert result is False
                    mock_metadata.fail_stage.assert_called_once_with(
                        "worktree_setup", "Stage returned False"
                    )

    def test_run_stage_exception_handling(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test that exceptions in stage execution are handled properly."""
        mock_metadata.is_stage_completed.return_value = False
        mock_metadata.start_stage = MagicMock()
        mock_metadata.fail_stage = MagicMock()

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.STAGE_WORKTREE_SETUP = "worktree_setup"
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch.object(
                    pipeline, "_run_worktree_setup", side_effect=Exception("Test error")
                ):
                    result = pipeline.run_stage("worktree_setup")

                    assert result is False
                    mock_metadata.fail_stage.assert_called_once_with(
                        "worktree_setup", "Test error"
                    )

    def test_run_stage_unimplemented_stage(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test running an unimplemented stage marks it as skipped."""
        mock_metadata.is_stage_completed.return_value = False
        mock_metadata.start_stage = MagicMock()
        mock_metadata.skip_stage = MagicMock()

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline.run_stage("unknown_stage")

                assert result is True
                mock_metadata.skip_stage.assert_called_once_with("unknown_stage")


class TestRunAllPending:
    """Tests for run_all_pending method."""

    def test_run_all_pending_all_completed(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test run_all_pending when all stages are already completed."""
        mock_metadata.get_pending_stages.return_value = []

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.console") as mock_console:
                    result = pipeline.run_all_pending()

                    assert result is True
                    mock_console.print.assert_called_with(
                        "[green]All stages already completed![/green]"
                    )

    def test_run_all_pending_with_pending_stages(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test run_all_pending with pending stages."""
        mock_metadata.get_pending_stages.return_value = [
            "worktree_setup",
            "git_analysis",
        ]

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.STAGE_WORKTREE_SETUP = "worktree_setup"
            mock_kb_instance.STAGE_GIT_ANALYSIS = "git_analysis"
            mock_kb_instance.STAGE_AST_PARSING_BASE = "ast_parsing_base"
            mock_kb_instance.STAGE_AST_PARSING_HEAD = "ast_parsing_head"
            mock_kb_instance.STAGE_SEMANTIC_DIFF = "semantic_diff"
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                with patch("ggdes.pipeline.LockContext"):
                    pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                    with patch.object(
                        pipeline, "run_stage", return_value=True
                    ) as mock_run_stage:
                        result = pipeline.run_all_pending()

                        assert result is True
                        assert mock_run_stage.call_count == 2
                        mock_run_stage.assert_any_call("worktree_setup")
                        mock_run_stage.assert_any_call("git_analysis")

    def test_run_all_pending_stage_failure(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test run_all_pending halts on stage failure."""
        mock_metadata.get_pending_stages.return_value = [
            "worktree_setup",
            "git_analysis",
        ]

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.STAGE_WORKTREE_SETUP = "worktree_setup"
            mock_kb_instance.STAGE_GIT_ANALYSIS = "git_analysis"
            mock_kb_instance.STAGE_AST_PARSING_BASE = "ast_parsing_base"
            mock_kb_instance.STAGE_AST_PARSING_HEAD = "ast_parsing_head"
            mock_kb_instance.STAGE_SEMANTIC_DIFF = "semantic_diff"
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                with patch("ggdes.pipeline.LockContext"):
                    pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                    with patch.object(
                        pipeline, "run_stage", side_effect=[True, False]
                    ) as mock_run_stage:
                        result = pipeline.run_all_pending()

                        assert result is False
                        assert mock_run_stage.call_count == 2


class TestRunParallelGroup:
    """Tests for run_parallel_group method."""

    def test_run_parallel_group_all_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test running parallel group with all stages succeeding."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch.object(
                    pipeline, "run_stage", return_value=True
                ) as mock_run_stage:
                    results = pipeline.run_parallel_group(
                        ["ast_parsing_base", "ast_parsing_head"]
                    )

                    assert results == {
                        "ast_parsing_base": True,
                        "ast_parsing_head": True,
                    }
                    assert mock_run_stage.call_count == 2

    def test_run_parallel_group_partial_failure(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test running parallel group with some stages failing."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                def side_effect(stage: str) -> bool:
                    return stage == "ast_parsing_base"

                with patch.object(
                    pipeline, "run_stage", side_effect=side_effect
                ) as mock_run_stage:
                    results = pipeline.run_parallel_group(
                        ["ast_parsing_base", "ast_parsing_head"]
                    )

                    assert results["ast_parsing_base"] is True
                    assert results["ast_parsing_head"] is False


class TestRunAstParsing:
    """Tests for _run_ast_parsing method."""

    def test_run_ast_parsing_base_variant(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _run_ast_parsing with base variant."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/test/worktrees/base",
            head="/test/worktrees/head",
        )

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock ASTParser
                mock_parse_result = MagicMock()
                mock_parse_result.success = True
                mock_parse_result.file_path = "test.py"
                mock_parse_result.language = "python"
                mock_parse_result.elements = []

                with patch("ggdes.pipeline.ASTParser") as mock_parser_class:
                    mock_parser = MagicMock()
                    mock_parser.parse_directory.return_value = [mock_parse_result]
                    mock_parser_class.return_value = mock_parser

                    # Mock Path operations
                    with patch("ggdes.pipeline.Path.exists", return_value=True):
                        with patch(
                            "ggdes.pipeline.Path.iterdir", return_value=[Path("file1")]
                        ):
                            with patch("ggdes.pipeline.Path.mkdir"):
                                with patch("ggdes.pipeline.Path.write_text"):
                                    result = pipeline._run_ast_parsing("base")

                                    assert result is True
                                    mock_parser.parse_directory.assert_called_once()

    def test_run_ast_parsing_head_variant(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _run_ast_parsing with head variant."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/test/worktrees/base",
            head="/test/worktrees/head",
        )

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                mock_parse_result = MagicMock()
                mock_parse_result.success = True
                mock_parse_result.file_path = "test.py"
                mock_parse_result.language = "python"
                mock_parse_result.elements = []

                with patch("ggdes.pipeline.ASTParser") as mock_parser_class:
                    mock_parser = MagicMock()
                    mock_parser.parse_directory.return_value = [mock_parse_result]
                    mock_parser_class.return_value = mock_parser

                    with patch("ggdes.pipeline.Path.exists", return_value=True):
                        with patch(
                            "ggdes.pipeline.Path.iterdir", return_value=[Path("file1")]
                        ):
                            with patch("ggdes.pipeline.Path.mkdir"):
                                with patch("ggdes.pipeline.Path.write_text"):
                                    result = pipeline._run_ast_parsing("head")

                                    assert result is True

    def test_run_ast_parsing_no_worktrees(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _run_ast_parsing fails when worktrees not set up."""
        mock_metadata.worktrees = None

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline._run_ast_parsing("base")

                assert result is False

    def test_run_ast_parsing_worktree_not_exist(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _run_ast_parsing fails when worktree doesn't exist."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/nonexistent/base",
            head="/nonexistent/head",
        )

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.Path.exists", return_value=False):
                    result = pipeline._run_ast_parsing("base")

                    assert result is False

    def test_run_ast_parsing_worktree_not_exist(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _run_ast_parsing fails when worktree doesn't exist."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/nonexistent/base",
            head="/nonexistent/head",
        )

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch.object(Path, "exists", return_value=False):
                    result = pipeline._run_ast_parsing("base")

                    assert result is False


class TestGetChangedFilesDetailed:
    """Tests for _get_changed_files_detailed method."""

    def test_get_changed_files_detailed_with_data(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _get_changed_files_detailed with mock git analysis data."""
        mock_analysis_data = {
            "files_changed": [
                {
                    "path": "src/main.py",
                    "change_type": "modified",
                    "lines_added": 10,
                    "lines_deleted": 5,
                    "summary": "Added new feature",
                },
                {
                    "path": "tests/test_main.py",
                    "change_type": "added",
                    "lines_added": 50,
                    "lines_deleted": 0,
                    "summary": "Added tests",
                },
            ]
        }

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            # Return a MagicMock for path that supports / operator and exists()
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.__truediv__ = MagicMock(return_value=mock_path)
            mock_kb_instance.get_analysis_path.return_value = mock_path
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock file reading
                with (
                    patch(
                        "builtins.open",
                        mock_open(read_data=json.dumps(mock_analysis_data)),
                    ),
                    patch(
                        "ggdes.pipeline.json.loads",
                        return_value=mock_analysis_data,
                    ),
                ):
                    result = pipeline._get_changed_files_detailed()

                    assert len(result) == 2
                    assert result[0]["path"] == "src/main.py"
                    assert result[0]["change_type"] == "modified"
                    assert result[0]["lines_added"] == 10
                    assert result[1]["path"] == "tests/test_main.py"

    def test_get_changed_files_detailed_no_file(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _get_changed_files_detailed when analysis file doesn't exist."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.Path.exists", return_value=False):
                    result = pipeline._get_changed_files_detailed()

                    assert result == []

    def test_get_changed_files_detailed_invalid_json(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _get_changed_files_detailed with invalid JSON."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.Path.exists", return_value=True):
                    with patch(
                        "builtins.open",
                        mock_open(read_data="invalid json"),
                    ):
                        with patch(
                            "ggdes.pipeline.json.loads",
                            side_effect=json.JSONDecodeError("test", "", 0),
                        ):
                            result = pipeline._get_changed_files_detailed()

                            assert result == []

    def test_get_changed_files_detailed_invalid_json(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _get_changed_files_detailed with invalid JSON."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch.object(Path, "exists", return_value=True):
                    with patch(
                        "builtins.open",
                        mock_open(read_data="invalid json"),
                    ):
                        with patch(
                            "ggdes.pipeline.json.loads",
                            side_effect=json.JSONDecodeError("test", "", 0),
                        ):
                            result = pipeline._get_changed_files_detailed()

                            assert result == []


class TestBuildToolExecutor:
    """Tests for _build_tool_executor method."""

    def test_build_tool_executor_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _build_tool_executor constructs ToolExecutor correctly."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None

        # The method does: from ggdes.tools import ToolExecutor
        # We need to patch it where it's used in the pipeline module
        with patch("ggdes.tools.ToolExecutor") as mock_tool_executor_class:
            mock_executor = MagicMock()
            mock_tool_executor_class.return_value = mock_executor

            with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
                mock_kb_instance = MagicMock()
                mock_kb_instance.load_metadata.return_value = mock_metadata
                mock_kb_instance.get_analysis_path.return_value = Path(
                    "/test/kb/test_analysis_001"
                )
                mock_kb_class.return_value = mock_kb_instance

                with patch("ggdes.pipeline.WorktreeManager"):
                    pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                    # Mock _get_changed_files_detailed
                    pipeline._get_changed_files_detailed = MagicMock(
                        return_value=[
                            {
                                "path": "src/main.py",
                                "change_type": "modified",
                                "lines_added": 10,
                                "lines_deleted": 5,
                                "summary": "Changes",
                            }
                        ]
                    )

                    # Mock _load_ast_elements_for_tools
                    pipeline._load_ast_elements_for_tools = MagicMock(
                        return_value={"src/main.py": [{"name": "test_func"}]}
                    )

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()

    def test_build_tool_executor_no_data(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _build_tool_executor with no data available."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None

        # The method does: from ggdes.tools import ToolExecutor
        # We need to patch it where it's used in the pipeline module
        with patch("ggdes.tools.ToolExecutor") as mock_tool_executor_class:
            mock_executor = MagicMock()
            mock_tool_executor_class.return_value = mock_executor

            with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
                mock_kb_instance = MagicMock()
                mock_kb_instance.load_metadata.return_value = mock_metadata
                mock_kb_instance.get_analysis_path.return_value = Path(
                    "/test/kb/test_analysis_001"
                )
                mock_kb_class.return_value = mock_kb_instance

                with patch("ggdes.pipeline.WorktreeManager"):
                    pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                    # Mock empty data
                    pipeline._get_changed_files_detailed = MagicMock(return_value=[])
                    pipeline._load_ast_elements_for_tools = MagicMock(return_value={})

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()

    def test_build_tool_executor_no_data(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _build_tool_executor with no data available."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock empty data
                pipeline._get_changed_files_detailed = MagicMock(return_value=[])
                pipeline._load_ast_elements_for_tools = MagicMock(return_value={})

                # Patch where it's imported locally in _build_tool_executor
                with patch(
                    "ggdes.tools.executor.ToolExecutor"
                ) as mock_tool_executor_class:
                    mock_executor = MagicMock()
                    mock_tool_executor_class.return_value = mock_executor

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()

    def test_build_tool_executor_no_data(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _build_tool_executor with no data available."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock empty data
                pipeline._get_changed_files_detailed = MagicMock(return_value=[])
                pipeline._load_ast_elements_for_tools = MagicMock(return_value={})

                # Patch at the pipeline module level where it's imported
                with patch("ggdes.pipeline.ToolExecutor") as mock_tool_executor_class:
                    mock_executor = MagicMock()
                    mock_tool_executor_class.return_value = mock_executor

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock _get_changed_files_detailed
                pipeline._get_changed_files_detailed = MagicMock(
                    return_value=[
                        {
                            "path": "src/main.py",
                            "change_type": "modified",
                            "lines_added": 10,
                            "lines_deleted": 5,
                            "summary": "Changes",
                        }
                    ]
                )

                # Mock _load_ast_elements_for_tools
                pipeline._load_ast_elements_for_tools = MagicMock(
                    return_value={"src/main.py": [{"name": "test_func"}]}
                )

                # The method does: from ggdes.tools import ToolExecutor
                with patch("ggdes.tools.ToolExecutor") as mock_tool_executor_class:
                    mock_executor = MagicMock()
                    mock_tool_executor_class.return_value = mock_executor

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()

    def test_build_tool_executor_no_data(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test _build_tool_executor with no data available."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None

        # The method does: from ggdes.tools import ToolExecutor
        # We need to patch it where it's used in the pipeline module
        with patch("ggdes.tools.ToolExecutor") as mock_tool_executor_class:
            mock_executor = MagicMock()
            mock_tool_executor_class.return_value = mock_executor

            with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
                mock_kb_instance = MagicMock()
                mock_kb_instance.load_metadata.return_value = mock_metadata
                mock_kb_instance.get_analysis_path.return_value = Path(
                    "/test/kb/test_analysis_001"
                )
                mock_kb_class.return_value = mock_kb_instance

                with patch("ggdes.pipeline.WorktreeManager"):
                    pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                    # Mock empty data
                    pipeline._get_changed_files_detailed = MagicMock(return_value=[])
                    pipeline._load_ast_elements_for_tools = MagicMock(return_value={})

                    result = pipeline._build_tool_executor()

                    assert result == mock_executor
                    mock_tool_executor_class.assert_called_once()


class TestRunWorktreeSetup:
    """Tests for _run_worktree_setup method."""

    def test_run_worktree_setup_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test successful worktree setup."""
        mock_metadata.commit_range = "abc123..def456"

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager") as mock_wt_class:
                mock_wt_manager = MagicMock()
                mock_worktree_pair = MagicMock()
                mock_worktree_pair.base = Path("/test/worktrees/base")
                mock_worktree_pair.head = Path("/test/worktrees/head")
                mock_wt_manager.create_for_analysis.return_value = mock_worktree_pair
                mock_wt_class.return_value = mock_wt_manager

                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock Path.exists for worktree verification
                with patch("ggdes.pipeline.Path.exists", return_value=True):
                    with patch(
                        "ggdes.pipeline.Path.iterdir",
                        return_value=[Path("file1"), Path("file2")],
                    ):
                        with patch(
                            "ggdes.pipeline.Path.resolve",
                            return_value=Path("/test/worktrees/base"),
                        ):
                            result = pipeline._run_worktree_setup()

                            assert result is True
                            mock_wt_manager.create_for_analysis.assert_called_once_with(
                                "test_analysis_001",
                                base_commit="abc123",
                                head_commit="def456",
                            )

    def test_run_worktree_setup_invalid_range(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test worktree setup with invalid commit range."""
        mock_metadata.commit_range = "invalid_range"

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline._run_worktree_setup()

                assert result is False

    def test_run_worktree_setup_creation_failure(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test worktree setup when creation fails."""
        mock_metadata.commit_range = "abc123..def456"

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager") as mock_wt_class:
                mock_wt_manager = MagicMock()
                mock_wt_manager.create_for_analysis.side_effect = Exception(
                    "Creation failed"
                )
                mock_wt_class.return_value = mock_wt_manager

                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline._run_worktree_setup()

                assert result is False

    def test_run_worktree_setup_creation_failure(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test worktree setup when creation fails."""
        mock_metadata.commit_range = "abc123..def456"

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager") as mock_wt_class:
                mock_wt_manager = MagicMock()
                mock_wt_manager.create_for_analysis.side_effect = Exception(
                    "Creation failed"
                )
                mock_wt_class.return_value = mock_wt_manager

                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline._run_worktree_setup()

                assert result is False


class TestRunGitAnalysis:
    """Tests for _run_git_analysis method."""

    def test_run_git_analysis_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test successful git analysis stage."""
        mock_metadata.commit_range = "abc123..def456"
        mock_metadata.focus_commits = None
        mock_metadata.storage_policy = StoragePolicy.SUMMARY
        mock_metadata.user_context = None

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock InputValidator
                with patch(
                    "ggdes.validation.validators.InputValidator"
                ) as mock_validator_class:
                    mock_validator = MagicMock()
                    mock_validation_result = MagicMock()
                    mock_validation_result.passed = True
                    mock_validation_result.errors = []
                    mock_validation_result.warnings = []
                    mock_validator.validate_commit_range.return_value = (
                        mock_validation_result
                    )
                    mock_validator_class.return_value = mock_validator

                    # Mock GitAnalyzer
                    with patch("ggdes.pipeline.GitAnalyzer") as mock_analyzer_class:
                        mock_analyzer = MagicMock()
                        mock_summary = MagicMock()
                        mock_summary.files_changed = []
                        mock_summary.change_type = "feature"
                        mock_summary.impact = "high"
                        mock_summary.model_dump.return_value = {}
                        mock_analyzer.analyze = AsyncMock(return_value=mock_summary)
                        mock_analyzer_class.return_value = mock_analyzer

                        with patch("ggdes.pipeline.asyncio.run") as mock_asyncio_run:
                            mock_asyncio_run.return_value = mock_summary

                            with patch("ggdes.pipeline.Path.mkdir"):
                                with patch("ggdes.pipeline.Path.write_text"):
                                    result = pipeline._run_git_analysis()

                                    assert result is True


class TestRunSemanticDiff:
    """Tests for _run_semantic_diff method."""

    def test_run_semantic_diff_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test successful semantic diff stage."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/test/worktrees/base",
            head="/test/worktrees/head",
        )
        mock_metadata.commit_range = "abc123..def456"

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock _get_changed_files_from_analysis
                pipeline._get_changed_files_from_analysis = MagicMock(
                    return_value=["src/main.py"]
                )

                # Mock SemanticDiffAnalyzer
                with patch(
                    "ggdes.semantic_diff.SemanticDiffAnalyzer"
                ) as mock_analyzer_class:
                    mock_analyzer = MagicMock()
                    mock_result = MagicMock()
                    mock_result.semantic_changes = []
                    mock_result.breaking_changes = []
                    mock_result.behavioral_changes = []
                    mock_result.refactoring_changes = []
                    mock_result.documentation_changes = []
                    mock_result.test_changes = []
                    mock_result.performance_changes = []
                    mock_result.dependency_changes = []
                    mock_result.has_breaking_changes = False
                    mock_result.total_impact_score = 0.0
                    mock_analyzer.analyze.return_value = mock_result
                    mock_analyzer_class.return_value = mock_analyzer

                    with patch("ggdes.semantic_diff.save_semantic_diff"):
                        with patch("ggdes.pipeline.Path.mkdir"):
                            result = pipeline._run_semantic_diff()

                            assert result is True

    def test_run_semantic_diff_no_worktrees(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test semantic diff fails when worktrees not set up."""
        mock_metadata.worktrees = None

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                result = pipeline._run_semantic_diff()

                assert result is False

    def test_run_semantic_diff_no_changed_files(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test semantic diff succeeds when no changed files (nothing to analyze)."""
        mock_metadata.worktrees = WorktreeInfo(
            base="/test/worktrees/base",
            head="/test/worktrees/head",
        )

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock empty changed files
                pipeline._get_changed_files_from_analysis = MagicMock(return_value=[])

                result = pipeline._run_semantic_diff()

                assert result is True  # Should succeed (nothing to do)


class TestLoadAstElementsForTools:
    """Tests for _load_ast_elements_for_tools method."""

    def test_load_ast_elements_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test loading AST elements successfully."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                # Mock ast_head directory with JSON files
                mock_ast_data = {
                    "file_path": "src/main.py",
                    "elements": [
                        {"name": "func1", "type": "function"},
                        {"name": "Class1", "type": "class"},
                    ],
                }

                # Create a mock for the ast_head path
                mock_json_file = MagicMock()
                mock_json_file.stem = "src_main.py"
                mock_json_file.read_text.return_value = json.dumps(mock_ast_data)

                mock_ast_head_path = MagicMock()
                mock_ast_head_path.exists.return_value = True
                mock_ast_head_path.glob.return_value = [mock_json_file]

                # Mock get_analysis_path to return a path that supports / operator
                mock_base_path = MagicMock()
                mock_base_path.__truediv__ = MagicMock(return_value=mock_ast_head_path)
                mock_kb_instance.get_analysis_path.return_value = mock_base_path

                result = pipeline._load_ast_elements_for_tools()

                assert "src/main.py" in result
                assert len(result["src/main.py"]) == 2

    def test_load_ast_elements_no_directory(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test loading AST elements when directory doesn't exist."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.Path.exists", return_value=False):
                    result = pipeline._load_ast_elements_for_tools()

                    assert result == {}


class TestGetChangedFilesFromAnalysis:
    """Tests for _get_changed_files_from_analysis method."""

    def test_get_changed_files_success(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test getting changed files from analysis."""
        mock_analysis_data = {
            "files_changed": [
                {"path": "src/main.py", "change_type": "modified"},
                {"path": "tests/test.py", "change_type": "added"},
            ]
        }

        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            # Return a MagicMock for path that supports / operator and exists()
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.__truediv__ = MagicMock(return_value=mock_path)
            mock_kb_instance.get_analysis_path.return_value = mock_path
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with (
                    patch(
                        "builtins.open",
                        mock_open(read_data=json.dumps(mock_analysis_data)),
                    ),
                    patch(
                        "ggdes.pipeline.json.loads",
                        return_value=mock_analysis_data,
                    ),
                ):
                    result = pipeline._get_changed_files_from_analysis()

                    assert result == ["src/main.py", "tests/test.py"]

    def test_get_changed_files_no_file(
        self, mock_config: GGDesConfig, mock_metadata: AnalysisMetadata
    ) -> None:
        """Test getting changed files when analysis file doesn't exist."""
        with patch("ggdes.pipeline.KnowledgeBaseManager") as mock_kb_class:
            mock_kb_instance = MagicMock()
            mock_kb_instance.load_metadata.return_value = mock_metadata
            mock_kb_instance.get_analysis_path.return_value = Path(
                "/test/kb/test_analysis_001"
            )
            mock_kb_class.return_value = mock_kb_instance

            with patch("ggdes.pipeline.WorktreeManager"):
                pipeline = AnalysisPipeline(mock_config, "test_analysis_001")

                with patch("ggdes.pipeline.Path.exists", return_value=False):
                    result = pipeline._get_changed_files_from_analysis()

                    assert result == []
