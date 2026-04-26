"""Semantic diff module for comparing code changes.

This module provides semantic code analysis to understand the meaning
behind code changes, not just syntactic differences.
"""

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# Schema version for forward/backward compatibility
SEMANTIC_DIFF_SCHEMA_VERSION = "2.0"


class SemanticChangeType(str, Enum):
    """Types of semantic changes."""

    # API Changes
    API_ADDED = "api_added"
    API_REMOVED = "api_removed"
    API_MODIFIED = "api_modified"
    API_DEPRECATED = "api_deprecated"

    # Behavior Changes
    BEHAVIOR_CHANGE = "behavior_change"
    LOGIC_CHANGE = "logic_change"
    ALGORITHM_CHANGE = "algorithm_change"

    # Structure Changes
    REFACTORING = "refactoring"
    EXTRACTION = "extraction"  # Extract method/class
    INLINE = "inline"  # Inline method/class
    RENAME = "rename"

    # Data Changes
    SCHEMA_CHANGE = "schema_change"
    TYPE_CHANGE = "type_change"

    # Control Flow
    CONTROL_FLOW_CHANGE = "control_flow_change"
    ERROR_HANDLING_CHANGE = "error_handling_change"

    # Performance
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    MEMORY_OPTIMIZATION = "memory_optimization"

    # Documentation
    DOCUMENTATION_ADDED = "documentation_added"
    DOCUMENTATION_IMPROVED = "documentation_improved"

    # Testing
    TEST_ADDED = "test_added"
    TEST_MODIFIED = "test_modified"
    COVERAGE_IMPROVED = "coverage_improved"

    # Dependencies
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    DEPENDENCY_UPDATED = "dependency_updated"


@dataclass
class SemanticChangeElement:
    """Structured element information within a semantic change.

    Provides a normalized view of the code element involved in a change,
    enabling consumers (output agents, comparison) to extract class/method
    names and types without parsing free-text descriptions.
    """

    element_type: str  # "class", "function", "method", "variable", "module", "unknown"
    name: str  # Symbol name (e.g., "MyClass", "process_data")
    parent: str | None = None  # Parent class/module if applicable
    change_category: str = "modified"  # "added", "modified", "removed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_type": self.element_type,
            "name": self.name,
            "parent": self.parent,
            "change_category": self.change_category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticChangeElement":
        return cls(
            element_type=data.get("element_type", "unknown"),
            name=data.get("name", ""),
            parent=data.get("parent"),
            change_category=data.get("change_category", "modified"),
        )


@dataclass
class SemanticChange:
    """A single semantic change detected in code."""

    change_type: SemanticChangeType
    description: str
    file_path: str
    line_start: int
    line_end: int
    confidence: float  # 0.0 to 1.0
    impact_score: float  # 0.0 to 1.0 (how significant is this change)
    related_symbols: list[str] = field(default_factory=list)
    before_snippet: str | None = None
    after_snippet: str | None = None
    element: SemanticChangeElement | None = None  # Structured element info
    change_id: str | None = None  # Stable ID for comparison across analyses
    is_doc_only: bool = False  # True if change only affects documentation/comments

    def __post_init__(self) -> None:
        """Generate stable change_id if not provided."""
        if self.change_id is None:
            self.change_id = self._generate_change_id()

    def _generate_change_id(self) -> str:
        """Generate a stable ID based on file, symbol, and change type.

        Format: file_path:symbol_name:change_type:hash
        The hash incorporates line range and description for uniqueness.
        """
        symbol = self.related_symbols[0] if self.related_symbols else "unknown"
        content = f"{self.file_path}:{symbol}:{self.change_type.value}:{self.line_start}-{self.line_end}:{self.description}"
        hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:8]
        return f"{self.file_path}:{symbol}:{self.change_type.value}:{hash_suffix}"


@dataclass
class SemanticDiffResult:
    """Result of semantic diff analysis."""

    base_commit: str
    head_commit: str
    semantic_changes: list[SemanticChange]
    breaking_changes: list[SemanticChange]
    behavioral_changes: list[SemanticChange]
    refactoring_changes: list[SemanticChange]
    documentation_changes: list[SemanticChange]
    test_changes: list[SemanticChange]
    performance_changes: list[SemanticChange]
    dependency_changes: list[SemanticChange]
    schema_version: str = SEMANTIC_DIFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Initialize derived lists from semantic_changes if not provided."""
        if not self.breaking_changes:
            self.breaking_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.API_REMOVED,
                    SemanticChangeType.API_MODIFIED,
                    SemanticChangeType.BEHAVIOR_CHANGE,
                    SemanticChangeType.SCHEMA_CHANGE,
                    SemanticChangeType.TYPE_CHANGE,
                ]
                or c.impact_score >= 0.8
            ]

        if not self.behavioral_changes:
            self.behavioral_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.BEHAVIOR_CHANGE,
                    SemanticChangeType.LOGIC_CHANGE,
                    SemanticChangeType.ALGORITHM_CHANGE,
                    SemanticChangeType.CONTROL_FLOW_CHANGE,
                ]
            ]

        if not self.refactoring_changes:
            self.refactoring_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.REFACTORING,
                    SemanticChangeType.EXTRACTION,
                    SemanticChangeType.INLINE,
                    SemanticChangeType.RENAME,
                ]
            ]

        if not self.documentation_changes:
            self.documentation_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.DOCUMENTATION_ADDED,
                    SemanticChangeType.DOCUMENTATION_IMPROVED,
                ]
            ]

        if not self.test_changes:
            self.test_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.TEST_ADDED,
                    SemanticChangeType.TEST_MODIFIED,
                    SemanticChangeType.COVERAGE_IMPROVED,
                ]
            ]

        if not self.performance_changes:
            self.performance_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.PERFORMANCE_OPTIMIZATION,
                    SemanticChangeType.MEMORY_OPTIMIZATION,
                ]
            ]

        if not self.dependency_changes:
            self.dependency_changes = [
                c
                for c in self.semantic_changes
                if c.change_type
                in [
                    SemanticChangeType.DEPENDENCY_ADDED,
                    SemanticChangeType.DEPENDENCY_REMOVED,
                    SemanticChangeType.DEPENDENCY_UPDATED,
                ]
            ]

    @property
    def has_breaking_changes(self) -> bool:
        """Check if diff contains breaking changes."""
        return len(self.breaking_changes) > 0

    @property
    def total_impact_score(self) -> float:
        """Calculate total impact score (0-10)."""
        if not self.semantic_changes:
            return 0.0
        return min(10.0, sum(c.impact_score for c in self.semantic_changes))


class SemanticDiffAnalyzer:
    """Analyze semantic differences between code versions."""

    def __init__(self, config: Any, confidence_threshold: float = 0.15) -> None:
        """Initialize analyzer.

        Args:
            config: GGDes configuration
            confidence_threshold: Minimum confidence score to include a change.
                Changes below this threshold are suppressed. Default 0.15.
        """
        self.config = config
        self.confidence_threshold = confidence_threshold
        self._ast_parser: Any | None = None  # Lazy-loaded tree-sitter parser

    def _get_ast_parser(self) -> Any:
        """Lazily initialize the tree-sitter AST parser."""
        if self._ast_parser is None:
            try:
                from ggdes.parsing.ast_parser import ASTParser

                self._ast_parser = ASTParser()
            except ImportError:
                self._ast_parser = None
        return self._ast_parser

    def analyze(
        self,
        base_path: Path,
        head_path: Path,
        base_commit: str,
        head_commit: str,
        changed_files: list[str],
    ) -> SemanticDiffResult:
        """Perform semantic diff analysis.

        This method compares the code at base and head, identifying
        semantic changes beyond simple text diffs.

        Args:
            base_path: Path to base worktree
            head_path: Path to head worktree
            base_commit: Base commit hash
            head_commit: Head commit hash
            changed_files: List of files that changed

        Returns:
            SemanticDiffResult with all detected changes
        """
        semantic_changes = []

        console.print(
            f"[dim]Performing semantic diff: {base_commit[:8]}..{head_commit[:8]}[/dim]"
        )
        console.print(f"[dim]Analyzing {len(changed_files)} changed files...[/dim]")

        # Log that we're only analyzing changed files
        console.print(
            "[dim]  Only analyzing files that changed in the commit range[/dim]"
        )

        for file_path in changed_files:
            base_file = base_path / file_path
            head_file = head_path / file_path

            # Handle newly added files
            if not base_file.exists() and head_file.exists():
                console.print(f"  [dim]Analyzing new file: {file_path}[/dim]")
                new_changes = self._analyze_new_file(head_file, file_path)
                semantic_changes.extend(new_changes)
                continue

            # Handle deleted files
            if base_file.exists() and not head_file.exists():
                console.print(f"  [dim]Analyzing deleted file: {file_path}[/dim]")
                deleted_changes = self._analyze_deleted_file(base_file, file_path)
                semantic_changes.extend(deleted_changes)
                continue

            # Skip files that don't exist in either location
            if not base_file.exists() or not head_file.exists():
                continue

            # Analyze this file's changes
            file_changes = self._analyze_file_changes(base_file, head_file, file_path)
            semantic_changes.extend(file_changes)

        # Apply precision guards: suppress low-confidence changes
        semantic_changes = self._apply_precision_guards(semantic_changes)

        return SemanticDiffResult(
            base_commit=base_commit,
            head_commit=head_commit,
            semantic_changes=semantic_changes,
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

    def _apply_precision_guards(
        self, changes: list[SemanticChange]
    ) -> list[SemanticChange]:
        """Apply precision guards to filter low-confidence and doc-only changes.

        Suppresses changes below the confidence threshold and marks
        documentation-only changes with is_doc_only=True.

        Args:
            changes: Raw list of semantic changes

        Returns:
            Filtered list with low-confidence changes removed
        """
        filtered = []
        for change in changes:
            # Suppress changes below confidence threshold
            if change.confidence < self.confidence_threshold:
                console.print(
                    f"    [dim]Suppressed low-confidence change: "
                    f"{change.change_type.value} in {change.file_path} "
                    f"(confidence={change.confidence:.2f})[/dim]"
                )
                continue
            filtered.append(change)
        return filtered

    def _analyze_new_file(
        self,
        head_file: Path,
        file_path: str,
    ) -> list[SemanticChange]:
        """Analyze a newly added file.

        Args:
            head_file: Path to new file version
            file_path: Relative file path

        Returns:
            List of semantic changes detected
        """
        changes: list[SemanticChange] = []

        try:
            head_content = head_file.read_text()
        except Exception as e:
            console.print(f"    [yellow]Warning: Could not read file: {e}[/yellow]")
            return changes

        # Parse AST elements to find what was added
        elements = self._parse_ast_elements(head_content, file_path)

        if elements:
            for elem in elements:
                impact = self._calculate_impact_score(
                    change_type=SemanticChangeType.API_ADDED,
                    element_type=elem.get("type", "function"),
                    num_params=len(elem.get("parameters", [])),
                )
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.API_ADDED
                )
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_ADDED,
                        description=f"New file '{file_path}' added with {elem['type']} '{elem['name']}'",
                        file_path=file_path,
                        line_start=elem["line_start"],
                        line_end=elem["line_end"],
                        confidence=confidence,
                        impact_score=impact,
                        related_symbols=[elem["name"]],
                        after_snippet=self._extract_snippet(
                            head_content, elem["line_start"], elem["line_end"]
                        ),
                        element=SemanticChangeElement(
                            element_type=elem.get("type", "function"),
                            name=elem["name"],
                            parent=elem.get("parent"),
                            change_category="added",
                        ),
                    )
                )
        else:
            # File added but no parseable elements (e.g., config, data file)
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.API_ADDED,
                    description=f"New file '{file_path}' added",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.95,
                    impact_score=0.3,
                )
            )

        return changes

    def _analyze_deleted_file(
        self,
        base_file: Path,
        file_path: str,
    ) -> list[SemanticChange]:
        """Analyze a deleted file.

        Args:
            base_file: Path to deleted file version
            file_path: Relative file path

        Returns:
            List of semantic changes detected
        """
        changes: list[SemanticChange] = []

        try:
            base_content = base_file.read_text()
        except Exception as e:
            console.print(f"    [yellow]Warning: Could not read file: {e}[/yellow]")
            return changes

        # Parse AST elements to find what was removed
        elements = self._parse_ast_elements(base_content, file_path)

        if elements:
            for elem in elements:
                impact = self._calculate_impact_score(
                    change_type=SemanticChangeType.API_REMOVED,
                    element_type=elem.get("type", "function"),
                    num_params=len(elem.get("parameters", [])),
                )
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.API_REMOVED
                )
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_REMOVED,
                        description=f"File '{file_path}' deleted, removing {elem['type']} '{elem['name']}' (BREAKING CHANGE)",
                        file_path=file_path,
                        line_start=elem["line_start"],
                        line_end=elem["line_end"],
                        confidence=confidence,
                        impact_score=impact,
                        related_symbols=[elem["name"]],
                        before_snippet=self._extract_snippet(
                            base_content, elem["line_start"], elem["line_end"]
                        ),
                        element=SemanticChangeElement(
                            element_type=elem.get("type", "function"),
                            name=elem["name"],
                            parent=elem.get("parent"),
                            change_category="removed",
                        ),
                    )
                )
        else:
            # File deleted but no parseable elements
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.API_REMOVED,
                    description=f"File '{file_path}' deleted (BREAKING CHANGE)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.95,
                    impact_score=0.8,
                )
            )

        return changes

    def _extract_snippet(
        self, content: str, line_start: int, line_end: int, max_lines: int = 10
    ) -> str:
        """Extract a code snippet from content at given line range.

        Args:
            content: Full file content
            line_start: Starting line number (1-indexed)
            line_end: Ending line number (1-indexed)
            max_lines: Maximum number of lines to include

        Returns:
            Extracted snippet string
        """
        lines = content.splitlines()
        start_idx = max(0, line_start - 1)
        end_idx = min(len(lines), line_end)

        # Limit to max_lines
        if end_idx - start_idx > max_lines:
            end_idx = start_idx + max_lines

        snippet = "\n".join(lines[start_idx:end_idx])
        return snippet

    def _calculate_impact_score(
        self,
        change_type: SemanticChangeType,
        element_type: str = "function",
        num_params: int = 0,
        num_methods: int = 0,
    ) -> float:
        """Calculate dynamic impact score based on change context.

        Args:
            change_type: Type of semantic change
            element_type: 'function', 'class', or 'module'
            num_params: Number of parameters (for functions)
            num_methods: Number of methods (for classes)

        Returns:
            Impact score between 0.0 and 1.0
        """
        base_scores = {
            SemanticChangeType.API_ADDED: 0.3,
            SemanticChangeType.API_REMOVED: 0.8,
            SemanticChangeType.API_MODIFIED: 0.5,
            SemanticChangeType.BEHAVIOR_CHANGE: 0.6,
            SemanticChangeType.DOCUMENTATION_ADDED: 0.1,
            SemanticChangeType.DOCUMENTATION_IMPROVED: 0.15,
            SemanticChangeType.CONTROL_FLOW_CHANGE: 0.4,
            SemanticChangeType.ERROR_HANDLING_CHANGE: 0.3,
        }

        score = base_scores.get(change_type, 0.5)

        # Adjust for element type
        if element_type == "class":
            if change_type == SemanticChangeType.API_REMOVED:
                score = min(1.0, score + 0.2)  # Removing a class is more impactful
            elif change_type == SemanticChangeType.API_ADDED:
                score = min(1.0, score + 0.1)

        # Adjust for parameter changes
        if change_type == SemanticChangeType.API_MODIFIED and num_params > 5:
            score = min(1.0, score + 0.1)  # More params = more impact

        return round(min(1.0, max(0.0, score)), 2)

    def _calculate_confidence(
        self,
        has_source: bool = True,
        change_type: SemanticChangeType | None = None,
    ) -> float:
        """Calculate confidence score based on available information.

        Args:
            has_source: Whether source code is available for verification
            change_type: Type of change (affects base confidence)

        Returns:
            Confidence score between 0.0 and 1.0
        """
        base_confidence = 0.8 if has_source else 0.5

        # Some change types are more certain than others
        type_confidence = {
            SemanticChangeType.API_ADDED: 0.95,
            SemanticChangeType.API_REMOVED: 0.95,
            SemanticChangeType.API_MODIFIED: 0.85,
            SemanticChangeType.DOCUMENTATION_ADDED: 0.8,
            SemanticChangeType.DOCUMENTATION_IMPROVED: 0.75,
            SemanticChangeType.CONTROL_FLOW_CHANGE: 0.7,
            SemanticChangeType.ERROR_HANDLING_CHANGE: 0.75,
        }

        if change_type and change_type in type_confidence:
            base_confidence = type_confidence[change_type]

        if not has_source:
            base_confidence *= 0.7  # Reduce confidence without source

        return round(min(1.0, max(0.0, base_confidence)), 2)

    def _analyze_file_changes(
        self,
        base_file: Path,
        head_file: Path,
        file_path: str,
    ) -> list[SemanticChange]:
        """Analyze semantic changes in a single file.

        Args:
            base_file: Path to base version
            head_file: Path to head version
            file_path: Relative file path

        Returns:
            List of semantic changes detected
        """
        changes: list[SemanticChange] = []

        try:
            base_content = base_file.read_text()
            head_content = head_file.read_text()
        except Exception as e:
            console.print(f"    [yellow]Warning: Could not read file: {e}[/yellow]")
            return changes

        # Log language detection
        lang = "C++" if self._is_cpp_file(file_path) else "Python"
        console.print(f"  [dim]Analyzing changed file: {file_path} ({lang})[/dim]")

        # Detect function/method signature changes
        signature_changes = self._detect_signature_changes(
            base_content, head_content, file_path
        )
        changes.extend(signature_changes)
        if signature_changes:
            console.print(
                f"    [dim]  - {len(signature_changes)} signature change(s) detected[/dim]"
            )

        # Detect documentation changes
        doc_changes = self._detect_documentation_changes(
            base_content, head_content, file_path
        )
        changes.extend(doc_changes)
        if doc_changes:
            console.print(
                f"    [dim]  - {len(doc_changes)} documentation change(s) detected[/dim]"
            )

        # Detect control flow changes
        control_flow_changes = self._detect_control_flow_changes(
            base_content, head_content, file_path
        )
        changes.extend(control_flow_changes)
        if control_flow_changes:
            console.print(
                f"    [dim]  - {len(control_flow_changes)} control flow change(s) detected[/dim]"
            )

        # Detect error handling changes
        error_changes = self._detect_error_handling_changes(
            base_content, head_content, file_path
        )
        changes.extend(error_changes)
        if error_changes:
            console.print(
                f"    [dim]  - {len(error_changes)} error handling change(s) detected[/dim]"
            )

        return changes

    def _detect_signature_changes(
        self,
        base_content: str,
        head_content: str,
        file_path: str,
    ) -> list[SemanticChange]:
        """Detect function/method signature changes.

        Uses AST parsing to find changes in:
        - Function names
        - Parameter lists (added/removed/renamed params)
        - Return types
        - Access modifiers (public/private)
        """
        changes = []

        # Parse ASTs for both versions
        base_elements = self._parse_ast_elements(base_content, file_path)
        head_elements = self._parse_ast_elements(head_content, file_path)

        # Compare functions/classes
        base_by_name = {e["name"]: e for e in base_elements}
        head_by_name = {e["name"]: e for e in head_elements}

        # Find added functions
        for name, element in head_by_name.items():
            if name not in base_by_name:
                impact = self._calculate_impact_score(
                    change_type=SemanticChangeType.API_ADDED,
                    element_type=element.get("type", "function"),
                    num_params=len(element.get("parameters", [])),
                )
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.API_ADDED
                )
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_ADDED,
                        description=f"New {element['type']} '{name}' added",
                        file_path=file_path,
                        line_start=element["line_start"],
                        line_end=element["line_end"],
                        confidence=confidence,
                        impact_score=impact,
                        related_symbols=[name],
                        after_snippet=self._extract_snippet(
                            head_content, element["line_start"], element["line_end"]
                        ),
                        element=SemanticChangeElement(
                            element_type=element.get("type", "function"),
                            name=name,
                            parent=element.get("parent"),
                            change_category="added",
                        ),
                    )
                )

        # Find removed functions
        for name, element in base_by_name.items():
            if name not in head_by_name:
                impact = self._calculate_impact_score(
                    change_type=SemanticChangeType.API_REMOVED,
                    element_type=element.get("type", "function"),
                    num_params=len(element.get("parameters", [])),
                )
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.API_REMOVED
                )
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_REMOVED,
                        description=f"{element['type'].capitalize()} '{name}' removed (BREAKING CHANGE)",
                        file_path=file_path,
                        line_start=element["line_start"],
                        line_end=element["line_end"],
                        confidence=confidence,
                        impact_score=impact,
                        related_symbols=[name],
                        before_snippet=self._extract_snippet(
                            base_content, element["line_start"], element["line_end"]
                        ),
                        element=SemanticChangeElement(
                            element_type=element.get("type", "function"),
                            name=name,
                            parent=element.get("parent"),
                            change_category="removed",
                        ),
                    )
                )

        # Find modified functions (signature changes)
        for name in set(base_by_name.keys()) & set(head_by_name.keys()):
            base_el = base_by_name[name]
            head_el = head_by_name[name]

            # Check parameter changes
            base_params = set(base_el.get("parameters", []))
            head_params = set(head_el.get("parameters", []))

            if base_params != head_params:
                added = head_params - base_params
                removed = base_params - head_params

                change_desc = (
                    f"{head_el['type'].capitalize()} '{name}' signature modified"
                )
                if added:
                    change_desc += f", added params: {', '.join(added)}"
                if removed:
                    change_desc += f", removed params: {', '.join(removed)}"

                # Calculate impact based on parameter changes
                impact = self._calculate_impact_score(
                    change_type=SemanticChangeType.API_MODIFIED,
                    element_type=head_el.get("type", "function"),
                    num_params=len(head_el.get("parameters", [])),
                )
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.API_MODIFIED
                )

                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_MODIFIED,
                        description=change_desc,
                        file_path=file_path,
                        line_start=head_el["line_start"],
                        line_end=head_el["line_end"],
                        confidence=confidence,
                        impact_score=impact,
                        related_symbols=[name],
                        before_snippet=self._extract_snippet(
                            base_content, base_el["line_start"], base_el["line_end"]
                        ),
                        after_snippet=self._extract_snippet(
                            head_content, head_el["line_start"], head_el["line_end"]
                        ),
                        element=SemanticChangeElement(
                            element_type=head_el.get("type", "function"),
                            name=name,
                            parent=head_el.get("parent"),
                            change_category="modified",
                        ),
                    )
                )

        return changes

    def _detect_documentation_changes(
        self,
        base_content: str,
        head_content: str,
        file_path: str,
    ) -> list[SemanticChange]:
        """Detect documentation changes in code."""
        changes = []

        # Simple heuristic: count docstrings and comments
        base_docstrings = self._count_docstrings(base_content)
        head_docstrings = self._count_docstrings(head_content)

        # DOCUMENTATION_ADDED: when going from 0 to >0 docstrings
        if base_docstrings == 0 and head_docstrings > 0:
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.DOCUMENTATION_ADDED,
                    description=f"Added documentation ({head_docstrings} docstring(s) added)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.8,
                    impact_score=0.2,
                    is_doc_only=True,
                )
            )
        # DOCUMENTATION_IMPROVED: when base > 0 and head increased by 20%+
        elif base_docstrings > 0 and head_docstrings > base_docstrings * 1.2:
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.DOCUMENTATION_IMPROVED,
                    description=f"Documentation improved ({base_docstrings} → {head_docstrings} docstrings)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.75,
                    impact_score=0.15,
                    is_doc_only=True,
                )
            )

        return changes

    def _detect_control_flow_changes(
        self,
        base_content: str,
        head_content: str,
        file_path: str,
    ) -> list[SemanticChange]:
        """Detect changes in control flow (if statements, loops, etc.)."""
        changes = []

        # Count control flow constructs
        base_control = self._count_control_structures(base_content)
        head_control = self._count_control_structures(head_content)

        # Get threshold from config if available, default to 2
        config_sd = getattr(self.config, "semantic_diff", None)
        threshold = getattr(config_sd, "control_flow_threshold", 2) if config_sd else 2
        # Handle MagicMock (in tests)
        if not isinstance(threshold, (int, float)):
            threshold = 2

        if base_control != head_control:
            diff = head_control - base_control
            if abs(diff) >= threshold:  # Significant change
                confidence = self._calculate_confidence(
                    has_source=True, change_type=SemanticChangeType.CONTROL_FLOW_CHANGE
                )
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.CONTROL_FLOW_CHANGE,
                        description=f"Control flow modified ({base_control} → {head_control} structures)",
                        file_path=file_path,
                        line_start=1,
                        line_end=1,
                        confidence=confidence,
                        impact_score=0.5,
                    )
                )

        return changes

    def _detect_error_handling_changes(
        self,
        base_content: str,
        head_content: str,
        file_path: str,
    ) -> list[SemanticChange]:
        """Detect changes in error handling (try/except, error returns)."""
        changes = []

        # Count try-except blocks using AST
        base_try = self._count_try_blocks(base_content)
        head_try = self._count_try_blocks(head_content)

        if head_try > base_try:
            confidence = self._calculate_confidence(
                has_source=True, change_type=SemanticChangeType.ERROR_HANDLING_CHANGE
            )
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.ERROR_HANDLING_CHANGE,
                    description=f"Improved error handling ({base_try}→{head_try} try/except blocks)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=confidence,
                    impact_score=0.4,
                )
            )
        elif base_try > head_try:
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.ERROR_HANDLING_CHANGE,
                    description=f"Reduced error handling ({base_try}→{head_try} try/except blocks)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.75,
                    impact_score=0.5,  # Removing error handling is more impactful
                )
            )

        return changes

    def _count_try_blocks(self, content: str) -> int:
        """Count try/except blocks using AST parsing."""
        try:
            import ast

            tree = ast.parse(content)
            count = 0

            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    count += 1

            return count
        except (SyntaxError, ValueError):
            return 0

    def _is_cpp_file(self, file_path: str) -> bool:
        """Check if file is a C++ file based on extension.

        Args:
            file_path: Relative file path

        Returns:
            True if file is C++, False otherwise
        """
        cpp_extensions = {".cpp", ".h", ".hpp", ".cc", ".cxx", ".c"}
        return Path(file_path).suffix.lower() in cpp_extensions

    def _parse_cpp_elements(self, content: str, file_path: str) -> list[dict[str, Any]]:
        """Parse AST elements from C++ code using tree-sitter.

        Args:
            content: C++ source code content
            file_path: Relative file path

        Returns:
            List of dicts with:
            - name: element name
            - type: 'function' or 'class'
            - parameters: list of parameter names (for functions)
            - line_start: starting line number
            - line_end: ending line number
            - parent: parent class/namespace if applicable
        """
        elements: list[dict[str, Any]] = []

        parser = self._get_ast_parser()
        if parser is None:
            return elements

        try:
            # Parse the content
            result = parser.parse_file_content(content, file_path)
            if not result or not result.elements:
                return elements

            for elem in result.elements:
                # Map element_type to our format
                elem_type_str = str(elem.element_type).lower()
                if elem_type_str in ("class", "struct", "interface"):
                    elem_type = "class"
                elif elem_type_str in ("function", "method", "constructor", "destructor"):
                    elem_type = "function"
                else:
                    continue  # Skip other element types

                # Extract parameter names from children or signature
                parameters: list[str] = []
                if elem.children:
                    for child in elem.children:
                        if str(child.element_type).lower() == "parameter":
                            parameters.append(child.name)

                elements.append(
                    {
                        "name": elem.name,
                        "type": elem_type,
                        "parameters": parameters,
                        "line_start": elem.start_line,
                        "line_end": elem.end_line,
                        "parent": None,  # Could extract from nested structure if needed
                    }
                )

        except Exception:
            pass

        return elements

    def _parse_ast_elements(self, content: str, file_path: str) -> list[dict[str, Any]]:
        """Parse AST elements from code content.

        Returns list of dicts with:
        - name: element name
        - type: 'function' or 'class'
        - parameters: list of parameter names (for functions)
        - line_start: starting line number
        - line_end: ending line number
        """
        # Route to C++ parser if applicable
        if self._is_cpp_file(file_path):
            return self._parse_cpp_elements(content, file_path)

        elements = []

        try:
            import ast

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    elements.append(
                        {
                            "name": node.name,
                            "type": "function",
                            "parameters": [arg.arg for arg in node.args.args],
                            "line_start": node.lineno,
                            "line_end": node.end_lineno
                            if hasattr(node, "end_lineno")
                            else node.lineno,
                        }
                    )
                elif isinstance(node, ast.ClassDef):
                    elements.append(
                        {
                            "name": node.name,
                            "type": "class",
                            "parameters": [],
                            "line_start": node.lineno,
                            "line_end": node.end_lineno
                            if hasattr(node, "end_lineno")
                            else node.lineno,
                        }
                    )

        except (SyntaxError, ValueError):
            pass

        return elements

    def _count_docstrings(self, content: str) -> int:
        """Count docstrings in code."""
        try:
            import ast

            tree = ast.parse(content)
            count = 0

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    docstring = ast.get_docstring(node)
                    if docstring:
                        count += 1

            return count
        except (SyntaxError, ValueError):
            return 0

    def _count_control_structures(self, content: str) -> int:
        """Count control flow structures (if, for, while)."""
        try:
            import ast

            tree = ast.parse(content)
            count = 0

            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.For, ast.While)):
                    count += 1

            return count
        except (SyntaxError, ValueError):
            return 0


def _validate_semantic_diff_data(data: dict[str, Any]) -> None:
    """Validate semantic diff data before writing to disk.

    Ensures required fields are present and types are correct.
    Raises ValueError if validation fails.
    """
    required_top = {"schema_version", "base_commit", "head_commit", "semantic_changes", "summary"}
    missing = required_top - set(data.keys())
    if missing:
        raise ValueError(f"Missing required top-level fields: {missing}")

    for i, change in enumerate(data["semantic_changes"]):
        required_change = {"change_type", "description", "file_path", "confidence", "impact_score"}
        missing_change = required_change - set(change.keys())
        if missing_change:
            raise ValueError(f"Change at index {i} missing fields: {missing_change}")

        # Validate confidence and impact_score ranges
        conf = change.get("confidence", 0)
        impact = change.get("impact_score", 0)
        if not (0.0 <= conf <= 1.0):
            raise ValueError(f"Change at index {i} has invalid confidence: {conf}")
        if not (0.0 <= impact <= 1.0):
            raise ValueError(f"Change at index {i} has invalid impact_score: {impact}")


def save_semantic_diff(
    result: SemanticDiffResult,
    output_path: Path,
) -> None:
    """Save semantic diff result to JSON.

    Validates the data before writing to ensure schema consistency.

    Args:
        result: SemanticDiffResult to save
        output_path: Path to save JSON file
    """
    data = {
        "schema_version": result.schema_version,
        "base_commit": result.base_commit,
        "head_commit": result.head_commit,
        "semantic_changes": [
            {
                "change_id": c.change_id,
                "change_type": c.change_type.value,
                "description": c.description,
                "file_path": c.file_path,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "confidence": c.confidence,
                "impact_score": c.impact_score,
                "related_symbols": c.related_symbols,
                "before_snippet": c.before_snippet,
                "after_snippet": c.after_snippet,
                "element": c.element.to_dict() if c.element else None,
                "is_doc_only": c.is_doc_only,
            }
            for c in result.semantic_changes
        ],
        "summary": {
            "total_changes": len(result.semantic_changes),
            "breaking_changes": len(result.breaking_changes),
            "behavioral_changes": len(result.behavioral_changes),
            "refactoring_changes": len(result.refactoring_changes),
            "documentation_changes": len(result.documentation_changes),
            "test_changes": len(result.test_changes),
            "performance_changes": len(result.performance_changes),
            "dependency_changes": len(result.dependency_changes),
            "has_breaking_changes": result.has_breaking_changes,
            "total_impact_score": result.total_impact_score,
        },
    }

    # Validate before writing
    _validate_semantic_diff_data(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2))
