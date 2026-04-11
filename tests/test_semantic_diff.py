"""Tests for the semantic_diff module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ggdes.semantic_diff import (
    SemanticChange,
    SemanticChangeType,
    SemanticDiffAnalyzer,
    SemanticDiffResult,
    save_semantic_diff,
)


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config for testing."""
    return MagicMock()


@pytest.fixture
def sample_python_code_base() -> str:
    """Create sample Python code for base version."""
    return '''
"""Module docstring."""

def old_function(x, y):
    """Old function docstring."""
    if x > 0:
        return x + y
    return y

class OldClass:
    """Old class docstring."""
    
    def method(self, arg):
        """Method docstring."""
        return arg * 2
'''


@pytest.fixture
def sample_python_code_head() -> str:
    """Create sample Python code for head version with changes."""
    return '''
"""Module docstring."""

def new_function(x, y, z):
    """New function with added parameter."""
    if x > 0:
        if z > 0:
            return x + y + z
    return y

def old_function(x, y):
    """Old function docstring - updated."""
    try:
        if x > 0:
            return x + y
    except Exception:
        return 0
    return y

class NewClass:
    """New class added."""
    pass
'''


@pytest.fixture
def temp_worktrees(tmp_path: Path) -> tuple[Path, Path]:
    """Create temporary worktree directories with sample files."""
    base_path = tmp_path / "base"
    head_path = tmp_path / "head"
    base_path.mkdir()
    head_path.mkdir()
    return base_path, head_path


class TestSemanticDiffAnalyzer:
    """Tests for SemanticDiffAnalyzer class."""

    def test_initialization(self, mock_config: MagicMock) -> None:
        """Test that SemanticDiffAnalyzer initializes correctly."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        assert analyzer.config == mock_config

    def test_analyze_with_changed_files(
        self,
        mock_config: MagicMock,
        temp_worktrees: tuple[Path, Path],
        sample_python_code_base: str,
        sample_python_code_head: str,
    ) -> None:
        """Test analyze method with mock files."""
        base_path, head_path = temp_worktrees

        # Create sample files
        base_file = base_path / "test.py"
        head_file = head_path / "test.py"
        base_file.write_text(sample_python_code_base)
        head_file.write_text(sample_python_code_head)

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=["test.py"],
            )

        assert isinstance(result, SemanticDiffResult)
        assert result.base_commit == "abc123"
        assert result.head_commit == "def456"
        assert len(result.semantic_changes) > 0

    def test_analyze_file_not_in_both(
        self,
        mock_config: MagicMock,
        temp_worktrees: tuple[Path, Path],
        sample_python_code_base: str,
    ) -> None:
        """Test analyze skips files not present in both versions."""
        base_path, head_path = temp_worktrees

        # Only create file in base
        base_file = base_path / "deleted.py"
        base_file.write_text(sample_python_code_base)

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=["deleted.py"],
            )

        # Should have no changes since file doesn't exist in head
        assert len(result.semantic_changes) == 0

    def test_analyze_empty_changed_files(
        self, mock_config: MagicMock, temp_worktrees: tuple[Path, Path]
    ) -> None:
        """Test analyze with empty changed files list."""
        base_path, head_path = temp_worktrees

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=[],
            )

        assert len(result.semantic_changes) == 0


class TestParseAstElements:
    """Tests for _parse_ast_elements method."""

    def test_parse_functions(self, mock_config: MagicMock) -> None:
        """Test parsing functions from Python code."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func1(a, b):
    pass

def func2(c):
    pass
"""
        elements = analyzer._parse_ast_elements(code, "test.py")

        func_names = [e["name"] for e in elements if e["type"] == "function"]
        assert "func1" in func_names
        assert "func2" in func_names

    def test_parse_classes(self, mock_config: MagicMock) -> None:
        """Test parsing classes from Python code."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
class Class1:
    pass

class Class2:
    def method(self):
        pass
"""
        elements = analyzer._parse_ast_elements(code, "test.py")

        class_names = [e["name"] for e in elements if e["type"] == "class"]
        assert "Class1" in class_names
        assert "Class2" in class_names

    def test_parse_function_parameters(self, mock_config: MagicMock) -> None:
        """Test parsing function parameters."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func_with_params(a, b, c=None):
    pass
"""
        elements = analyzer._parse_ast_elements(code, "test.py")

        func = next((e for e in elements if e["name"] == "func_with_params"), None)
        assert func is not None
        assert "a" in func["parameters"]
        assert "b" in func["parameters"]

    def test_parse_line_numbers(self, mock_config: MagicMock) -> None:
        """Test that line numbers are correctly parsed."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func1():
    pass

def func2():
    pass
"""
        elements = analyzer._parse_ast_elements(code, "test.py")

        for element in elements:
            assert "line_start" in element
            assert "line_end" in element
            assert element["line_start"] > 0

    def test_parse_syntax_error(self, mock_config: MagicMock) -> None:
        """Test handling of syntax errors."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = "def invalid syntax here"

        elements = analyzer._parse_ast_elements(code, "test.py")
        assert elements == []


class TestDetectSignatureChanges:
    """Tests for _detect_signature_changes method."""

    def test_detect_added_function(self, mock_config: MagicMock) -> None:
        """Test detecting added functions."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = ""
        head_code = """
def new_function(x, y):
    return x + y
"""

        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")

        added = [c for c in changes if c.change_type == SemanticChangeType.API_ADDED]
        assert len(added) == 1
        assert "new_function" in added[0].description
        assert added[0].confidence == 0.95

    def test_detect_removed_function(self, mock_config: MagicMock) -> None:
        """Test detecting removed functions."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def removed_function(x, y):
    return x + y
"""
        head_code = ""

        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")

        removed = [
            c for c in changes if c.change_type == SemanticChangeType.API_REMOVED
        ]
        assert len(removed) == 1
        assert "removed_function" in removed[0].description
        assert removed[0].impact_score == 1.0  # High impact for removal

    def test_detect_modified_signature(self, mock_config: MagicMock) -> None:
        """Test detecting modified function signatures."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func(a, b):
    return a + b
"""
        head_code = """
def func(a, b, c):
    return a + b + c
"""

        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")

        modified = [
            c for c in changes if c.change_type == SemanticChangeType.API_MODIFIED
        ]
        assert len(modified) == 1
        assert "c" in modified[0].description  # Should mention added param

    def test_detect_removed_parameter(self, mock_config: MagicMock) -> None:
        """Test detecting removed parameters (higher impact)."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func(a, b, c):
    return a + b + c
"""
        head_code = """
def func(a, b):
    return a + b
"""

        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")

        modified = [
            c for c in changes if c.change_type == SemanticChangeType.API_MODIFIED
        ]
        assert len(modified) == 1
        # Removing params should have higher impact
        assert modified[0].impact_score == 0.7


class TestDetectDocumentationChanges:
    """Tests for _detect_documentation_changes method."""

    def test_detect_added_docstrings(self, mock_config: MagicMock) -> None:
        """Test detecting added docstrings."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    pass
"""
        head_code = '''
def func():
    """New docstring added."""
    pass
'''

        changes = analyzer._detect_documentation_changes(
            base_code, head_code, "test.py"
        )

        assert len(changes) == 1
        assert changes[0].change_type == SemanticChangeType.DOCUMENTATION_ADDED
        assert "1 new docstring" in changes[0].description

    def test_detect_improved_documentation(self, mock_config: MagicMock) -> None:
        """Test detecting improved documentation (20% increase).

        Note: The code first checks if docstrings were added (head > base),
        and only if that's not true does it check for 20% improvement.
        Since we added docstrings, it will be detected as DOCUMENTATION_ADDED.
        """
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = '''
def func1():
    """Docstring."""
    pass

def func2():
    pass

def func3():
    pass

def func4():
    pass

def func5():
    pass
'''
        head_code = '''
def func1():
    """Docstring."""
    pass

def func2():
    """New docstring."""
    pass

def func3():
    """New docstring."""
    pass

def func4():
    """New docstring."""
    pass

def func5():
    """New docstring."""
    pass

def func6():
    """New docstring."""
    pass

def func7():
    """New docstring."""
    pass
'''

        changes = analyzer._detect_documentation_changes(
            base_code, head_code, "test.py"
        )

        # Since we added docstrings (1 -> 7), it will be detected as DOCUMENTATION_ADDED
        # not DOCUMENTATION_IMPROVED because the first condition catches it
        added = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.DOCUMENTATION_ADDED
        ]
        assert len(added) == 1
        assert "6 new docstring" in added[0].description

    def test_no_documentation_changes(self, mock_config: MagicMock) -> None:
        """Test when no documentation changes occur."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = '''
def func():
    """Docstring."""
    pass
'''

        changes = analyzer._detect_documentation_changes(code, code, "test.py")
        assert len(changes) == 0


class TestDetectBehavioralChanges:
    """Tests for _detect_control_flow_changes method (behavioral changes)."""

    def test_detect_control_flow_changes(self, mock_config: MagicMock) -> None:
        """Test detecting control flow structure changes."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    if True:
        pass
"""
        head_code = """
def func():
    if True:
        pass
    for i in range(10):
        pass
    while True:
        break
"""

        changes = analyzer._detect_control_flow_changes(base_code, head_code, "test.py")

        assert len(changes) == 1
        assert changes[0].change_type == SemanticChangeType.CONTROL_FLOW_CHANGE
        assert "1" in changes[0].description  # Base count
        assert "3" in changes[0].description  # Head count (if, for, while)

    def test_no_control_flow_changes(self, mock_config: MagicMock) -> None:
        """Test when control flow is unchanged."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func():
    if True:
        for i in range(10):
            pass
"""

        changes = analyzer._detect_control_flow_changes(code, code, "test.py")
        assert len(changes) == 0

    def test_insufficient_change(self, mock_config: MagicMock) -> None:
        """Test that small changes (< 2 structures) are not reported."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    if True:
        pass
"""
        head_code = """
def func():
    if True:
        pass
    for i in range(10):
        pass
"""

        changes = analyzer._detect_control_flow_changes(base_code, head_code, "test.py")
        # Only 1 structure difference, should not be reported
        assert len(changes) == 0


class TestDetectErrorHandlingChanges:
    """Tests for _detect_error_handling_changes method."""

    def test_detect_added_error_handling(self, mock_config: MagicMock) -> None:
        """Test detecting added try/except blocks."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    pass
"""
        head_code = """
def func():
    try:
        pass
    except Exception:
        pass
"""

        changes = analyzer._detect_error_handling_changes(
            base_code, head_code, "test.py"
        )

        assert len(changes) == 1
        assert changes[0].change_type == SemanticChangeType.ERROR_HANDLING_CHANGE
        assert "0" in changes[0].description  # Base try count
        assert "1" in changes[0].description  # Head try count

    def test_no_error_handling_changes(self, mock_config: MagicMock) -> None:
        """Test when error handling is unchanged."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func():
    try:
        pass
    except Exception:
        pass
"""

        changes = analyzer._detect_error_handling_changes(code, code, "test.py")
        assert len(changes) == 0


class TestSemanticDiffResult:
    """Tests for SemanticDiffResult class."""

    def test_initialization(self) -> None:
        """Test SemanticDiffResult initialization."""
        change = SemanticChange(
            change_type=SemanticChangeType.API_ADDED,
            description="Test change",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.9,
            impact_score=0.5,
        )

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[change],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        assert result.base_commit == "abc123"
        assert result.head_commit == "def456"
        assert len(result.semantic_changes) == 1

    def test_post_init_categorization(self) -> None:
        """Test that __post_init__ correctly categorizes changes."""
        api_removed = SemanticChange(
            change_type=SemanticChangeType.API_REMOVED,
            description="API removed",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.95,
            impact_score=1.0,
        )
        behavior_change = SemanticChange(
            change_type=SemanticChangeType.BEHAVIOR_CHANGE,
            description="Behavior changed",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.8,
            impact_score=0.6,
        )
        refactoring = SemanticChange(
            change_type=SemanticChangeType.REFACTORING,
            description="Refactored",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.9,
            impact_score=0.3,
        )
        doc_change = SemanticChange(
            change_type=SemanticChangeType.DOCUMENTATION_ADDED,
            description="Docs added",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.8,
            impact_score=0.2,
        )
        test_change = SemanticChange(
            change_type=SemanticChangeType.TEST_ADDED,
            description="Test added",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.9,
            impact_score=0.3,
        )
        perf_change = SemanticChange(
            change_type=SemanticChangeType.PERFORMANCE_OPTIMIZATION,
            description="Optimized",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.85,
            impact_score=0.5,
        )
        dep_change = SemanticChange(
            change_type=SemanticChangeType.DEPENDENCY_ADDED,
            description="Dependency added",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.9,
            impact_score=0.4,
        )

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[
                api_removed,
                behavior_change,
                refactoring,
                doc_change,
                test_change,
                perf_change,
                dep_change,
            ],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        # Check categorization
        # API_REMOVED and BEHAVIOR_CHANGE are both categorized as breaking changes
        assert len(result.breaking_changes) == 2  # API_REMOVED + BEHAVIOR_CHANGE
        assert len(result.behavioral_changes) == 1  # BEHAVIOR_CHANGE
        assert len(result.refactoring_changes) == 1  # REFACTORING
        assert len(result.documentation_changes) == 1  # DOCUMENTATION_ADDED
        assert len(result.test_changes) == 1  # TEST_ADDED
        assert len(result.performance_changes) == 1  # PERFORMANCE_OPTIMIZATION
        assert len(result.dependency_changes) == 1  # DEPENDENCY_ADDED

    def test_high_impact_breaking_change(self) -> None:
        """Test that high impact changes are marked as breaking."""
        high_impact = SemanticChange(
            change_type=SemanticChangeType.LOGIC_CHANGE,
            description="Logic changed",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.8,
            impact_score=0.9,  # High impact
        )

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[high_impact],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        # High impact score (>= 0.8) should be in breaking_changes
        assert len(result.breaking_changes) == 1

    def test_has_breaking_changes_property(self) -> None:
        """Test has_breaking_changes property."""
        change = SemanticChange(
            change_type=SemanticChangeType.API_REMOVED,
            description="API removed",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.95,
            impact_score=1.0,
        )

        result_with_bc = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[change],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        assert result_with_bc.has_breaking_changes is True

        result_without_bc = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        assert result_without_bc.has_breaking_changes is False

    def test_total_impact_score(self) -> None:
        """Test total_impact_score property."""
        changes = [
            SemanticChange(
                change_type=SemanticChangeType.API_ADDED,
                description=f"Change {i}",
                file_path="test.py",
                line_start=1,
                line_end=10,
                confidence=0.9,
                impact_score=2.0,  # Each contributes 2.0
            )
            for i in range(5)
        ]

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=changes,
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        # Total should be 10.0 (5 * 2.0), but capped at 10.0
        assert result.total_impact_score == 10.0

    def test_total_impact_score_empty(self) -> None:
        """Test total_impact_score with no changes."""
        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        assert result.total_impact_score == 0.0


class TestSaveSemanticDiff:
    """Tests for save_semantic_diff function."""

    def test_save_to_json(self, tmp_path: Path) -> None:
        """Test saving semantic diff result to JSON."""
        change = SemanticChange(
            change_type=SemanticChangeType.API_ADDED,
            description="Test change",
            file_path="test.py",
            line_start=1,
            line_end=10,
            confidence=0.9,
            impact_score=0.5,
            related_symbols=["func1"],
        )

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[change],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        output_path = tmp_path / "semantic_diff.json"
        save_semantic_diff(result, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())

        assert data["base_commit"] == "abc123"
        assert data["head_commit"] == "def456"
        assert data["summary"]["total_changes"] == 1
        assert data["summary"]["has_breaking_changes"] is False
        assert data["summary"]["total_impact_score"] == 0.5

        # Check semantic change details
        assert len(data["semantic_changes"]) == 1
        assert data["semantic_changes"][0]["change_type"] == "api_added"
        assert data["semantic_changes"][0]["confidence"] == 0.9

    def test_save_empty_result(self, tmp_path: Path) -> None:
        """Test saving empty semantic diff result."""
        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        output_path = tmp_path / "semantic_diff.json"
        save_semantic_diff(result, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["summary"]["total_changes"] == 0
        assert data["semantic_changes"] == []


class TestSemanticChangeType:
    """Tests for SemanticChangeType enum."""

    def test_all_change_types_exist(self) -> None:
        """Test that all expected change types exist."""
        expected_types = [
            # API Changes
            SemanticChangeType.API_ADDED,
            SemanticChangeType.API_REMOVED,
            SemanticChangeType.API_MODIFIED,
            SemanticChangeType.API_DEPRECATED,
            # Behavior Changes
            SemanticChangeType.BEHAVIOR_CHANGE,
            SemanticChangeType.LOGIC_CHANGE,
            SemanticChangeType.ALGORITHM_CHANGE,
            # Structure Changes
            SemanticChangeType.REFACTORING,
            SemanticChangeType.EXTRACTION,
            SemanticChangeType.INLINE,
            SemanticChangeType.RENAME,
            # Data Changes
            SemanticChangeType.SCHEMA_CHANGE,
            SemanticChangeType.TYPE_CHANGE,
            # Control Flow
            SemanticChangeType.CONTROL_FLOW_CHANGE,
            SemanticChangeType.ERROR_HANDLING_CHANGE,
            # Performance
            SemanticChangeType.PERFORMANCE_OPTIMIZATION,
            SemanticChangeType.MEMORY_OPTIMIZATION,
            # Documentation
            SemanticChangeType.DOCUMENTATION_ADDED,
            SemanticChangeType.DOCUMENTATION_IMPROVED,
            # Testing
            SemanticChangeType.TEST_ADDED,
            SemanticChangeType.TEST_MODIFIED,
            SemanticChangeType.COVERAGE_IMPROVED,
            # Dependencies
            SemanticChangeType.DEPENDENCY_ADDED,
            SemanticChangeType.DEPENDENCY_REMOVED,
            SemanticChangeType.DEPENDENCY_UPDATED,
        ]

        for change_type in expected_types:
            assert isinstance(change_type, SemanticChangeType)
            assert isinstance(change_type.value, str)

    def test_change_type_values(self) -> None:
        """Test that change type values are correct strings."""
        assert SemanticChangeType.API_ADDED.value == "api_added"
        assert SemanticChangeType.BEHAVIOR_CHANGE.value == "behavior_change"
        assert SemanticChangeType.REFACTORING.value == "refactoring"
        assert (
            SemanticChangeType.PERFORMANCE_OPTIMIZATION.value
            == "performance_optimization"
        )
