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
        """Test analyze detects deleted files."""
        base_path, head_path = temp_worktrees

        # Only create file in base (deleted file)
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

        # Should detect the deleted file and its elements
        assert len(result.semantic_changes) > 0
        removed = [
            c
            for c in result.semantic_changes
            if c.change_type == SemanticChangeType.API_REMOVED
        ]
        assert len(removed) > 0

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
        assert added[0].confidence >= 0.8  # Dynamic scoring, should be high

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
        assert (
            removed[0].impact_score >= 0.7
        )  # Dynamic scoring, should be high for removal

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
        # Removing params should have higher impact (dynamic scoring)
        assert modified[0].impact_score >= 0.5


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
        assert "docstring" in changes[0].description.lower()

    def test_detect_improved_documentation(self, mock_config: MagicMock) -> None:
        """Test detecting improved documentation (20% increase).

        With the fixed logic: DOCUMENTATION_ADDED only when base=0→head>0.
        DOCUMENTATION_IMPROVED when base>0 and head increased by 20%+.
        This test has base=1, head=7, so it should be DOCUMENTATION_IMPROVED.
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

        # With fixed logic: base=1, head=7 → DOCUMENTATION_IMPROVED (20%+ increase)
        improved = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.DOCUMENTATION_IMPROVED
        ]
        assert len(improved) == 1
        assert "1 → 7" in improved[0].description

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


class TestNewAndDeletedFiles:
    """Tests for new and deleted file analysis."""

    def test_analyze_new_file(
        self,
        mock_config: MagicMock,
        temp_worktrees: tuple[Path, Path],
    ) -> None:
        """Test that newly added files are analyzed."""
        base_path, head_path = temp_worktrees

        # Create file only in head (new file)
        head_file = head_path / "new_module.py"
        head_file.write_text("""
def new_function(x, y):
    '''A new function.'''
    return x + y

class NewClass:
    '''A new class.'''
    pass
""")

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=["new_module.py"],
            )

        # Should detect the new file and its elements
        assert len(result.semantic_changes) > 0
        added = [
            c
            for c in result.semantic_changes
            if c.change_type == SemanticChangeType.API_ADDED
        ]
        assert len(added) > 0
        # Should have after_snippet populated
        for change in added:
            if change.after_snippet:
                assert (
                    "new_function" in change.after_snippet
                    or "NewClass" in change.after_snippet
                )
                break

    def test_analyze_deleted_file(
        self,
        mock_config: MagicMock,
        temp_worktrees: tuple[Path, Path],
    ) -> None:
        """Test that deleted files are analyzed."""
        base_path, head_path = temp_worktrees

        # Create file only in base (deleted file)
        base_file = base_path / "old_module.py"
        base_file.write_text("""
def old_function(x, y):
    '''An old function.'''
    return x + y
""")

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=["old_module.py"],
            )

        # Should detect the deleted file
        assert len(result.semantic_changes) > 0
        removed = [
            c
            for c in result.semantic_changes
            if c.change_type == SemanticChangeType.API_REMOVED
        ]
        assert len(removed) > 0
        # Should have before_snippet populated
        for change in removed:
            if change.before_snippet:
                assert "old_function" in change.before_snippet
                break

    def test_deleted_file_is_breaking_change(
        self,
        mock_config: MagicMock,
        temp_worktrees: tuple[Path, Path],
    ) -> None:
        """Test that deleted files are classified as breaking changes."""
        base_path, head_path = temp_worktrees

        base_file = base_path / "api_module.py"
        base_file.write_text("""
def public_api(x):
    return x * 2
""")

        analyzer = SemanticDiffAnalyzer(mock_config)

        with patch("ggdes.semantic_diff.console.print"):
            result = analyzer.analyze(
                base_path=base_path,
                head_path=head_path,
                base_commit="abc123",
                head_commit="def456",
                changed_files=["api_module.py"],
            )

        assert result.has_breaking_changes
        assert len(result.breaking_changes) > 0


class TestSnippetPopulation:
    """Tests for before/after snippet population."""

    def test_snippets_populated_for_added_function(
        self, mock_config: MagicMock
    ) -> None:
        """Test that after_snippet is populated for added functions."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = ""
        head_code = """
def added_func(a, b):
    return a + b
"""
        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")
        added = [c for c in changes if c.change_type == SemanticChangeType.API_ADDED]
        assert len(added) == 1
        assert added[0].after_snippet is not None
        assert "added_func" in added[0].after_snippet
        assert added[0].before_snippet is None

    def test_snippets_populated_for_removed_function(
        self, mock_config: MagicMock
    ) -> None:
        """Test that before_snippet is populated for removed functions."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def removed_func(a, b):
    return a + b
"""
        head_code = ""

        changes = analyzer._detect_signature_changes(base_code, head_code, "test.py")
        removed = [
            c for c in changes if c.change_type == SemanticChangeType.API_REMOVED
        ]
        assert len(removed) == 1
        assert removed[0].before_snippet is not None
        assert "removed_func" in removed[0].before_snippet
        assert removed[0].after_snippet is None

    def test_snippets_populated_for_modified_function(
        self, mock_config: MagicMock
    ) -> None:
        """Test that both snippets are populated for modified functions."""
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
        assert modified[0].before_snippet is not None
        assert modified[0].after_snippet is not None

    def test_save_includes_snippets(self, tmp_path: Path) -> None:
        """Test that save_semantic_diff includes snippet fields in JSON."""
        change = SemanticChange(
            change_type=SemanticChangeType.API_ADDED,
            description="New function added",
            file_path="test.py",
            line_start=1,
            line_end=5,
            confidence=0.9,
            impact_score=0.5,
            before_snippet=None,
            after_snippet="def new_func():\n    pass",
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

        data = json.loads(output_path.read_text())
        assert "before_snippet" in data["semantic_changes"][0]
        assert "after_snippet" in data["semantic_changes"][0]
        assert (
            data["semantic_changes"][0]["after_snippet"] == "def new_func():\n    pass"
        )


class TestDynamicScoring:
    """Tests for dynamic confidence and impact scoring."""

    def test_calculate_impact_score_api_added(self, mock_config: MagicMock) -> None:
        """Test impact score for API added."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        score = analyzer._calculate_impact_score(
            change_type=SemanticChangeType.API_ADDED,
            element_type="function",
        )
        assert 0.0 <= score <= 1.0
        # Added functions should have moderate impact
        assert score >= 0.2

    def test_calculate_impact_score_api_removed(self, mock_config: MagicMock) -> None:
        """Test impact score for API removed."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        score = analyzer._calculate_impact_score(
            change_type=SemanticChangeType.API_REMOVED,
            element_type="function",
        )
        assert 0.0 <= score <= 1.0
        # Removed functions should have high impact
        assert score >= 0.7

    def test_calculate_impact_score_class_removal(self, mock_config: MagicMock) -> None:
        """Test that removing a class has higher impact than removing a function."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        func_score = analyzer._calculate_impact_score(
            change_type=SemanticChangeType.API_REMOVED,
            element_type="function",
        )
        class_score = analyzer._calculate_impact_score(
            change_type=SemanticChangeType.API_REMOVED,
            element_type="class",
        )
        assert class_score > func_score

    def test_calculate_confidence_with_source(self, mock_config: MagicMock) -> None:
        """Test confidence calculation with source available."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        confidence = analyzer._calculate_confidence(
            has_source=True,
            change_type=SemanticChangeType.API_ADDED,
        )
        assert 0.0 <= confidence <= 1.0
        assert confidence >= 0.8

    def test_calculate_confidence_without_source(self, mock_config: MagicMock) -> None:
        """Test confidence calculation without source."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        confidence_with = analyzer._calculate_confidence(
            has_source=True,
            change_type=SemanticChangeType.API_ADDED,
        )
        confidence_without = analyzer._calculate_confidence(
            has_source=False,
            change_type=SemanticChangeType.API_ADDED,
        )
        assert confidence_without < confidence_with


class TestASTErrorHandlingDetection:
    """Tests for AST-based error handling detection."""

    def test_count_try_blocks(self, mock_config: MagicMock) -> None:
        """Test counting try/except blocks using AST."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func():
    try:
        pass
    except Exception:
        pass

    try:
        pass
    except ValueError:
        pass
"""
        count = analyzer._count_try_blocks(code)
        assert count == 2

    def test_count_try_blocks_empty(self, mock_config: MagicMock) -> None:
        """Test counting try/except blocks with no try blocks."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = """
def func():
    if True:
        pass
    for i in range(10):
        pass
"""
        count = analyzer._count_try_blocks(code)
        assert count == 0

    def test_count_try_blocks_syntax_error(self, mock_config: MagicMock) -> None:
        """Test handling of syntax errors in try block counting."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        code = "def invalid syntax"
        count = analyzer._count_try_blocks(code)
        assert count == 0

    def test_detect_error_handling_improved(self, mock_config: MagicMock) -> None:
        """Test detecting improved error handling using AST."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    return 1 / 0
"""
        head_code = """
def func():
    try:
        return 1 / 0
    except ZeroDivisionError:
        return 0
"""
        changes = analyzer._detect_error_handling_changes(
            base_code, head_code, "test.py"
        )
        error_changes = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.ERROR_HANDLING_CHANGE
        ]
        assert len(error_changes) == 1
        assert "Improved" in error_changes[0].description

    def test_detect_error_handling_reduced(self, mock_config: MagicMock) -> None:
        """Test detecting reduced error handling."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    try:
        return 1 / 0
    except ZeroDivisionError:
        return 0
"""
        head_code = """
def func():
    return 1 / 0
"""
        changes = analyzer._detect_error_handling_changes(
            base_code, head_code, "test.py"
        )
        error_changes = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.ERROR_HANDLING_CHANGE
        ]
        assert len(error_changes) == 1
        assert "Reduced" in error_changes[0].description

    def test_error_handling_no_false_positives(self, mock_config: MagicMock) -> None:
        """Test that string 'try:' in comments/strings doesn't trigger false positives."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    pass
"""
        head_code = """
def func():
    # This is a comment with try: in it
    message = "Remember to try: something"
    pass
"""
        changes = analyzer._detect_error_handling_changes(
            base_code, head_code, "test.py"
        )
        error_changes = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.ERROR_HANDLING_CHANGE
        ]
        # Should NOT detect error handling change since there are no actual try blocks
        assert len(error_changes) == 0


class TestDocumentationDetectionFix:
    """Tests for fixed documentation detection logic."""

    def test_documentation_added_when_base_zero(self, mock_config: MagicMock) -> None:
        """Test DOCUMENTATION_ADDED when going from 0 to >0 docstrings."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    pass
"""
        head_code = """
def func():
    '''Added docstring.'''
    pass
"""
        changes = analyzer._detect_documentation_changes(
            base_code, head_code, "test.py"
        )
        doc_added = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.DOCUMENTATION_ADDED
        ]
        assert len(doc_added) == 1

    def test_documentation_improved_when_base_positive(
        self, mock_config: MagicMock
    ) -> None:
        """Test DOCUMENTATION_IMPROVED when base > 0 and head increased by 20%+."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func1():
    '''Doc 1.'''
    pass

def func2():
    '''Doc 2.'''
    pass
"""
        head_code = """
def func1():
    '''Doc 1.'''
    pass

def func2():
    '''Doc 2.'''
    pass

def func3():
    '''Doc 3.'''
    pass
"""
        changes = analyzer._detect_documentation_changes(
            base_code, head_code, "test.py"
        )
        doc_improved = [
            c
            for c in changes
            if c.change_type == SemanticChangeType.DOCUMENTATION_IMPROVED
        ]
        assert len(doc_improved) == 1

    def test_no_doc_change_when_same(self, mock_config: MagicMock) -> None:
        """Test no documentation change when counts are equal."""
        analyzer = SemanticDiffAnalyzer(mock_config)
        base_code = """
def func():
    '''Doc.'''
    pass
"""
        head_code = """
def func():
    '''Different doc.'''
    pass
"""
        changes = analyzer._detect_documentation_changes(
            base_code, head_code, "test.py"
        )
        assert len(changes) == 0
