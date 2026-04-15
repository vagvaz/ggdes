"""Tests for the comparison module."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ggdes.comparison import (
    AnalysisComparator,
    AnalysisDiff,
    ComparisonResult,
    export_comparison,
    print_comparison,
)
from ggdes.kb import AnalysisMetadata
from ggdes.schemas import ChangeSummary, FileChange, TechnicalFact


@pytest.fixture
def mock_config(tmp_path: Path) -> MagicMock:
    """Create a mock config for testing."""
    config = MagicMock()
    config.paths.knowledge_base = str(tmp_path / "kb")
    return config


@pytest.fixture
def sample_metadata1() -> AnalysisMetadata:
    """Create sample metadata for analysis 1."""
    return AnalysisMetadata(
        id="analysis_001",
        name="Test Analysis 1",
        repo_path="/path/to/repo1",
        commit_range="abc123..def456",
        focus_commits=["abc123", "def456"],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_metadata2() -> AnalysisMetadata:
    """Create sample metadata for analysis 2."""
    return AnalysisMetadata(
        id="analysis_002",
        name="Test Analysis 2",
        repo_path="/path/to/repo2",
        commit_range="ghi789..jkl012",
        focus_commits=["ghi789", "jkl012", "mno345"],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_summary1() -> ChangeSummary:
    """Create sample change summary for analysis 1."""
    return ChangeSummary(
        commit_hash="def456",
        commit_range="abc123..def456",
        change_type="feature",
        description="Added new feature",
        intent="Improve user experience",
        impact="User interface",
        impact_level="medium",
        files_changed=[
            FileChange(
                path="src/main.py",
                change_type="modified",
                lines_added=50,
                lines_deleted=10,
                summary="Updated main logic",
            ),
            FileChange(
                path="src/utils.py",
                change_type="modified",
                lines_added=20,
                lines_deleted=5,
                summary="Added utility functions",
            ),
        ],
        breaking_changes=["Changed API signature"],
        dependencies_changed=["requests>=2.0.0"],
    )


@pytest.fixture
def sample_summary2() -> ChangeSummary:
    """Create sample change summary for analysis 2."""
    return ChangeSummary(
        commit_hash="jkl012",
        commit_range="ghi789..jkl012",
        change_type="bugfix",
        description="Fixed critical bug",
        intent="Fix security issue",
        impact="Authentication system",
        impact_level="high",
        files_changed=[
            FileChange(
                path="src/auth.py",
                change_type="modified",
                lines_added=30,
                lines_deleted=15,
                summary="Fixed auth bug",
            ),
            FileChange(
                path="src/main.py",
                change_type="modified",
                lines_added=10,
                lines_deleted=2,
                summary="Updated main logic",
            ),
        ],
        breaking_changes=["Changed API signature", "Removed deprecated endpoint"],
        dependencies_changed=["requests>=2.0.0", "cryptography>=3.0"],
    )


@pytest.fixture
def sample_facts1() -> list[TechnicalFact]:
    """Create sample technical facts for analysis 1."""
    return [
        TechnicalFact(
            fact_id="fact_001",
            category="api",
            source_elements=["main.py", "utils.py"],
            description="New API endpoint added for user management",
            source_file="src/main.py",
            confidence=0.95,
            verified=True,
        ),
        TechnicalFact(
            fact_id="fact_002",
            category="behavior",
            source_elements=["main.py"],
            description="User authentication flow updated",
            source_file="src/main.py",
            confidence=0.85,
            verified=True,
        ),
    ]


@pytest.fixture
def sample_facts2() -> list[TechnicalFact]:
    """Create sample technical facts for analysis 2."""
    return [
        TechnicalFact(
            fact_id="fact_001",
            category="api",
            source_elements=["main.py"],
            description="Updated API endpoint for user management with new features",
            source_file="src/main.py",
            confidence=0.95,
            verified=True,
        ),
        TechnicalFact(
            fact_id="fact_003",
            category="security",
            source_elements=["auth.py"],
            description="Security vulnerability fixed in auth module",
            source_file="src/auth.py",
            confidence=0.98,
            verified=True,
        ),
    ]


class TestAnalysisComparator:
    """Tests for AnalysisComparator class."""

    def test_initialization(self, mock_config: Any) -> None:
        """Test that AnalysisComparator initializes correctly."""
        comparator = AnalysisComparator(mock_config)
        assert comparator.config == mock_config
        assert comparator.kb_manager is not None

    def test_compare_analysis_not_found(self, mock_config: Any) -> None:
        """Test that compare raises ValueError when analysis not found."""
        comparator = AnalysisComparator(mock_config)

        with (
            patch.object(comparator.kb_manager, "load_metadata", return_value=None),
            pytest.raises(ValueError, match="Analysis not found: analysis_001"),
        ):
            comparator.compare("analysis_001", "analysis_002")

    def test_compare_success(
        self,
        mock_config: Any,
        sample_metadata1: AnalysisMetadata,
        sample_metadata2: AnalysisMetadata,
        sample_summary1: ChangeSummary,
        sample_summary2: ChangeSummary,
        sample_facts1: list[TechnicalFact],
        sample_facts2: list[TechnicalFact],
    ) -> None:
        """Test successful comparison of two analyses."""
        comparator = AnalysisComparator(mock_config)

        with patch.object(comparator.kb_manager, "load_metadata") as mock_load_metadata:
            mock_load_metadata.side_effect = [sample_metadata1, sample_metadata2]

            with patch.object(comparator, "_load_git_summary") as mock_load_summary:
                mock_load_summary.side_effect = [sample_summary1, sample_summary2]

                with patch.object(
                    comparator, "_load_technical_facts"
                ) as mock_load_facts:
                    mock_load_facts.side_effect = [sample_facts1, sample_facts2]

                    with patch.object(
                        comparator, "_load_semantic_diff"
                    ) as mock_load_semantic:
                        mock_load_semantic.return_value = None

                        result = comparator.compare("analysis_001", "analysis_002")

                        assert isinstance(result, ComparisonResult)
                        assert result.analysis1_id == "analysis_001"
                        assert result.analysis2_id == "analysis_002"
                        assert result.analysis1_name == "Test Analysis 1"
                        assert result.analysis2_name == "Test Analysis 2"


class TestCompareCommits:
    """Tests for _compare_commits method."""

    def test_compare_different_commit_ranges(
        self,
        mock_config: Any,
        sample_metadata1: AnalysisMetadata,
        sample_metadata2: AnalysisMetadata,
    ) -> None:
        """Test comparing analyses with different commit ranges."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_commits(sample_metadata1, sample_metadata2)

        # Should have commit_range diff and focus_commit diffs
        commit_range_diff = next((d for d in diffs if d.field == "commit_range"), None)
        assert commit_range_diff is not None
        assert commit_range_diff.analysis1_value == "abc123..def456"
        assert commit_range_diff.analysis2_value == "ghi789..jkl012"
        assert commit_range_diff.change_type == "modified"

    def test_compare_same_commit_ranges(self, mock_config: Any) -> None:
        """Test comparing analyses with same commit ranges."""
        comparator = AnalysisComparator(mock_config)

        metadata1 = AnalysisMetadata(
            id="analysis_001",
            name="Test 1",
            repo_path="/path/to/repo",
            commit_range="abc123..def456",
            focus_commits=["abc123", "def456"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        metadata2 = AnalysisMetadata(
            id="analysis_002",
            name="Test 2",
            repo_path="/path/to/repo",
            commit_range="abc123..def456",
            focus_commits=["abc123", "def456"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        diffs = comparator._compare_commits(metadata1, metadata2)

        # Should have no diffs when commit ranges are the same
        commit_range_diff = next((d for d in diffs if d.field == "commit_range"), None)
        assert commit_range_diff is None

    def test_compare_focus_commits_added(
        self,
        mock_config: Any,
        sample_metadata1: AnalysisMetadata,
        sample_metadata2: AnalysisMetadata,
    ) -> None:
        """Test detecting added focus commits."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_commits(sample_metadata1, sample_metadata2)

        # Should detect mno345 as added
        added_commit = next((d for d in diffs if d.analysis2_value == "mno345"), None)
        assert added_commit is not None
        assert added_commit.change_type == "added"

    def test_compare_focus_commits_removed(
        self,
        mock_config: Any,
        sample_metadata1: AnalysisMetadata,
        sample_metadata2: AnalysisMetadata,
    ) -> None:
        """Test detecting removed focus commits."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_commits(sample_metadata1, sample_metadata2)

        # Should detect abc123 and def456 as removed
        removed_commits = [d for d in diffs if d.change_type == "removed"]
        assert len(removed_commits) == 2
        removed_values = {d.analysis1_value for d in removed_commits}
        assert removed_values == {"abc123", "def456"}


class TestCompareFileChanges:
    """Tests for _compare_file_changes method."""

    def test_compare_files_added(
        self,
        mock_config: Any,
        sample_summary1: ChangeSummary,
        sample_summary2: ChangeSummary,
    ) -> None:
        """Test detecting added files."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_file_changes(sample_summary1, sample_summary2)

        # auth.py should be marked as added
        auth_diff = next((d for d in diffs if "auth.py" in d.field), None)
        assert auth_diff is not None
        assert auth_diff.change_type == "added"

    def test_compare_files_removed(
        self,
        mock_config: Any,
        sample_summary1: ChangeSummary,
        sample_summary2: ChangeSummary,
    ) -> None:
        """Test detecting removed files."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_file_changes(sample_summary1, sample_summary2)

        # utils.py should be marked as removed
        utils_diff = next((d for d in diffs if "utils.py" in d.field), None)
        assert utils_diff is not None
        assert utils_diff.change_type == "removed"

    def test_compare_files_modified(
        self,
        mock_config: Any,
        sample_summary1: ChangeSummary,
        sample_summary2: ChangeSummary,
    ) -> None:
        """Test detecting modified files with different metrics."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_file_changes(sample_summary1, sample_summary2)

        # main.py should be marked as modified (different line counts)
        main_diff = next((d for d in diffs if "main.py" in d.field), None)
        assert main_diff is not None
        assert main_diff.change_type == "modified"
        assert "+50/-10" in main_diff.analysis1_value
        assert "+10/-2" in main_diff.analysis2_value

    def test_compare_with_none_summary(
        self, mock_config: Any, sample_summary1: ChangeSummary
    ) -> None:
        """Test comparing with None summary."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_file_changes(sample_summary1, None)

        # All files from summary1 should be marked as removed
        assert len(diffs) == 2
        for diff in diffs:
            assert diff.change_type == "removed"


class TestCompareTechnicalFacts:
    """Tests for _compare_facts method."""

    def test_compare_facts_added(
        self,
        mock_config: Any,
        sample_facts1: list[TechnicalFact],
        sample_facts2: list[TechnicalFact],
    ) -> None:
        """Test detecting added facts."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_facts(sample_facts1, sample_facts2)

        # fact_003 should be marked as added
        fact3_diff = next((d for d in diffs if "fact_003" in d.field), None)
        assert fact3_diff is not None
        assert fact3_diff.change_type == "added"
        assert "Security vulnerability" in fact3_diff.analysis2_value

    def test_compare_facts_removed(
        self,
        mock_config: Any,
        sample_facts1: list[TechnicalFact],
        sample_facts2: list[TechnicalFact],
    ) -> None:
        """Test detecting removed facts."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_facts(sample_facts1, sample_facts2)

        # fact_002 should be marked as removed
        fact2_diff = next((d for d in diffs if "fact_002" in d.field), None)
        assert fact2_diff is not None
        assert fact2_diff.change_type == "removed"
        assert "User authentication" in fact2_diff.analysis1_value

    def test_compare_facts_modified(
        self,
        mock_config: Any,
        sample_facts1: list[TechnicalFact],
        sample_facts2: list[TechnicalFact],
    ) -> None:
        """Test detecting modified facts."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_facts(sample_facts1, sample_facts2)

        # fact_001 should be marked as modified (different source_elements)
        fact1_diff = next((d for d in diffs if "fact_001" in d.field), None)
        assert fact1_diff is not None
        assert fact1_diff.change_type == "modified"

    def test_compare_facts_same(self, mock_config: Any) -> None:
        """Test comparing identical facts."""
        comparator = AnalysisComparator(mock_config)

        facts = [
            TechnicalFact(
                fact_id="fact_001",
                category="api",
                source_elements=["main.py"],
                description="Test description",
                source_file="src/main.py",
                confidence=0.95,
                verified=True,
            )
        ]

        diffs = comparator._compare_facts(facts, facts)
        assert len(diffs) == 0


class TestCompareBreakingChanges:
    """Tests for _compare_breaking_changes method."""

    def test_compare_breaking_changes_added(
        self,
        mock_config: Any,
        sample_summary1: ChangeSummary,
        sample_summary2: ChangeSummary,
    ) -> None:
        """Test detecting added breaking changes."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_breaking_changes(sample_summary1, sample_summary2)

        # "Removed deprecated endpoint" should be marked as added
        added_bc = next(
            (d for d in diffs if "Removed deprecated" in d.analysis2_value), None
        )
        assert added_bc is not None
        assert added_bc.change_type == "added"

    def test_compare_breaking_changes_removed(self, mock_config: Any) -> None:
        """Test detecting removed breaking changes."""
        comparator = AnalysisComparator(mock_config)

        summary1 = ChangeSummary(
            commit_hash="abc123",
            change_type="feature",
            description="Test",
            intent="Test",
            impact="Test",
            breaking_changes=["Old breaking change"],
        )
        summary2 = ChangeSummary(
            commit_hash="def456",
            change_type="feature",
            description="Test",
            intent="Test",
            impact="Test",
            breaking_changes=[],
        )

        diffs = comparator._compare_breaking_changes(summary1, summary2)

        # "Old breaking change" should be marked as removed
        assert len(diffs) == 1
        assert diffs[0].change_type == "removed"
        assert "Old breaking change" in diffs[0].analysis1_value

    def test_compare_breaking_changes_same(
        self, mock_config: Any, sample_summary1: ChangeSummary
    ) -> None:
        """Test comparing identical breaking changes."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_breaking_changes(sample_summary1, sample_summary1)

        # No diffs when breaking changes are identical
        assert len(diffs) == 0


class TestSimilarityScore:
    """Tests for _compute_similarity method."""

    def test_similarity_identical(self, mock_config: Any) -> None:
        """Test similarity score for identical analyses."""
        comparator = AnalysisComparator(mock_config)

        # No diffs means identical
        similarity = comparator._compute_similarity([], [], [], [], [])
        assert similarity == 1.0

    def test_similarity_completely_different(self, mock_config: Any) -> None:
        """Test similarity score for completely different analyses."""
        comparator = AnalysisComparator(mock_config)

        diffs = [
            AnalysisDiff(
                field="test",
                analysis1_value="a",
                analysis2_value="b",
                change_type="modified",
            )
        ]

        similarity = comparator._compute_similarity(diffs, diffs, diffs, diffs, diffs)
        assert similarity == 0.0

    def test_similarity_partial(self, mock_config: Any) -> None:
        """Test similarity score for partially similar analyses."""
        comparator = AnalysisComparator(mock_config)

        same_diff = AnalysisDiff(
            field="same",
            analysis1_value="a",
            analysis2_value="a",
            change_type="same",
        )
        modified_diff = AnalysisDiff(
            field="modified",
            analysis1_value="a",
            analysis2_value="b",
            change_type="modified",
        )

        # 1 same out of 2 total = 0.5 similarity
        similarity = comparator._compute_similarity(
            [same_diff], [modified_diff], [], [], []
        )
        assert similarity == 0.5


class TestSemanticDiffComparison:
    """Tests for _compare_semantic_diff method."""

    def test_both_none(self, mock_config: Any) -> None:
        """Test when both semantic diffs are None."""
        comparator = AnalysisComparator(mock_config)
        diffs = comparator._compare_semantic_diff(None, None)
        assert len(diffs) == 0

    def test_first_none_second_present(self, mock_config: Any) -> None:
        """Test when first is None and second is present."""
        comparator = AnalysisComparator(mock_config)
        semantic_diff2 = {
            "semantic_changes": [{"type": "test"}],
            "summary": {"breaking_changes": 1},
        }

        diffs = comparator._compare_semantic_diff(None, semantic_diff2)

        assert len(diffs) == 1
        assert diffs[0].field == "semantic_diff"
        assert diffs[0].change_type == "added"
        assert "Present" in diffs[0].analysis2_value

    def test_first_present_second_none(self, mock_config: Any) -> None:
        """Test when first is present and second is None."""
        comparator = AnalysisComparator(mock_config)
        semantic_diff1 = {
            "semantic_changes": [{"type": "test"}],
            "summary": {"breaking_changes": 1},
        }

        diffs = comparator._compare_semantic_diff(semantic_diff1, None)

        assert len(diffs) == 1
        assert diffs[0].field == "semantic_diff"
        assert diffs[0].change_type == "removed"

    def test_breaking_changes_count_differs(self, mock_config: Any) -> None:
        """Test detecting different breaking changes counts."""
        comparator = AnalysisComparator(mock_config)
        semantic_diff1 = {"summary": {"breaking_changes": 1}}
        semantic_diff2 = {"summary": {"breaking_changes": 3}}

        diffs = comparator._compare_semantic_diff(semantic_diff1, semantic_diff2)

        bc_diff = next((d for d in diffs if d.field == "breaking_changes_count"), None)
        assert bc_diff is not None
        assert bc_diff.analysis1_value == "1"
        assert bc_diff.analysis2_value == "3"

    def test_impact_score_differs(self, mock_config: Any) -> None:
        """Test detecting different impact scores."""
        comparator = AnalysisComparator(mock_config)
        semantic_diff1 = {"summary": {"total_impact_score": 5.0}}
        semantic_diff2 = {"summary": {"total_impact_score": 8.5}}

        diffs = comparator._compare_semantic_diff(semantic_diff1, semantic_diff2)

        impact_diff = next((d for d in diffs if d.field == "total_impact_score"), None)
        assert impact_diff is not None
        assert impact_diff.analysis1_value == "5.0"
        assert impact_diff.analysis2_value == "8.5"

    def test_change_types_comparison_bug_fix(self, mock_config: Any) -> None:
        """Test the bug fix: verify summary2.get(change_type, 0) uses loop variable.

        This test verifies that the bug where `summary2.get(change_types, 0)`
        was using the list instead of the loop variable has been fixed.
        """
        comparator = AnalysisComparator(mock_config)

        # Create semantic diffs with different counts for each change type
        semantic_diff1 = {
            "summary": {
                "behavioral_changes": 2,
                "refactoring_changes": 0,
                "documentation_changes": 1,
                "test_changes": 0,
                "performance_changes": 3,
                "dependency_changes": 0,
            }
        }
        semantic_diff2 = {
            "summary": {
                "behavioral_changes": 5,  # Different from summary1
                "refactoring_changes": 1,  # Different from summary1
                "documentation_changes": 1,  # Same as summary1
                "test_changes": 2,  # Different from summary1
                "performance_changes": 1,  # Different from summary1
                "dependency_changes": 0,  # Same as summary1
            }
        }

        diffs = comparator._compare_semantic_diff(semantic_diff1, semantic_diff2)

        # Count how many change type diffs we have
        change_type_diffs = [
            d
            for d in diffs
            if d.field
            in [
                "behavioral_changes",
                "refactoring_changes",
                "documentation_changes",
                "test_changes",
                "performance_changes",
                "dependency_changes",
            ]
        ]

        # Should have diffs for behavioral, refactoring, test, and performance
        # documentation and dependency should not appear (they're the same)
        assert len(change_type_diffs) == 4

        # Verify each diff has correct values
        behavioral_diff = next(
            (d for d in change_type_diffs if d.field == "behavioral_changes"), None
        )
        assert behavioral_diff is not None
        assert behavioral_diff.analysis1_value == "2"
        assert behavioral_diff.analysis2_value == "5"

        refactoring_diff = next(
            (d for d in change_type_diffs if d.field == "refactoring_changes"), None
        )
        assert refactoring_diff is not None
        assert refactoring_diff.analysis1_value == "0"
        assert refactoring_diff.analysis2_value == "1"

        # Verify documentation is NOT in the diffs (same value)
        doc_diff = next(
            (d for d in change_type_diffs if d.field == "documentation_changes"), None
        )
        assert doc_diff is None


class TestExportComparison:
    """Tests for export_comparison function."""

    def test_export_to_json(self, tmp_path: Path) -> None:
        """Test exporting comparison result to JSON."""
        result = ComparisonResult(
            analysis1_id="analysis_001",
            analysis2_id="analysis_002",
            analysis1_name="Test 1",
            analysis2_name="Test 2",
            commit_diff=[
                AnalysisDiff(
                    field="commit_range",
                    analysis1_value="abc..def",
                    analysis2_value="ghi..jkl",
                    change_type="modified",
                )
            ],
            file_changes_diff=[],
            facts_diff=[],
            breaking_changes_diff=[],
            semantic_changes_diff=[],
            similarity_score=0.75,
        )

        output_path = tmp_path / "comparison.json"
        export_comparison(result, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["analysis1"]["id"] == "analysis_001"
        assert data["analysis2"]["id"] == "analysis_002"
        assert data["similarity_score"] == 0.75
        assert data["semantic_diff_available"] is False
        assert "exported_at" in data


class TestPrintComparison:
    """Tests for print_comparison function."""

    def test_print_comparison(self, capsys: pytest.CaptureFixture) -> None:
        """Test printing comparison result."""
        result = ComparisonResult(
            analysis1_id="analysis_001",
            analysis2_id="analysis_002",
            analysis1_name="Test Analysis 1",
            analysis2_name="Test Analysis 2",
            commit_diff=[
                AnalysisDiff(
                    field="commit_range",
                    analysis1_value="abc..def",
                    analysis2_value="ghi..jkl",
                    change_type="modified",
                )
            ],
            file_changes_diff=[
                AnalysisDiff(
                    field="file:main.py",
                    analysis1_value="+10/-5",
                    analysis2_value="+20/-10",
                    change_type="modified",
                )
            ],
            facts_diff=[],
            breaking_changes_diff=[],
            semantic_changes_diff=[],
            similarity_score=0.5,
        )

        # Should not raise any errors
        print_comparison(result)

        # Note: rich.console output may not be captured by capsys
        # but we verify the function runs without errors
