"""Validation layer for GGDes."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ggdes.schemas import CodeElement, TechnicalFact


@dataclass
class ValidationResult:
    """Result of a validation check."""

    passed: bool
    errors: list[str]
    warnings: list[str]


class InputValidator:
    """Validate inputs before processing."""

    MAX_DIFF_LINES = 10000
    MAX_FILE_SIZE_MB = 10
    SUPPORTED_EXTENSIONS = {
        ".py",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".h",
        ".md",
        ".txt",
        ".yaml",
        ".yml",
        ".json",
    }

    def __init__(self, repo_path: Path):
        """Initialize input validator.

        Args:
            repo_path: Path to the repository
        """
        self.repo_path = repo_path

    def validate_commit_range(self, commit_range: str) -> ValidationResult:
        """Validate a git commit range.

        Args:
            commit_range: Git commit range (e.g., "HEAD~5..HEAD")

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        # Check format
        if ".." not in commit_range:
            errors.append(
                f"Invalid commit range format: {commit_range}. Expected 'base..head'"
            )
            return ValidationResult(False, errors, warnings)

        # Validate commits exist
        base, head = commit_range.split("..", 1)
        for commit in [base, head]:
            if commit:
                result = self._validate_commit_exists(commit)
                if not result.passed:
                    errors.extend(result.errors)

        return ValidationResult(len(errors) == 0, errors, warnings)

    def _validate_commit_exists(self, commit: str) -> ValidationResult:
        """Check if a commit exists in the repo."""
        import subprocess

        errors = []
        warnings = []

        try:
            subprocess.run(
                ["git", "-C", str(self.repo_path), "cat-file", "-t", commit],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            errors.append(f"Commit not found: {commit}")

        return ValidationResult(len(errors) == 0, errors, warnings)

    def validate_diff_size(self, diff_content: str) -> ValidationResult:
        """Validate diff content is within limits.

        Args:
            diff_content: Git diff content

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        lines = diff_content.split("\n")
        line_count = len(lines)

        if line_count > self.MAX_DIFF_LINES:
            errors.append(
                f"Diff too large: {line_count} lines (max: {self.MAX_DIFF_LINES}). "
                f"Consider using AST chunking."
            )

        if line_count > self.MAX_DIFF_LINES / 2:
            warnings.append(
                f"Large diff: {line_count} lines. Analysis may take longer."
            )

        return ValidationResult(len(errors) == 0, errors, warnings)

    def validate_file_type(self, file_path: Path) -> ValidationResult:
        """Validate file type is supported.

        Args:
            file_path: Path to file

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        # Skip binary files
        if self._is_binary(file_path):
            errors.append(f"Binary file not supported: {file_path}")
            return ValidationResult(False, errors, warnings)

        # Check extension
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            warnings.append(f"Unsupported file type: {ext}. Analysis may be limited.")

        # Check size
        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > self.MAX_FILE_SIZE_MB:
                errors.append(
                    f"File too large: {size_mb:.1f}MB (max: {self.MAX_FILE_SIZE_MB}MB)"
                )
        except OSError:
            errors.append(f"Cannot access file: {file_path}")

        return ValidationResult(len(errors) == 0, errors, warnings)

    def _is_binary(self, file_path: Path) -> bool:
        """Check if a file is binary."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)
                return b"\0" in chunk
        except Exception:
            return True


class SchemaValidator:
    """Validate data against schemas."""

    def validate_pydantic_model(self, data: Any, model_class: type) -> ValidationResult:
        """Validate data against a Pydantic model.

        Args:
            data: Data to validate
            model_class: Pydantic model class

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        try:
            model_class(**data)
        except ValidationError as e:
            for error in e.errors():
                field = ".".join(str(x) for x in error["loc"])
                message = error["msg"]
                errors.append(f"{field}: {message}")

        return ValidationResult(len(errors) == 0, errors, warnings)


class ASTValidator:
    """Validate technical facts against AST."""

    def __init__(self, code_elements: list[CodeElement]):
        """Initialize AST validator.

        Args:
            code_elements: Extracted code elements from AST
        """
        self.elements = {elem.name: elem for elem in code_elements}
        self.element_names = set(self.elements.keys())

    def validate_fact(self, fact: TechnicalFact) -> ValidationResult:
        """Validate a technical fact against AST.

        Args:
            fact: Technical fact to validate

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        # Check that referenced elements exist
        for element_ref in fact.source_elements:
            if element_ref not in self.element_names:
                errors.append(f"Referenced element not found in AST: {element_ref}")

        # Warn if confidence is low
        if fact.confidence < 0.5:
            warnings.append(
                f"Low confidence fact: {fact.fact_id} ({fact.confidence:.2f})"
            )

        return ValidationResult(len(errors) == 0, errors, warnings)

    def validate_facts(self, facts: list[TechnicalFact]) -> ValidationResult:
        """Validate multiple facts.

        Args:
            facts: List of technical facts

        Returns:
            ValidationResult
        """
        all_errors = []
        all_warnings = []

        for fact in facts:
            result = self.validate_fact(fact)
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)

        return ValidationResult(len(all_errors) == 0, all_errors, all_warnings)

    def check_hallucination(self, text: str) -> ValidationResult:
        """Check text for potential hallucinations (function names not in AST).

        Args:
            text: Text to check (e.g., generated documentation)

        Returns:
            ValidationResult with warnings for unknown function/class references
        """
        errors = []
        warnings = []

        # Pattern to match function-like names in text
        # This is heuristic - looks for word(s) followed by parentheses
        pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        potential_names = set(re.findall(pattern, text))

        for name in potential_names:
            if name not in self.element_names:
                # Common false positives
                if name not in (
                    "if",
                    "while",
                    "for",
                    "return",
                    "print",
                    "len",
                    "range",
                    "str",
                    "int",
                ):
                    warnings.append(
                        f"Potential hallucination: '{name}' not found in codebase"
                    )

        return ValidationResult(True, errors, warnings)


class ValidationPipeline:
    """Pipeline of validation checks."""

    def __init__(self, repo_path: Path):
        """Initialize validation pipeline.

        Args:
            repo_path: Path to repository
        """
        self.input_validator = InputValidator(repo_path)
        self.schema_validator = SchemaValidator()
        self.results: list[tuple[str, ValidationResult]] = []

    def add_check(self, name: str, result: ValidationResult) -> None:
        """Add a validation check result."""
        self.results.append((name, result))

    def get_summary(self) -> ValidationResult:
        """Get overall validation summary.

        Returns:
            ValidationResult with all errors and warnings
        """
        all_errors = []
        all_warnings = []

        for name, result in self.results:
            for error in result.errors:
                all_errors.append(f"[{name}] {error}")
            for warning in result.warnings:
                all_warnings.append(f"[{name}] {warning}")

        return ValidationResult(len(all_errors) == 0, all_errors, all_warnings)

    def has_critical_errors(self) -> bool:
        """Check if there are any critical errors."""
        summary = self.get_summary()
        return len(summary.errors) > 0
