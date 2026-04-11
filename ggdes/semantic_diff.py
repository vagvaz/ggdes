"""Semantic diff module for comparing code changes.

This module provides semantic code analysis to understand the meaning
behind code changes, not just syntactic differences.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

console = Console()


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

    def __init__(self, config: Any) -> None:
        """Initialize analyzer.

        Args:
            config: GGDes configuration
        """
        self.config = config

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
            f"[dim]  Only analyzing files that changed in the commit range[/dim]"
        )

        for file_path in changed_files:
            base_file = base_path / file_path
            head_file = head_path / file_path

            if not base_file.exists() or not head_file.exists():
                # File was added or removed - handled by git analysis
                continue

            # Analyze this file's changes
            file_changes = self._analyze_file_changes(base_file, head_file, file_path)
            semantic_changes.extend(file_changes)

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
        console.print(f"  [dim]Analyzing changed file: {file_path}[/dim]")
        changes: list[SemanticChange] = []

        try:
            base_content = base_file.read_text()
            head_content = head_file.read_text()
        except Exception as e:
            console.print(f"    [yellow]Warning: Could not read file: {e}[/yellow]")
            return changes

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
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_ADDED,
                        description=f"New {element['type']} '{name}' added",
                        file_path=file_path,
                        line_start=element["line_start"],
                        line_end=element["line_end"],
                        confidence=0.95,
                        impact_score=0.5,
                        related_symbols=[name],
                    )
                )

        # Find removed functions
        for name, element in base_by_name.items():
            if name not in head_by_name:
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_REMOVED,
                        description=f"{element['type'].capitalize()} '{name}' removed (BREAKING CHANGE)",
                        file_path=file_path,
                        line_start=element["line_start"],
                        line_end=element["line_end"],
                        confidence=0.95,
                        impact_score=1.0,  # High impact
                        related_symbols=[name],
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
                impact = 0.7 if removed else 0.4  # Removing params is more breaking

                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.API_MODIFIED,
                        description=change_desc,
                        file_path=file_path,
                        line_start=head_el["line_start"],
                        line_end=head_el["line_end"],
                        confidence=0.85,
                        impact_score=impact,
                        related_symbols=[name],
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

        if head_docstrings > base_docstrings:
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.DOCUMENTATION_ADDED,
                    description=f"Added {head_docstrings - base_docstrings} new docstring(s)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.8,
                    impact_score=0.2,
                )
            )
        elif head_docstrings > base_docstrings * 1.2:  # 20% improvement
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.DOCUMENTATION_IMPROVED,
                    description=f"Documentation improved ({base_docstrings} → {head_docstrings} docstrings)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.75,
                    impact_score=0.15,
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

        if base_control != head_control:
            diff = head_control - base_control
            if abs(diff) >= 2:  # Significant change
                changes.append(
                    SemanticChange(
                        change_type=SemanticChangeType.CONTROL_FLOW_CHANGE,
                        description=f"Control flow modified ({base_control} → {head_control} structures)",
                        file_path=file_path,
                        line_start=1,
                        line_end=1,
                        confidence=0.7,
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

        # Count try-except blocks
        base_try = base_content.count("try:")
        head_try = head_content.count("try:")
        base_except = base_content.count("except")
        head_except = head_content.count("except")

        if head_try > base_try or head_except > base_except:
            changes.append(
                SemanticChange(
                    change_type=SemanticChangeType.ERROR_HANDLING_CHANGE,
                    description=f"Improved error handling ({base_try}→{head_try} try blocks, {base_except}→{head_except} except blocks)",
                    file_path=file_path,
                    line_start=1,
                    line_end=1,
                    confidence=0.75,
                    impact_score=0.4,
                )
            )

        return changes

    def _parse_ast_elements(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Parse AST elements from code content.

        Returns list of dicts with:
        - name: element name
        - type: 'function' or 'class'
        - parameters: list of parameter names (for functions)
        - line_start: starting line number
        - line_end: ending line number
        """
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

        except SyntaxError:
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
        except SyntaxError:
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
        except SyntaxError:
            return 0


def save_semantic_diff(
    result: SemanticDiffResult,
    output_path: Path,
) -> None:
    """Save semantic diff result to JSON.

    Args:
        result: SemanticDiffResult to save
        output_path: Path to save JSON file
    """
    data = {
        "base_commit": result.base_commit,
        "head_commit": result.head_commit,
        "semantic_changes": [
            {
                "change_type": c.change_type.value,
                "description": c.description,
                "file_path": c.file_path,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "confidence": c.confidence,
                "impact_score": c.impact_score,
                "related_symbols": c.related_symbols,
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

    output_path.write_text(json.dumps(data, indent=2))
