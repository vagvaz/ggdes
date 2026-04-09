"""Code reference validation for LLM outputs."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeReference:
    """A code reference found in LLM output."""

    file_path: str | None  # File path if specified
    line_number: int | None  # Line number if specified
    code_snippet: str  # The referenced code
    reference_type: str  # 'function', 'class', 'variable', 'snippet'


@dataclass
class ReferenceValidationResult:
    """Result of validating a code reference."""

    reference: CodeReference
    is_valid: bool
    found_in: str | None  # 'diff', 'ast', 'file', or None
    error_message: str | None = None


class CodeReferenceValidator:
    """Validate code references in LLM output against diffs and AST."""

    def __init__(
        self,
        repo_path: Path,
        changed_files: list[str] | None = None,
        code_elements: dict[str, dict] | None = None,
        diff_content: str | None = None,
    ):
        """Initialize code reference validator.

        Args:
            repo_path: Path to the repository
            changed_files: List of files that changed in the diff
            code_elements: Dict of code elements from AST parsing (name -> element info)
            diff_content: The git diff content for content verification
        """
        self.repo_path = repo_path
        self.changed_files = set(changed_files or [])
        self.code_elements = code_elements or {}
        self.diff_content = diff_content or ""

        # Build diff snippets index for quick lookup
        self.diff_snippets = self._extract_diff_snippets()

    def _extract_diff_snippets(self) -> dict[str, list[str]]:
        """Extract code snippets from diff content by file.

        Returns:
            Dict mapping file paths to list of code snippets in the diff
        """
        snippets: dict[str, list[str]] = {}
        if not self.diff_content:
            return snippets

        current_file = None
        current_snippets: list[str] = []

        for line in self.diff_content.split("\n"):
            # Check for file header
            if line.startswith("diff --git"):
                if current_file and current_snippets:
                    snippets[current_file] = current_snippets
                current_file = None
                current_snippets = []
            elif line.startswith("--- a/") or line.startswith("+++ b/"):
                # Extract filename
                parts = line.split("/", 2)
                if len(parts) >= 2:
                    current_file = parts[1] if len(parts) == 2 else "/".join(parts[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                # Added line (skip the + prefix)
                code_line = line[1:].strip()
                if code_line and not code_line.startswith("#"):
                    current_snippets.append(code_line)

        # Don't forget the last file
        if current_file and current_snippets:
            snippets[current_file] = current_snippets

        return snippets

    def validate_references_in_text(self, text: str) -> list[ReferenceValidationResult]:
        """Validate all code references in a text.

        Args:
            text: Text to validate (e.g., LLM output)

        Returns:
            List of validation results for each reference found
        """
        references = self._extract_references(text)
        results = []

        for ref in references:
            result = self._validate_reference(ref)
            results.append(result)

        return results

    def _extract_references(self, text: str) -> list[CodeReference]:
        """Extract code references from text.

        Args:
            text: Text to extract references from

        Returns:
            List of code references
        """
        references = []

        # Pattern 1: File paths with optional line numbers
        # Matches: `path/to/file.py`, `path/to/file.py:123`, or "in path/to/file.py"
        file_patterns = [
            r"`([^`]+\.(?:py|cpp|cc|cxx|hpp|h|hh|hxx|js|ts|java|go|rs))(?::(\d+))?`",
            r'"([^"]+\.(?:py|cpp|cc|cxx|hpp|h|hh|hxx|js|ts|java|go|rs))(?::(\d+))?"',
            r"in\s+([a-zA-Z_][a-zA-Z0-9_./]*\.(?:py|cpp|cc|cxx|hpp|h|hh|hxx|js|ts|java|go|rs))(?::(\d+))?",
        ]

        for pattern in file_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                file_path = match.group(1)
                line_num = int(match.group(2)) if match.group(2) else None

                # Get surrounding context (20 chars before and after)
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                context = text[start:end]

                references.append(
                    CodeReference(
                        file_path=file_path,
                        line_number=line_num,
                        code_snippet=context,
                        reference_type="file",
                    )
                )

        # Pattern 2: Function/method calls and definitions
        # Look for function names followed by parentheses
        func_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)(?:\([^)]*\))"
        for match in re.finditer(func_pattern, text):
            func_name = match.group(1)

            # Skip common non-function patterns
            if func_name.lower() in {
                "if",
                "while",
                "for",
                "return",
                "print",
                "len",
                "range",
                "str",
                "int",
                "float",
                "bool",
                "list",
                "dict",
                "set",
                "tuple",
                "type",
                "isinstance",
                "hasattr",
                "getattr",
                "setattr",
                "import",
                "from",
                "as",
                "with",
                "assert",
            }:
                continue

            references.append(
                CodeReference(
                    file_path=None,
                    line_number=None,
                    code_snippet=func_name,
                    reference_type="function",
                )
            )

        # Pattern 3: Class references (CamelCase words that look like classes)
        class_pattern = r"\b([A-Z][a-zA-Z0-9_]*)(?:\s*\(|\.[a-zA-Z])"
        for match in re.finditer(class_pattern, text):
            class_name = match.group(1)

            # Skip common false positives
            if class_name in {"I", "It", "The", "This", "That", "A", "An"}:
                continue

            references.append(
                CodeReference(
                    file_path=None,
                    line_number=None,
                    code_snippet=class_name,
                    reference_type="class",
                )
            )

        return references

    def _validate_reference(
        self, reference: CodeReference
    ) -> ReferenceValidationResult:
        """Validate a single code reference.

        Args:
            reference: Code reference to validate

        Returns:
            Validation result
        """
        # Check 1: File path validation
        if reference.file_path:
            # Check if file is in changed files
            if reference.file_path in self.changed_files:
                # Check if the code snippet exists in the diff for this file
                if self._snippet_in_diff(reference.file_path, reference.code_snippet):
                    return ReferenceValidationResult(
                        reference=reference,
                        is_valid=True,
                        found_in="diff",
                    )
                else:
                    return ReferenceValidationResult(
                        reference=reference,
                        is_valid=False,
                        found_in=None,
                        error_message=f"Code snippet not found in diff for file: {reference.file_path}",
                    )
            else:
                # File not in diff - check if it exists in repo
                full_path = self.repo_path / reference.file_path
                if full_path.exists():
                    # File exists but wasn't changed - this is a reference to existing code
                    return ReferenceValidationResult(
                        reference=reference,
                        is_valid=True,
                        found_in="file",
                    )
                else:
                    return ReferenceValidationResult(
                        reference=reference,
                        is_valid=False,
                        found_in=None,
                        error_message=f"File not found in repository: {reference.file_path}",
                    )

        # Check 2: Code element validation (function/class names)
        if reference.reference_type in ("function", "class"):
            code_name = reference.code_snippet

            # Check if it's in the code elements from AST
            if code_name in self.code_elements:
                return ReferenceValidationResult(
                    reference=reference,
                    is_valid=True,
                    found_in="ast",
                )
            else:
                return ReferenceValidationResult(
                    reference=reference,
                    is_valid=False,
                    found_in=None,
                    error_message=f"{reference.reference_type.capitalize()} '{code_name}' not found in parsed code",
                )

        # Unknown reference type
        return ReferenceValidationResult(
            reference=reference,
            is_valid=False,
            found_in=None,
            error_message=f"Cannot validate reference of type: {reference.reference_type}",
        )

    def _snippet_in_diff(self, file_path: str, snippet: str) -> bool:
        """Check if a code snippet exists in the diff for a file.

        Args:
            file_path: File path
            snippet: Code snippet to search for

        Returns:
            True if found in diff
        """
        if file_path not in self.diff_snippets:
            return False

        # Extract the key code parts (ignore whitespace, comments)
        snippet_normalized = self._normalize_code(snippet)

        for diff_line in self.diff_snippets[file_path]:
            diff_normalized = self._normalize_code(diff_line)
            if (
                snippet_normalized in diff_normalized
                or diff_normalized in snippet_normalized
            ):
                return True

        return False

    def _normalize_code(self, code: str) -> str:
        """Normalize code for comparison.

        Args:
            code: Code string

        Returns:
            Normalized code
        """
        # Remove whitespace, normalize case for comparison
        return " ".join(code.split()).lower()

    def get_correction_prompt(
        self, invalid_results: list[ReferenceValidationResult], original_text: str
    ) -> str:
        """Generate a correction prompt for invalid references.

        Args:
            invalid_results: List of invalid reference validation results
            original_text: The original LLM output

        Returns:
            Correction prompt for the LLM
        """
        if not invalid_results:
            return ""

        errors = []
        for result in invalid_results:
            ref = result.reference
            if ref.file_path:
                errors.append(f"- File '{ref.file_path}': {result.error_message}")
            else:
                errors.append(
                    f"- {ref.reference_type.capitalize()} '{ref.code_snippet}': {result.error_message}"
                )

        available_files = "\n".join(f"  - {f}" for f in sorted(self.changed_files))
        available_elements = "\n".join(
            f"  - {name}" for name in sorted(self.code_elements.keys())[:20]
        )

        return f"""Your previous response contains code references that could not be verified:

{chr(10).join(errors)}

You must only reference code that exists in:
1. The changed files (diff):
{available_files}

2. The parsed code elements:
{available_elements}

Please rewrite your response, ensuring:
- All file paths match exactly with the changed files
- All function/class names exist in the parsed code
- Code snippets match content from the diff
- If referencing a file, use the exact path from the diff

Original response:
{original_text}

Please provide a corrected response with valid code references:"""

    def validate_and_correct(
        self, llm_output: str, llm_provider, max_corrections: int = 2
    ) -> str:
        """Validate LLM output and request corrections if needed.

        Args:
            llm_output: The LLM-generated text
            llm_provider: LLM provider to request corrections
            max_corrections: Maximum number of correction attempts

        Returns:
            Validated (and potentially corrected) text
        """
        current_output = llm_output

        for attempt in range(max_corrections + 1):
            results = self.validate_references_in_text(current_output)
            invalid_results = [r for r in results if not r.is_valid]

            if not invalid_results:
                # All references are valid
                return current_output

            if attempt < max_corrections:
                # Request correction
                correction_prompt = self.get_correction_prompt(
                    invalid_results, current_output
                )

                print(
                    f"Code reference validation failed, requesting correction (attempt {attempt + 1}/{max_corrections + 1})..."
                )

                # Generate corrected output
                current_output = llm_provider.generate(
                    prompt=correction_prompt,
                    system_prompt=None,
                    temperature=0.3 + (attempt * 0.1),  # Increase temperature slightly
                    max_tokens=4096,
                )
            else:
                # Max corrections reached, return best effort with warnings
                print(
                    f"Warning: Could not validate all code references after {max_corrections + 1} attempts"
                )
                invalid_refs = [r.reference.code_snippet for r in invalid_results]
                warning = f"\n\n<!-- WARNING: Unverified code references: {', '.join(invalid_refs)} -->"
                return current_output + warning

        return current_output
