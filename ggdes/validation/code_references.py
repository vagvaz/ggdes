"""Code reference validation for LLM outputs."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class CodeReference:
    """A code reference found in LLM output."""

    file_path: Optional[str]  # File path if specified
    line_number: Optional[int]  # Line number if specified
    code_snippet: str  # The referenced code
    reference_type: str  # 'function', 'class', 'variable', 'snippet', 'code_block'


@dataclass
class CodeBlockValidationResult:
    """Result of validating a code block against actual source code."""

    code_block: str  # The code block found in LLM output
    language: str  # Language identifier (e.g., 'python', 'cpp')
    is_valid: bool  # Whether the code block matches actual source
    matched_element: str | None  # Name of the matched code element, if any
    similarity: float  # Similarity score (0.0-1.0) to actual source
    error_message: str | None = None


@dataclass
class ReferenceValidationResult:
    """Result of validating a code reference."""

    reference: CodeReference
    is_valid: bool
    found_in: str | None  # 'diff', 'ast', 'file', 'source_code', or None
    error_message: str | None = None


class CodeReferenceValidator:
    """Validate code references in LLM output against diffs and AST.

    Enhanced to also validate code blocks (fenced code snippets) against
    actual source code, detecting hallucinated code that doesn't match
    the real implementation.
    """

    def __init__(
        self,
        repo_path: Path,
        changed_files: list[str] | None = None,
        code_elements: Optional[Dict[str, Dict[str, Any]]] = None,
        diff_content: str | None = None,
        source_code: Optional[Dict[str, str]] = None,
    ):
        """Initialize code reference validator.

        Args:
            repo_path: Path to the repository
            changed_files: List of files that changed in the diff
            code_elements: Dict of code elements from AST parsing (name -> element info).
                Each element dict may contain 'source_code' key with actual source.
            diff_content: The git diff content for content verification
            source_code: Optional dict mapping element names to their source code.
                Used for validating code blocks against actual implementations.
        """
        self.repo_path = repo_path
        self.changed_files = set(changed_files or [])
        self.code_elements = code_elements or {}
        self.diff_content = diff_content or ""

        # Build source code index from code_elements and explicit source_code
        self.source_code: Dict[str, str] = {}
        if source_code:
            self.source_code.update(source_code)
        # Also extract source_code from code_elements if available
        for name, elem_data in self.code_elements.items():
            if isinstance(elem_data, dict) and "source_code" in elem_data:
                self.source_code[name] = elem_data["source_code"]

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

    def extract_code_blocks(self, text: str) -> list[tuple[str, str]]:
        """Extract fenced code blocks from text.

        Args:
            text: Text containing fenced code blocks

        Returns:
            List of (language, code_content) tuples
        """
        pattern = r"```(\w+)?\s*\n(.*?)```"
        blocks = []
        for match in re.finditer(pattern, text, re.DOTALL):
            language = match.group(1) or ""
            code = match.group(2).strip()
            if code:
                blocks.append((language, code))
        return blocks

    def validate_code_blocks(
        self, text: str, similarity_threshold: float = 0.6
    ) -> list[CodeBlockValidationResult]:
        """Validate code blocks in text against actual source code.

        This detects hallucinated code blocks that don't match any real
        source code in the repository.

        Args:
            text: Text containing fenced code blocks
            similarity_threshold: Minimum similarity score (0.0-1.0) to consider
                a code block as valid. Default 0.6 (60% similar).

        Returns:
            List of validation results for each code block found
        """
        blocks = self.extract_code_blocks(text)
        results = []

        for language, code_block in blocks:
            result = self._validate_code_block(
                code_block, language, similarity_threshold
            )
            results.append(result)

        return results

    def _validate_code_block(
        self, code_block: str, language: str, similarity_threshold: float
    ) -> CodeBlockValidationResult:
        """Validate a single code block against source code.

        Args:
            code_block: The code block content
            language: Language identifier
            similarity_threshold: Minimum similarity to consider valid

        Returns:
            Validation result
        """
        normalized_block = self._normalize_code(code_block)

        # Skip very short code blocks (likely just identifiers or one-liners)
        if len(normalized_block) < 20:
            return CodeBlockValidationResult(
                code_block=code_block,
                language=language,
                is_valid=True,  # Too short to validate meaningfully
                matched_element=None,
                similarity=1.0,
                error_message=None,
            )

        best_match = None
        best_similarity = 0.0

        # Check against source code from code elements
        for elem_name, source in self.source_code.items():
            if not source:
                continue
            normalized_source = self._normalize_code(source)

            # Skip very short source code
            if len(normalized_source) < 10:
                continue

            similarity = self._compute_similarity(normalized_block, normalized_source)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = elem_name

        # Also check against diff snippets
        for file_path, snippets in self.diff_snippets.items():
            for snippet in snippets:
                normalized_snippet = self._normalize_code(snippet)
                if len(normalized_snippet) < 10:
                    continue
                similarity = self._compute_similarity(
                    normalized_block, normalized_snippet
                )
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = f"diff:{file_path}"

        is_valid = best_similarity >= similarity_threshold

        return CodeBlockValidationResult(
            code_block=code_block,
            language=language,
            is_valid=is_valid,
            matched_element=best_match,
            similarity=best_similarity,
            error_message=None
            if is_valid
            else f"Code block does not match any known source code (best similarity: {best_similarity:.1%} with '{best_match}')",
        )

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Compute similarity between two normalized code strings.

        Uses a combination of substring matching and token overlap
        to determine if code blocks are similar enough.

        Args:
            text1: First normalized code string
            text2: Second normalized code string

        Returns:
            Similarity score between 0.0 and 1.0
        """
        if not text1 or not text2:
            return 0.0

        # Check if one is a substring of the other (strong match)
        if text1 in text2 or text2 in text1:
            # Proportional to the size of the smaller string
            min_len = min(len(text1), len(text2))
            max_len = max(len(text1), len(text2))
            return min_len / max_len if max_len > 0 else 0.0

        # Token-based overlap (Jaccard-like)
        tokens1 = set(text1.split())
        tokens2 = set(text2.split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1 & tokens2
        union = tokens1 | tokens2

        # Jaccard similarity
        jaccard = len(intersection) / len(union) if union else 0.0

        # Also check for n-gram overlap (bigrams) for structural similarity
        bigrams1 = (
            set(zip(text1.split(), text1.split()[1:]))
            if len(text1.split()) > 1
            else set()
        )
        bigrams2 = (
            set(zip(text2.split(), text2.split()[1:]))
            if len(text2.split()) > 1
            else set()
        )

        if bigrams1 and bigrams2:
            bigram_intersection = bigrams1 & bigrams2
            bigram_union = bigrams1 | bigrams2
            bigram_sim = (
                len(bigram_intersection) / len(bigram_union) if bigram_union else 0.0
            )
        else:
            bigram_sim = 0.0

        # Weighted combination: bigram similarity is more indicative of structural match
        return 0.4 * jaccard + 0.6 * bigram_sim

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
        self, llm_output: str, llm_provider: Any, max_corrections: int = 2
    ) -> str:
        """Validate LLM output and request corrections if needed.

        Validates both code references (file paths, function/class names) and
        code blocks (fenced code snippets) against actual source code.

        Args:
            llm_output: The LLM-generated text
            llm_provider: LLM provider to request corrections
            max_corrections: Maximum number of correction attempts

        Returns:
            Validated (and potentially corrected) text
        """
        logger.info(
            "Code reference validation starting | max_corrections=%d", max_corrections
        )
        current_output = llm_output

        for attempt in range(max_corrections + 1):
            # Validate code references (file paths, function/class names)
            ref_results = self.validate_references_in_text(current_output)
            invalid_refs = [r for r in ref_results if not r.is_valid]

            # Validate code blocks against actual source code
            block_results = self.validate_code_blocks(current_output)
            invalid_blocks = [r for r in block_results if not r.is_valid]

            if not invalid_refs and not invalid_blocks:
                # All references and code blocks are valid
                return current_output

            if attempt < max_corrections:
                # Build correction prompt
                correction_prompt = self._build_correction_prompt(
                    invalid_refs, invalid_blocks, current_output
                )

                logger.warning(
                    "Code reference validation failed, requesting correction "
                    "(attempt %d/%d) | invalid_refs=%d invalid_blocks=%d",
                    attempt + 1,
                    max_corrections + 1,
                    len(invalid_refs),
                    len(invalid_blocks),
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
                warnings = []
                if invalid_refs:
                    ref_names = [r.reference.code_snippet for r in invalid_refs]
                    warnings.append(
                        f"Unverified code references: {', '.join(ref_names)}"
                    )
                if invalid_blocks:
                    block_info = [
                        f"'{r.matched_element or 'unknown'}' (similarity: {r.similarity:.0%})"
                        for r in invalid_blocks
                    ]
                    warnings.append(
                        f"Potentially hallucinated code blocks: {', '.join(block_info)}"
                    )

                warning_text = "\n\n<!-- WARNING: " + "; ".join(warnings) + " -->"
                return current_output + warning_text

        return current_output

    def _build_correction_prompt(
        self,
        invalid_refs: list[ReferenceValidationResult],
        invalid_blocks: list[CodeBlockValidationResult],
        original_text: str,
    ) -> str:
        """Build a correction prompt for invalid references and code blocks.

        Args:
            invalid_refs: List of invalid reference validation results
            invalid_blocks: List of invalid code block validation results
            original_text: The original LLM output

        Returns:
            Correction prompt for the LLM
        """
        errors = []

        for result in invalid_refs:
            ref = result.reference
            if ref.file_path:
                errors.append(f"- File '{ref.file_path}': {result.error_message}")
            else:
                errors.append(
                    f"- {ref.reference_type.capitalize()} '{ref.code_snippet}': {result.error_message}"
                )

        for result in invalid_blocks:
            errors.append(
                f"- Code block (language: {result.language}): {result.error_message}"
            )

        available_files = "\n".join(f"  - {f}" for f in sorted(self.changed_files))
        available_elements = "\n".join(
            f"  - {name}" for name in sorted(self.code_elements.keys())[:20]
        )

        # Include available source code snippets for reference
        source_code_section = ""
        if self.source_code:
            source_code_lines = []
            for name, code in list(self.source_code.items())[:10]:
                # Truncate long source code to keep prompt manageable
                truncated = code[:500] + "..." if len(code) > 500 else code
                source_code_lines.append(f"  ### {name}\n  ```\n  {truncated}\n  ```")
            if source_code_lines:
                source_code_section = (
                    "\n3. Available source code for reference:\n"
                    + "\n".join(source_code_lines)
                )

        prompt = f"""Your previous response contains code references that could not be verified:

{chr(10).join(errors)}

You must only reference code that exists in:
1. The changed files (diff):
{available_files}

2. The parsed code elements:
{available_elements}
{source_code_section}

Please rewrite your response, ensuring:
- All file paths match exactly with the changed files
- All function/class names exist in the parsed code
- Code snippets match content from the diff or available source code
- If referencing a file, use the exact path from the diff
- Do NOT fabricate or hallucinate code that doesn't appear in the source code above

Original response:
{original_text}

Please provide a corrected response with valid code references and accurate code blocks:"""

        return prompt
