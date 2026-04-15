"""Comprehensive tests for the GGDes validation module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ggdes.schemas import CodeElement, CodeElementType, TechnicalFact
from ggdes.validation import (
    ASTValidator,
    CodeReference,
    CodeReferenceValidator,
    InputValidator,
    ReferenceValidationResult,
    SchemaValidator,
    ValidationPipeline,
    ValidationResult,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary repository structure."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create some source files
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("""
def main():
    print("Hello")
    
class MyClass:
    def method(self):
        pass
""")
    (repo / "src" / "utils.py").write_text("""
def helper():
    return 42
""")

    return repo


@pytest.fixture
def sample_diff_content() -> str:
    """Sample git diff content for testing."""
    return """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,5 @@
 def main():
-    print("Hello")
+    print("Hello World")
     
 class MyClass:
     def method(self):
-        pass
+        return True

diff --git a/src/utils.py b/src/utils.py
index 1234567..abcdefg 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,4 @@
 def helper():
+    x = 1
     return 42
"""


@pytest.fixture
def sample_code_elements() -> dict[str, dict[str, object]]:
    """Sample code elements for testing."""
    return {
        "main": {
            "type": "function",
            "file": "src/main.py",
            "line": 1,
        },
        "MyClass": {
            "type": "class",
            "file": "src/main.py",
            "line": 4,
        },
        "method": {
            "type": "method",
            "file": "src/main.py",
            "line": 5,
        },
        "helper": {
            "type": "function",
            "file": "src/utils.py",
            "line": 1,
        },
    }


@pytest.fixture
def sample_code_element_objects() -> list[CodeElement]:
    """Sample CodeElement objects for ASTValidator testing."""
    return [
        CodeElement(
            name="main",
            element_type=CodeElementType.FUNCTION,
            signature="def main()",
            start_line=1,
            end_line=3,
            file_path="src/main.py",
        ),
        CodeElement(
            name="MyClass",
            element_type=CodeElementType.CLASS,
            start_line=4,
            end_line=7,
            file_path="src/main.py",
        ),
        CodeElement(
            name="method",
            element_type=CodeElementType.METHOD,
            signature="def method(self)",
            start_line=5,
            end_line=6,
            file_path="src/main.py",
            parent="MyClass",
        ),
        CodeElement(
            name="helper",
            element_type=CodeElementType.FUNCTION,
            signature="def helper()",
            start_line=1,
            end_line=2,
            file_path="src/utils.py",
        ),
    ]


@pytest.fixture
def sample_technical_facts() -> list[TechnicalFact]:
    """Sample TechnicalFact objects for testing."""
    return [
        TechnicalFact(
            fact_id="fact_1",
            category="api",
            source_elements=["main", "MyClass"],
            description="Main function creates MyClass instance",
            source_file="src/main.py",
            confidence=0.9,
        ),
        TechnicalFact(
            fact_id="fact_2",
            category="behavior",
            source_elements=["helper"],
            description="Helper function returns constant",
            source_file="src/utils.py",
            confidence=0.3,  # Low confidence
        ),
        TechnicalFact(
            fact_id="fact_3",
            category="api",
            source_elements=["nonexistent_function"],  # Invalid reference
            description="References a non-existent function",
            source_file="src/main.py",
            confidence=0.8,
        ),
    ]


@pytest.fixture
def mock_llm_provider() -> MagicMock:
    """Create a mock LLM provider."""
    mock = MagicMock()
    mock.generate.return_value = "Corrected output with valid references"
    return mock


# =============================================================================
# CodeReferenceValidator Tests
# =============================================================================


class TestCodeReferenceValidator:
    """Tests for CodeReferenceValidator class."""

    def test_initialization_with_all_params(
        self,
        temp_repo: Path,
        sample_code_elements: dict[str, dict[str, object]],
        sample_diff_content: str,
    ) -> None:
        """Test initialization with all parameters."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py", "src/utils.py"],
            code_elements=sample_code_elements,
            diff_content=sample_diff_content,
        )

        assert validator.repo_path == temp_repo
        assert validator.changed_files == {"src/main.py", "src/utils.py"}
        assert validator.code_elements == sample_code_elements
        assert validator.diff_content == sample_diff_content
        assert "src/main.py" in validator.diff_snippets
        assert "src/utils.py" in validator.diff_snippets

    def test_initialization_with_defaults(self, temp_repo: Path) -> None:
        """Test initialization with default values."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        assert validator.repo_path == temp_repo
        assert validator.changed_files == set()
        assert validator.code_elements == {}
        assert validator.diff_content == ""
        assert validator.diff_snippets == {}

    def test_initialization_with_none_values(self, temp_repo: Path) -> None:
        """Test initialization with explicit None values."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=None,
            code_elements=None,
            diff_content=None,
        )

        assert validator.changed_files == set()
        assert validator.code_elements == {}
        assert validator.diff_content == ""

    def test_extract_diff_snippets(
        self, temp_repo: Path, sample_diff_content: str
    ) -> None:
        """Test extraction of diff snippets."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            diff_content=sample_diff_content,
        )

        snippets = validator.diff_snippets
        assert "src/main.py" in snippets
        assert "src/utils.py" in snippets
        # Check that added lines are captured
        assert any("Hello World" in line for line in snippets["src/main.py"])
        assert any("x = 1" in line for line in snippets["src/utils.py"])

    def test_extract_diff_snippets_empty_diff(self, temp_repo: Path) -> None:
        """Test extraction with empty diff content."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            diff_content="",
        )

        assert validator.diff_snippets == {}

    def test_normalize_code(self, temp_repo: Path) -> None:
        """Test code normalization."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        # Test whitespace normalization
        assert validator._normalize_code("  hello   world  ") == "hello world"
        # Test case normalization
        assert validator._normalize_code("HELLO World") == "hello world"
        # Test multiple spaces
        assert validator._normalize_code("a    b") == "a b"

    def test_snippet_in_diff_found(
        self, temp_repo: Path, sample_diff_content: str
    ) -> None:
        """Test finding snippet in diff."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            diff_content=sample_diff_content,
        )

        assert validator._snippet_in_diff("src/main.py", "Hello World")
        assert validator._snippet_in_diff("src/utils.py", "x = 1")

    def test_snippet_in_diff_not_found(
        self, temp_repo: Path, sample_diff_content: str
    ) -> None:
        """Test when snippet is not in diff."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            diff_content=sample_diff_content,
        )

        assert not validator._snippet_in_diff("src/main.py", "NonExistentCode")
        assert not validator._snippet_in_diff("nonexistent.py", "Hello World")

    def test_extract_references_file_paths(self, temp_repo: Path) -> None:
        """Test extracting file path references."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = 'The file `src/main.py` contains the main function. Also see "src/utils.py".'
        references = validator._extract_references(text)

        file_refs = [r for r in references if r.reference_type == "file"]
        assert len(file_refs) == 2
        assert any(r.file_path == "src/main.py" for r in file_refs)
        assert any(r.file_path == "src/utils.py" for r in file_refs)

    def test_extract_references_with_line_numbers(self, temp_repo: Path) -> None:
        """Test extracting file references with line numbers."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = "Check `src/main.py:42` for the issue."
        references = validator._extract_references(text)

        file_refs = [r for r in references if r.file_path == "src/main.py"]
        assert len(file_refs) == 1
        assert file_refs[0].line_number == 42

    def test_extract_references_function_calls(self, temp_repo: Path) -> None:
        """Test extracting function call references."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = "The main() function calls helper() to get data."
        references = validator._extract_references(text)

        func_refs = [r for r in references if r.reference_type == "function"]
        assert any(r.code_snippet == "main" for r in func_refs)
        assert any(r.code_snippet == "helper" for r in func_refs)

    def test_extract_references_skips_keywords(self, temp_repo: Path) -> None:
        """Test that common keywords are not extracted as functions."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = "if True: print(len(range(10)))"
        references = validator._extract_references(text)

        func_refs = [r for r in references if r.reference_type == "function"]
        func_names = [r.code_snippet for r in func_refs]

        # Keywords should be skipped
        assert "if" not in func_names
        assert "print" not in func_names
        assert "len" not in func_names
        assert "range" not in func_names

    def test_extract_references_class_names(self, temp_repo: Path) -> None:
        """Test extracting class name references."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        # Pattern requires ( or . after class name
        text = "The MyClass() object is created. Call SomeClass.method() for help."
        references = validator._extract_references(text)

        class_refs = [r for r in references if r.reference_type == "class"]
        assert any(r.code_snippet == "MyClass" for r in class_refs)
        assert any(r.code_snippet == "SomeClass" for r in class_refs)

    def test_extract_references_skips_common_words(self, temp_repo: Path) -> None:
        """Test that common words are not extracted as classes."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = "It is The class. This That A An object."
        references = validator._extract_references(text)

        class_refs = [r for r in references if r.reference_type == "class"]
        class_names = [r.code_snippet for r in class_refs]

        # Common words should be skipped
        assert "It" not in class_names
        assert "The" not in class_names
        assert "This" not in class_names
        assert "That" not in class_names
        assert "A" not in class_names
        assert "An" not in class_names

    def test_validate_reference_valid_file_in_diff(
        self, temp_repo: Path, sample_diff_content: str
    ) -> None:
        """Test validating a file reference that exists in diff."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py"],
            diff_content=sample_diff_content,
        )

        ref = CodeReference(
            file_path="src/main.py",
            line_number=None,
            code_snippet="Hello World",
            reference_type="file",
        )
        result = validator._validate_reference(ref)

        assert result.is_valid
        assert result.found_in == "diff"
        assert result.error_message is None

    def test_validate_reference_valid_file_in_repo(self, temp_repo: Path) -> None:
        """Test validating a file reference that exists in repo but not in diff."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["other_file.py"],  # Not the file we're checking
        )

        ref = CodeReference(
            file_path="src/main.py",
            line_number=None,
            code_snippet="some code",
            reference_type="file",
        )
        result = validator._validate_reference(ref)

        assert result.is_valid
        assert result.found_in == "file"

    def test_validate_reference_invalid_file(self, temp_repo: Path) -> None:
        """Test validating a file reference that doesn't exist."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        ref = CodeReference(
            file_path="nonexistent/file.py",
            line_number=None,
            code_snippet="code",
            reference_type="file",
        )
        result = validator._validate_reference(ref)

        assert not result.is_valid
        assert result.found_in is None
        assert "not found" in (result.error_message or "").lower()

    def test_validate_reference_valid_function_in_ast(
        self, temp_repo: Path, sample_code_elements: dict[str, dict[str, object]]
    ) -> None:
        """Test validating a function reference that exists in AST."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            code_elements=sample_code_elements,
        )

        ref = CodeReference(
            file_path=None,
            line_number=None,
            code_snippet="main",
            reference_type="function",
        )
        result = validator._validate_reference(ref)

        assert result.is_valid
        assert result.found_in == "ast"

    def test_validate_reference_valid_class_in_ast(
        self, temp_repo: Path, sample_code_elements: dict[str, dict[str, object]]
    ) -> None:
        """Test validating a class reference that exists in AST."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            code_elements=sample_code_elements,
        )

        ref = CodeReference(
            file_path=None,
            line_number=None,
            code_snippet="MyClass",
            reference_type="class",
        )
        result = validator._validate_reference(ref)

        assert result.is_valid
        assert result.found_in == "ast"

    def test_validate_reference_invalid_element(
        self, temp_repo: Path, sample_code_elements: dict[str, dict[str, object]]
    ) -> None:
        """Test validating a code element that doesn't exist in AST."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            code_elements=sample_code_elements,
        )

        ref = CodeReference(
            file_path=None,
            line_number=None,
            code_snippet="NonExistentFunction",
            reference_type="function",
        )
        result = validator._validate_reference(ref)

        assert not result.is_valid
        assert result.found_in is None
        assert "not found" in (result.error_message or "").lower()

    def test_validate_references_in_text(
        self,
        temp_repo: Path,
        sample_code_elements: dict[str, dict[str, object]],
        sample_diff_content: str,
    ) -> None:
        """Test validating all references in a text."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py"],
            code_elements=sample_code_elements,
            diff_content=sample_diff_content,
        )

        text = """
The main() function is defined in `src/main.py`.
It uses MyClass.process() for processing.
Also see helper() in `src/utils.py`.
"""
        results = validator.validate_references_in_text(text)

        # Should find references
        assert len(results) > 0

        # Check that we have different types
        ref_types = [r.reference.reference_type for r in results]
        assert "file" in ref_types
        assert "function" in ref_types
        assert "class" in ref_types

    def test_get_correction_prompt(
        self, temp_repo: Path, sample_code_elements: dict[str, dict[str, object]]
    ) -> None:
        """Test generation of correction prompt."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py", "src/utils.py"],
            code_elements=sample_code_elements,
        )

        invalid_results = [
            ReferenceValidationResult(
                reference=CodeReference(
                    file_path="bad/file.py",
                    line_number=None,
                    code_snippet="context",
                    reference_type="file",
                ),
                is_valid=False,
                found_in=None,
                error_message="File not found",
            ),
            ReferenceValidationResult(
                reference=CodeReference(
                    file_path=None,
                    line_number=None,
                    code_snippet="BadFunction",
                    reference_type="function",
                ),
                is_valid=False,
                found_in=None,
                error_message="Function not found",
            ),
        ]

        prompt = validator.get_correction_prompt(invalid_results, "Original text")

        assert "bad/file.py" in prompt
        assert "BadFunction" in prompt
        assert "src/main.py" in prompt  # Available files
        assert "main" in prompt  # Available elements
        assert "Original text" in prompt

    def test_get_correction_prompt_empty(self, temp_repo: Path) -> None:
        """Test correction prompt with no invalid results."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        prompt = validator.get_correction_prompt([], "Original text")

        assert prompt == ""

    def test_validate_and_correct_all_valid(
        self,
        temp_repo: Path,
        sample_code_elements: dict[str, dict[str, object]],
        mock_llm_provider: MagicMock,
    ) -> None:
        """Test validate_and_correct when all references are valid."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py"],
            code_elements=sample_code_elements,
        )

        text = "The main() function works with MyClass."
        result = validator.validate_and_correct(text, mock_llm_provider)

        # Should return original text without calling LLM
        assert result == text
        mock_llm_provider.generate.assert_not_called()

    def test_validate_and_correct_with_invalid(
        self, temp_repo: Path, mock_llm_provider: MagicMock
    ) -> None:
        """Test validate_and_correct with invalid references."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py"],
            code_elements={},
        )

        text = "The BadFunction() is in `nonexistent.py`."
        result = validator.validate_and_correct(
            text, mock_llm_provider, max_corrections=1
        )

        # Should call LLM for correction
        mock_llm_provider.generate.assert_called_once()
        assert result == "Corrected output with valid references"

    def test_validate_and_correct_max_corrections_reached(
        self, temp_repo: Path, mock_llm_provider: MagicMock
    ) -> None:
        """Test validate_and_correct when max corrections is reached."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=[],
            code_elements={},
        )

        # Mock LLM to always return text with invalid references
        mock_llm_provider.generate.return_value = "Still has BadFunction()"

        text = "Original with BadFunction()"
        result = validator.validate_and_correct(
            text, mock_llm_provider, max_corrections=1
        )

        # Should have warning appended
        assert "WARNING" in result
        assert "BadFunction" in result

    def test_validate_and_correct_temperature_increase(
        self, temp_repo: Path, mock_llm_provider: MagicMock
    ) -> None:
        """Test that temperature increases with each correction attempt."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=[],
            code_elements={},
        )

        mock_llm_provider.generate.return_value = "Still invalid with BadFunction()"

        text = "Original with BadFunction()"
        validator.validate_and_correct(text, mock_llm_provider, max_corrections=2)

        # Check temperature increases
        calls = mock_llm_provider.generate.call_args_list
        assert calls[0][1]["temperature"] == 0.3
        assert calls[1][1]["temperature"] == 0.4


# =============================================================================
# ASTValidator Tests
# =============================================================================


class TestASTValidator:
    """Tests for ASTValidator class."""

    def test_initialization_with_code_elements(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test initialization with code elements."""
        validator = ASTValidator(sample_code_element_objects)

        assert "main" in validator.elements
        assert "MyClass" in validator.elements
        assert "method" in validator.elements
        assert "helper" in validator.elements
        assert validator.element_names == {"main", "MyClass", "method", "helper"}

    def test_initialization_empty(self) -> None:
        """Test initialization with empty list."""
        validator = ASTValidator([])

        assert validator.elements == {}
        assert validator.element_names == set()

    def test_validate_fact_valid_elements(
        self,
        sample_code_element_objects: list[CodeElement],
        sample_technical_facts: list[TechnicalFact],
    ) -> None:
        """Test validating a fact with valid element references."""
        validator = ASTValidator(sample_code_element_objects)

        # fact_1 references "main" and "MyClass" which exist
        result = validator.validate_fact(sample_technical_facts[0])

        assert result.passed
        assert len(result.errors) == 0

    def test_validate_fact_invalid_element(
        self,
        sample_code_element_objects: list[CodeElement],
        sample_technical_facts: list[TechnicalFact],
    ) -> None:
        """Test validating a fact with invalid element reference."""
        validator = ASTValidator(sample_code_element_objects)

        # fact_3 references "nonexistent_function" which doesn't exist
        result = validator.validate_fact(sample_technical_facts[2])

        assert not result.passed
        assert len(result.errors) == 1
        assert "nonexistent_function" in result.errors[0]

    def test_validate_fact_low_confidence(
        self,
        sample_code_element_objects: list[CodeElement],
        sample_technical_facts: list[TechnicalFact],
    ) -> None:
        """Test validating a fact with low confidence generates warning."""
        validator = ASTValidator(sample_code_element_objects)

        # fact_2 has confidence 0.3
        result = validator.validate_fact(sample_technical_facts[1])

        assert result.passed  # Still passes
        assert len(result.warnings) == 1
        assert "Low confidence" in result.warnings[0]
        assert "0.30" in result.warnings[0]

    def test_validate_facts_multiple(
        self,
        sample_code_element_objects: list[CodeElement],
        sample_technical_facts: list[TechnicalFact],
    ) -> None:
        """Test validating multiple facts."""
        validator = ASTValidator(sample_code_element_objects)

        result = validator.validate_facts(sample_technical_facts)

        # fact_1: valid, fact_2: valid with warning, fact_3: invalid
        assert not result.passed  # Because fact_3 has an error
        assert len(result.errors) == 1  # From fact_3
        assert len(result.warnings) == 1  # From fact_2

    def test_validate_facts_empty_list(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test validating empty list of facts."""
        validator = ASTValidator(sample_code_element_objects)

        result = validator.validate_facts([])

        assert result.passed
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_check_hallucination_no_hallucination(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test hallucination check with valid references."""
        validator = ASTValidator(sample_code_element_objects)

        text = "The main() function creates a MyClass instance and calls method()."
        result = validator.check_hallucination(text)

        assert result.passed
        assert len(result.warnings) == 0

    def test_check_hallucination_with_hallucination(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test hallucination check with invalid function references."""
        validator = ASTValidator(sample_code_element_objects)

        text = "The fakeFunction() is called along with anotherFake()."
        result = validator.check_hallucination(text)

        assert result.passed  # Still passes, but with warnings
        assert len(result.warnings) == 2
        assert any("fakeFunction" in w for w in result.warnings)
        assert any("anotherFake" in w for w in result.warnings)

    def test_check_hallucination_skips_keywords(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test that common keywords are not flagged as hallucinations."""
        validator = ASTValidator(sample_code_element_objects)

        text = "if True: print(len(range(10))) while x: return int(str(42))"
        result = validator.check_hallucination(text)

        # Should not flag keywords as hallucinations
        warnings_str = " ".join(result.warnings)
        assert "if" not in warnings_str
        assert "print" not in warnings_str
        assert "len" not in warnings_str
        assert "range" not in warnings_str
        assert "while" not in warnings_str
        assert "return" not in warnings_str
        assert "int" not in warnings_str
        assert "str" not in warnings_str

    def test_check_hallucination_mixed(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test hallucination check with mix of valid and invalid references."""
        validator = ASTValidator(sample_code_element_objects)

        text = "The main() function calls fakeFunction() and helper()."
        result = validator.check_hallucination(text)

        assert result.passed
        # Should only warn about fakeFunction, not main or helper
        assert len(result.warnings) == 1
        assert "fakeFunction" in result.warnings[0]


# =============================================================================
# ValidationPipeline Tests
# =============================================================================


class TestValidationPipeline:
    """Tests for ValidationPipeline class."""

    def test_initialization(self, temp_repo: Path) -> None:
        """Test pipeline initialization."""
        pipeline = ValidationPipeline(temp_repo)

        assert pipeline.input_validator is not None
        assert pipeline.schema_validator is not None
        assert pipeline.results == []

    def test_add_check(self, temp_repo: Path) -> None:
        """Test adding validation check results."""
        pipeline = ValidationPipeline(temp_repo)

        result1 = ValidationResult(passed=True, errors=[], warnings=["Warning 1"])
        result2 = ValidationResult(passed=False, errors=["Error 1"], warnings=[])

        pipeline.add_check("check1", result1)
        pipeline.add_check("check2", result2)

        assert len(pipeline.results) == 2
        assert pipeline.results[0] == ("check1", result1)
        assert pipeline.results[1] == ("check2", result2)

    def test_get_summary_all_passed(self, temp_repo: Path) -> None:
        """Test summary when all checks pass."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=True, errors=[], warnings=[])
        )
        pipeline.add_check(
            "check2", ValidationResult(passed=True, errors=[], warnings=[])
        )

        summary = pipeline.get_summary()

        assert summary.passed
        assert len(summary.errors) == 0
        assert len(summary.warnings) == 0

    def test_get_summary_with_errors(self, temp_repo: Path) -> None:
        """Test summary when some checks have errors."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=True, errors=[], warnings=[])
        )
        pipeline.add_check(
            "check2", ValidationResult(passed=False, errors=["Error 1"], warnings=[])
        )

        summary = pipeline.get_summary()

        assert not summary.passed
        assert len(summary.errors) == 1
        assert "[check2]" in summary.errors[0]
        assert "Error 1" in summary.errors[0]

    def test_get_summary_with_warnings(self, temp_repo: Path) -> None:
        """Test summary when checks have warnings."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=True, errors=[], warnings=["Warning 1"])
        )
        pipeline.add_check(
            "check2", ValidationResult(passed=True, errors=[], warnings=["Warning 2"])
        )

        summary = pipeline.get_summary()

        assert summary.passed
        assert len(summary.warnings) == 2
        assert any("[check1]" in w for w in summary.warnings)
        assert any("[check2]" in w for w in summary.warnings)

    def test_get_summary_mixed(self, temp_repo: Path) -> None:
        """Test summary with both errors and warnings."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=True, errors=[], warnings=["Warning 1"])
        )
        pipeline.add_check(
            "check2",
            ValidationResult(
                passed=False, errors=["Error 1", "Error 2"], warnings=["Warning 2"]
            ),
        )

        summary = pipeline.get_summary()

        assert not summary.passed
        assert len(summary.errors) == 2
        assert len(summary.warnings) == 2

    def test_has_critical_errors_true(self, temp_repo: Path) -> None:
        """Test has_critical_errors when there are errors."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=False, errors=["Error"], warnings=[])
        )

        assert pipeline.has_critical_errors()

    def test_has_critical_errors_false(self, temp_repo: Path) -> None:
        """Test has_critical_errors when there are no errors."""
        pipeline = ValidationPipeline(temp_repo)

        pipeline.add_check(
            "check1", ValidationResult(passed=True, errors=[], warnings=["Warning"])
        )

        assert not pipeline.has_critical_errors()

    def test_has_critical_errors_empty(self, temp_repo: Path) -> None:
        """Test has_critical_errors with no checks."""
        pipeline = ValidationPipeline(temp_repo)

        assert not pipeline.has_critical_errors()


# =============================================================================
# InputValidator Tests
# =============================================================================


class TestInputValidator:
    """Tests for InputValidator class."""

    def test_initialization(self, temp_repo: Path) -> None:
        """Test input validator initialization."""
        validator = InputValidator(temp_repo)

        assert validator.repo_path == temp_repo
        assert InputValidator.MAX_DIFF_LINES == 10000
        assert InputValidator.MAX_FILE_SIZE_MB == 10
        assert len(InputValidator.SUPPORTED_EXTENSIONS) > 0

    def test_validate_commit_range_valid_format(self, temp_repo: Path) -> None:
        """Test validating commit range with valid format."""
        validator = InputValidator(temp_repo)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = validator.validate_commit_range("HEAD~5..HEAD")

        assert result.passed
        assert len(result.errors) == 0

    def test_validate_commit_range_invalid_format(self, temp_repo: Path) -> None:
        """Test validating commit range with invalid format."""
        validator = InputValidator(temp_repo)

        result = validator.validate_commit_range("invalid-range")

        assert not result.passed
        assert len(result.errors) == 1
        assert "Invalid commit range format" in result.errors[0]

    def test_validate_commit_range_nonexistent_commit(self, temp_repo: Path) -> None:
        """Test validating commit range with non-existent commit."""
        import subprocess

        validator = InputValidator(temp_repo)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "git", stderr="Commit not found"
            )
            result = validator.validate_commit_range("abc123..def456")

        # The method should catch CalledProcessError and report the error
        assert not result.passed
        assert len(result.errors) == 2  # Both commits fail
        assert any("abc123" in e for e in result.errors)
        assert any("def456" in e for e in result.errors)

    def test_validate_commit_range_empty_base(self, temp_repo: Path) -> None:
        """Test validating commit range with empty base (e.g., '..HEAD')."""
        validator = InputValidator(temp_repo)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = validator.validate_commit_range("..HEAD")

        # Should only validate HEAD, not empty base
        assert mock_run.call_count == 1

    def test_validate_diff_size_small(self, temp_repo: Path) -> None:
        """Test validating small diff."""
        validator = InputValidator(temp_repo)

        diff = "line1\nline2\nline3"
        result = validator.validate_diff_size(diff)

        assert result.passed
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_validate_diff_size_at_limit(self, temp_repo: Path) -> None:
        """Test validating diff at the limit."""
        validator = InputValidator(temp_repo)

        diff = "\n".join([f"line{i}" for i in range(InputValidator.MAX_DIFF_LINES)])
        result = validator.validate_diff_size(diff)

        assert result.passed
        assert len(result.errors) == 0
        # At limit, should have warning
        assert len(result.warnings) == 1

    def test_validate_diff_size_over_limit(self, temp_repo: Path) -> None:
        """Test validating diff over the limit."""
        validator = InputValidator(temp_repo)

        diff = "\n".join([f"line{i}" for i in range(InputValidator.MAX_DIFF_LINES + 1)])
        result = validator.validate_diff_size(diff)

        assert not result.passed
        assert len(result.errors) == 1
        assert "Diff too large" in result.errors[0]

    def test_validate_diff_size_warning_threshold(self, temp_repo: Path) -> None:
        """Test warning for large diffs."""
        validator = InputValidator(temp_repo)

        # More than half the limit but under the full limit
        line_count = int(InputValidator.MAX_DIFF_LINES * 0.75)
        diff = "\n".join([f"line{i}" for i in range(line_count)])
        result = validator.validate_diff_size(diff)

        assert result.passed
        assert len(result.warnings) == 1
        assert "Large diff" in result.warnings[0]

    def test_validate_file_type_supported(self, temp_repo: Path) -> None:
        """Test validating supported file type."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "test.py"
        test_file.write_text("# Test file")

        result = validator.validate_file_type(test_file)

        assert result.passed
        assert len(result.errors) == 0

    def test_validate_file_type_unsupported(self, temp_repo: Path) -> None:
        """Test validating unsupported file type."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "test.xyz"
        test_file.write_text("# Test file")

        result = validator.validate_file_type(test_file)

        assert result.passed  # Still passes, but with warning
        assert len(result.warnings) == 1
        assert "Unsupported file type" in result.warnings[0]

    def test_validate_file_type_binary(self, temp_repo: Path) -> None:
        """Test validating binary file."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03")

        result = validator.validate_file_type(test_file)

        assert not result.passed
        assert len(result.errors) == 1
        assert "Binary file" in result.errors[0]

    def test_validate_file_type_too_large(self, temp_repo: Path) -> None:
        """Test validating file that is too large."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "large.py"
        # Create a file larger than MAX_FILE_SIZE_MB
        test_file.write_bytes(
            b"x" * (InputValidator.MAX_FILE_SIZE_MB * 1024 * 1024 + 1)
        )

        result = validator.validate_file_type(test_file)

        assert not result.passed
        assert len(result.errors) == 1
        assert "File too large" in result.errors[0]

    def test_validate_file_type_nonexistent(self, temp_repo: Path) -> None:
        """Test validating non-existent file."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "nonexistent.py"

        result = validator.validate_file_type(test_file)

        assert not result.passed
        assert len(result.errors) == 1
        # Error message could be about binary check or file access
        assert any(
            keyword in result.errors[0].lower()
            for keyword in ["cannot access", "binary"]
        )

    def test_is_binary_true(self, temp_repo: Path) -> None:
        """Test binary file detection."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "binary.bin"
        test_file.write_bytes(b"Hello\x00World")

        assert validator._is_binary(test_file)

    def test_is_binary_false(self, temp_repo: Path) -> None:
        """Test non-binary file detection."""
        validator = InputValidator(temp_repo)

        test_file = temp_repo / "text.txt"
        test_file.write_text("Hello World")

        assert not validator._is_binary(test_file)

    def test_is_binary_error(self, temp_repo: Path) -> None:
        """Test binary detection with file error."""
        validator = InputValidator(temp_repo)

        # Non-existent file
        assert validator._is_binary(temp_repo / "nonexistent")


# =============================================================================
# SchemaValidator Tests
# =============================================================================


class TestSchemaValidator:
    """Tests for SchemaValidator class."""

    def test_validate_pydantic_model_valid(self) -> None:
        """Test validating valid pydantic model data."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            age: int

        validator = SchemaValidator()
        result = validator.validate_pydantic_model(
            {"name": "John", "age": 30}, TestModel
        )

        assert result.passed
        assert len(result.errors) == 0

    def test_validate_pydantic_model_invalid(self) -> None:
        """Test validating invalid pydantic model data."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            age: int

        validator = SchemaValidator()
        result = validator.validate_pydantic_model(
            {"name": "John", "age": "not an int"}, TestModel
        )

        assert not result.passed
        assert len(result.errors) > 0
        assert "age" in result.errors[0]

    def test_validate_pydantic_model_missing_field(self) -> None:
        """Test validating data with missing required field."""
        from pydantic import BaseModel, Field

        class TestModel(BaseModel):
            name: str
            age: int = Field(..., description="Age is required")

        validator = SchemaValidator()
        result = validator.validate_pydantic_model({"name": "John"}, TestModel)

        assert not result.passed
        assert len(result.errors) > 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestValidationIntegration:
    """Integration tests for the validation module."""

    def test_full_validation_pipeline(
        self,
        temp_repo: Path,
        sample_code_element_objects: list[CodeElement],
        sample_technical_facts: list[TechnicalFact],
    ) -> None:
        """Test the full validation pipeline with all validators."""
        # Create pipeline
        pipeline = ValidationPipeline(temp_repo)

        # Add input validation
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            commit_result = pipeline.input_validator.validate_commit_range(
                "HEAD~1..HEAD"
            )
        pipeline.add_check("commit_range", commit_result)

        # Add AST validation
        ast_validator = ASTValidator(sample_code_element_objects)
        facts_result = ast_validator.validate_facts(sample_technical_facts)
        pipeline.add_check("technical_facts", facts_result)

        # Get summary
        summary = pipeline.get_summary()

        # Should have errors from the invalid fact
        assert not summary.passed
        assert any("nonexistent_function" in e for e in summary.errors)

    def test_code_reference_with_ast_validation(
        self, temp_repo: Path, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test code reference validation combined with AST validation."""
        # Create code reference validator with AST elements
        code_elements = {
            elem.name: {"type": elem.element_type.value}
            for elem in sample_code_element_objects
        }

        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=["src/main.py"],
            code_elements=code_elements,
        )

        # Validate text with code references
        text = "The main() function uses MyClass."
        results = validator.validate_references_in_text(text)

        # All references should be valid
        assert all(r.is_valid for r in results)

    def test_end_to_end_validation_workflow(
        self, temp_repo: Path, sample_diff_content: str, mock_llm_provider: MagicMock
    ) -> None:
        """Test end-to-end validation workflow."""
        # Setup
        changed_files = ["src/main.py"]
        code_elements = {
            "main": {"type": "function"},
            "MyClass": {"type": "class"},
        }

        # Create validator
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            changed_files=changed_files,
            code_elements=code_elements,
            diff_content=sample_diff_content,
        )

        # LLM output with some valid and invalid references
        llm_output = """
The main() function is defined in `src/main.py`.
It creates a MyClass instance.
Also see fakeFunction() in `nonexistent.py`.
"""

        # Validate and correct
        result = validator.validate_and_correct(
            llm_output, mock_llm_provider, max_corrections=1
        )

        # Should have called LLM for correction
        mock_llm_provider.generate.assert_called()
        assert result == "Corrected output with valid references"


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_code_reference_empty_text(self, temp_repo: Path) -> None:
        """Test validating empty text."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        results = validator.validate_references_in_text("")

        assert results == []

    def test_code_reference_special_characters(self, temp_repo: Path) -> None:
        """Test extracting references with special characters."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        text = "See `path/to/file-name_v2.py` and `another.file.py`."
        references = validator._extract_references(text)

        file_refs = [r for r in references if r.reference_type == "file"]
        assert len(file_refs) == 2

    def test_ast_validator_empty_fact(
        self, sample_code_element_objects: list[CodeElement]
    ) -> None:
        """Test validating fact with empty source elements."""
        validator = ASTValidator(sample_code_element_objects)

        fact = TechnicalFact(
            fact_id="empty_fact",
            category="test",
            source_elements=[],  # Empty list
            description="Test fact",
            source_file="test.py",
            confidence=0.9,
        )

        result = validator.validate_fact(fact)

        assert result.passed  # No elements to validate

    def test_input_validator_empty_diff(self, temp_repo: Path) -> None:
        """Test validating empty diff."""
        validator = InputValidator(temp_repo)

        result = validator.validate_diff_size("")

        assert result.passed
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_validation_pipeline_duplicate_checks(self, temp_repo: Path) -> None:
        """Test adding duplicate checks to pipeline."""
        pipeline = ValidationPipeline(temp_repo)

        result = ValidationResult(passed=True, errors=[], warnings=[])
        pipeline.add_check("check", result)
        pipeline.add_check("check", result)  # Duplicate name

        assert len(pipeline.results) == 2

    def test_code_reference_very_long_snippet(
        self, temp_repo: Path, sample_diff_content: str
    ) -> None:
        """Test with very long code snippet."""
        validator = CodeReferenceValidator(
            repo_path=temp_repo,
            diff_content=sample_diff_content,
        )

        # Very long snippet should still be handled
        long_snippet = "x" * 10000
        result = validator._snippet_in_diff("src/main.py", long_snippet)

        # Should not crash, just return False
        assert result is False

    def test_normalize_code_unicode(self, temp_repo: Path) -> None:
        """Test code normalization with unicode."""
        validator = CodeReferenceValidator(repo_path=temp_repo)

        normalized = validator._normalize_code("  héllo  wörld  ")

        assert "héllo" in normalized
        assert "wörld" in normalized
