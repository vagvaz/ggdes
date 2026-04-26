"""Tool executor for LLM function calling.

Implements the actual logic for each tool, accessing the git repository,
file system, and AST data to provide grounded responses.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console

from ggdes.tools.definitions import (
    ToolCall,
    ToolResult,
    get_tool_by_name,
)

console = Console()


class ToolExecutor:
    """Executes tool calls from LLM agents against the codebase.

    Provides grounded access to repository data, preventing hallucinations
    by letting the LLM verify its claims against actual code.
    """

    def __init__(
        self,
        repo_path: Path,
        changed_files: list[dict[str, Any]] | None = None,
        ast_elements: dict[str, list[Any]] | None = None,
        commit_range: str | None = None,
        focus_commits: list[str] | None = None,
        source_diffs_cache: dict[str, dict[str, str]] | None = None,
    ):
        """Initialize tool executor.

        Args:
            repo_path: Path to the git repository
            changed_files: List of changed file dicts from git analysis
            ast_elements: Dict mapping file paths to AST element lists
            commit_range: Git commit range being analyzed
            focus_commits: Specific commits being focused on
            source_diffs_cache: Pre-computed source code diffs (element_name -> {before, after, diff, file_path})
        """
        self.repo_path = repo_path
        self.changed_files = changed_files or []
        self.ast_elements = ast_elements or {}
        self.commit_range = commit_range
        self.focus_commits = focus_commits
        # Pre-computed source diffs: keyed by element_name or "file_path::element_name"
        self._source_diffs_cache: dict[str, dict[str, str]] = source_diffs_cache or {}

        # Build lookup structures
        self._element_names: dict[str, list[str]] = {}  # name -> [file_paths]
        self._file_elements: dict[str, list[Any]] = {}  # filepath -> [elements]
        self._build_element_index()

    def _build_element_index(self) -> None:
        """Build indexes for fast element lookup."""
        for file_path, elements in self.ast_elements.items():
            self._file_elements[file_path] = elements
            for elem in elements:
                name = getattr(elem, "name", None) or (
                    elem.get("name") if isinstance(elem, dict) else None
                )
                if name:
                    if name not in self._element_names:
                        self._element_names[name] = []
                    self._element_names[name].append(file_path)

    def set_source_diffs_cache(self, source_diffs: dict[str, dict[str, str]]) -> None:
        """Set or update the pre-computed source diffs cache.

        This lets get_element_source return instantly for cached elements
        without requiring another LLM request.

        Args:
            source_diffs: Dict mapping element key (file_path::name or just name)
                          to {before, after, diff, element_name, file_path}
        """
        self._source_diffs_cache = source_diffs

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute a tool call.

        Args:
            call: Tool call request

        Returns:
            Tool execution result
        """
        tool = get_tool_by_name(call.tool_name)
        if not tool:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                result=None,
                error=f"Unknown tool: {call.tool_name}",
            )

        handler: Any = {
            "get_changed_files": self._get_changed_files,
            "read_file": self._read_file,
            "search_code": self._search_code,
            "validate_reference": self._validate_reference,
            "get_ast_elements": self._get_ast_elements,
            "get_element_source": self._get_element_source,
            "find_element_name": self._find_element_name,
        }.get(call.tool_name)

        if not handler:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                result=None,
                error=f"No handler for tool: {call.tool_name}",
            )

        try:
            result = handler(**call.arguments)
            return ToolResult(
                tool_name=call.tool_name,
                success=True,
                result=result,
            )
        except Exception as e:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                result=None,
                error=str(e),
            )

    def execute_batch(self, calls: list[ToolCall]) -> list[ToolResult]:
        """Execute multiple tool calls.

        Args:
            calls: List of tool call requests

        Returns:
            List of tool execution results in the same order
        """
        return [self.execute(call) for call in calls]

    # ========================================================================
    # Tool Implementations
    # ========================================================================

    def _get_changed_files(
        self,
        include_contextual: bool = True,
        change_type_filter: str | None = None,
    ) -> dict[str, Any]:
        """Get changed files categorized by focus level.

        Args:
            include_contextual: Whether to include contextual files
            change_type_filter: Optional filter by change type

        Returns:
            Dict with 'focused' and 'contextual' file lists
        """
        focused = []
        contextual = []

        for file_info in self.changed_files:
            # Handle both dict and object formats
            if isinstance(file_info, dict):
                path = file_info.get("path", file_info.get("file_path", ""))
                change_type = file_info.get("change_type", "modified")
                lines_added = file_info.get("lines_added", 0)
                lines_deleted = file_info.get("lines_deleted", 0)
                summary = file_info.get("summary", "")
            else:
                path = getattr(file_info, "path", "") or getattr(
                    file_info, "file_path", ""
                )
                change_type = getattr(file_info, "change_type", "modified")
                lines_added = getattr(file_info, "lines_added", 0)
                lines_deleted = getattr(file_info, "lines_deleted", 0)
                summary = getattr(file_info, "summary", "")

            # Apply change type filter
            if change_type_filter and change_type != change_type_filter:
                continue

            entry = {
                "path": path,
                "change_type": change_type,
                "lines_added": lines_added,
                "lines_deleted": lines_deleted,
                "summary": summary,
            }

            # Determine if this is a focused or contextual file
            # Focused files are directly changed in the commit range
            # Contextual files are referenced/imported by focused files
            if path and self._is_focused_file(path):
                focused.append(entry)
            else:
                contextual.append(entry)

        result = {"focused": focused}
        if include_contextual:
            result["contextual"] = contextual

        return result

    def _is_focused_file(self, path: str) -> bool:
        """Check if a file is in the focused commit changes.

        Args:
            path: File path relative to repo root

        Returns:
            True if the file is directly changed in focused commits
        """
        # If we have focus commits, check git diff for those specific commits
        if self.focus_commits:
            try:
                for commit in self.focus_commits:
                    result = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.repo_path),
                            "diff-tree",
                            "--no-commit-id",
                            "--name-only",
                            "-r",
                            commit,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if path in result.stdout.strip().split("\n"):
                        return True
                return False
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # If no focus commits, all changed files are considered focused
        return True

    def _read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Read a file from the repository.

        Args:
            path: File path relative to repo root
            start_line: Starting line (1-indexed, inclusive)
            end_line: Ending line (1-indexed, inclusive)

        Returns:
            Dict with file contents and metadata
        """
        file_path = self.repo_path / path

        # Security: prevent path traversal
        try:
            file_path.resolve().relative_to(self.repo_path.resolve())
        except ValueError:
            return {
                "error": f"Path traversal denied: {path}",
                "content": None,
            }

        if not file_path.exists():
            return {
                "error": f"File not found: {path}",
                "content": None,
            }

        if not file_path.is_file():
            return {
                "error": f"Not a file: {path}",
                "content": None,
            }

        # Skip binary files
        try:
            with open(file_path, encoding="utf-8", errors="strict") as f:
                content = f.read()
        except UnicodeDecodeError:
            return {
                "error": f"Binary file, cannot read: {path}",
                "content": None,
            }

        lines = content.split("\n")
        total_lines = len(lines)

        # Apply line range
        if start_line is not None or end_line is not None:
            start = max(1, start_line or 1) - 1  # Convert to 0-indexed
            end = min(total_lines, end_line or total_lines)
            selected_lines = lines[start:end]
            # Add line numbers
            numbered = [
                f"{i + start + 1:4d}: {line}" for i, line in enumerate(selected_lines)
            ]
            content_section = "\n".join(numbered)
        else:
            # Add line numbers for full file if it's reasonable size
            if total_lines <= 500:
                numbered = [f"{i + 1:4d}: {line}" for i, line in enumerate(lines)]
                content_section = "\n".join(numbered)
            else:
                content_section = content

        return {
            "path": path,
            "total_lines": total_lines,
            "content": content_section,
        }

    def _search_code(
        self,
        pattern: str,
        file_pattern: str | None = None,
        max_results: int = 20,
    ) -> dict[str, Any]:
        """Search for code patterns in the repository.

        Args:
            pattern: Regex pattern to search for
            file_pattern: Glob pattern to filter files
            max_results: Maximum number of results

        Returns:
            Dict with matches list
        """
        matches = []

        try:
            # Use git grep for fast searching
            cmd = ["git", "-C", str(self.repo_path), "grep", "-n", "-E", pattern]

            if file_pattern:
                cmd.extend(["--", file_pattern])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[:max_results]:
                    if ":" in line:
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            matches.append(
                                {
                                    "file": parts[0],
                                    "line": int(parts[1]),
                                    "content": parts[2][:200],  # Truncate long lines
                                }
                            )

        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            # Fallback to Python-based search
            matches = self._search_code_python(pattern, file_pattern, max_results)

        return {
            "pattern": pattern,
            "total_matches": len(matches),
            "matches": matches,
        }

    def _search_code_python(
        self,
        pattern: str,
        file_pattern: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fallback Python-based code search.

        Args:
            pattern: Regex pattern
            file_pattern: Glob pattern
            max_results: Maximum results

        Returns:
            List of match dicts
        """
        matches = []
        compiled = re.compile(pattern)

        # Search only in changed files and common source directories
        search_paths = [self.repo_path / "src", self.repo_path / "lib"]
        if not search_paths[0].exists() and not search_paths[1].exists():
            search_paths = [self.repo_path]

        for search_path in search_paths:
            if not search_path.exists():
                continue

            for file_path in search_path.rglob(file_pattern or "*.py"):
                if not file_path.is_file():
                    continue
                try:
                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if compiled.search(line):
                                rel_path = str(file_path.relative_to(self.repo_path))
                                matches.append(
                                    {
                                        "file": rel_path,
                                        "line": line_num,
                                        "content": line.rstrip()[:200],
                                    }
                                )
                                if len(matches) >= max_results:
                                    return matches
                except Exception:
                    continue

        return matches

    def _validate_reference(
        self,
        reference_type: str,
        name: str,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Validate that a code reference exists in the codebase.

        Args:
            reference_type: Type of reference (file, function, class, variable)
            name: Name to validate
            file_path: Optional file path to narrow search scope

        Returns:
            Dict with 'found', 'locations', and 'suggestions'
        """
        if reference_type == "file":
            return self._validate_file_reference(name)

        # For function, class, variable references
        locations = []
        suggestions = []

        # Check AST elements first
        if name in self._element_names:
            for fp in self._element_names[name]:
                # Filter by file_path if provided
                if file_path and file_path not in fp:
                    continue
                # Find the element to get line number
                elements = self._file_elements.get(fp, [])
                for elem in elements:
                    elem_name = getattr(elem, "name", None) or (
                        elem.get("name") if isinstance(elem, dict) else None
                    )
                    if elem_name == name:
                        line = getattr(elem, "start_line", None) or (
                            elem.get("start_line") if isinstance(elem, dict) else None
                        )
                        locations.append(
                            {
                                "file": fp,
                                "line": line or 0,
                                "type": getattr(elem, "element_type", "unknown")
                                or (
                                    elem.get("element_type", "unknown")
                                    if isinstance(elem, dict)
                                    else "unknown"
                                ),
                            }
                        )

        # If not found in AST, try git grep
        if not locations:
            try:
                result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.repo_path),
                        "grep",
                        "-n",
                        f"\\b{name}\\b",
                        "--",
                        "*.py",
                        "*.cpp",
                        "*.h",
                        "*.js",
                        "*.ts",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n")[:10]:
                        if ":" in line:
                            parts = line.split(":", 2)
                            if len(parts) >= 3:
                                locations.append(
                                    {
                                        "file": parts[0],
                                        "line": int(parts[1]),
                                        "type": "grep_match",
                                    }
                                )
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                pass

        # Generate suggestions if not found
        if not locations:
            suggestions = self._find_similar_names(name, reference_type)

        return {
            "reference_type": reference_type,
            "name": name,
            "found": len(locations) > 0,
            "locations": locations,
            "suggestions": suggestions,
        }

    def _validate_file_reference(self, path: str) -> dict[str, Any]:
        """Validate that a file exists in the repository.

        Args:
            path: File path relative to repo root

        Returns:
            Validation result dict
        """
        file_path = self.repo_path / path
        exists = file_path.exists() and file_path.is_file()

        suggestions = []
        if not exists:
            # Try to find similar files
            parent = file_path.parent
            if parent.exists():
                stem = file_path.stem.lower()
                for candidate in parent.iterdir():
                    if candidate.is_file() and stem in candidate.name.lower():
                        suggestions.append(str(candidate.relative_to(self.repo_path)))
                        if len(suggestions) >= 5:
                            break

        return {
            "reference_type": "file",
            "name": path,
            "found": exists,
            "locations": [{"file": path, "line": 0, "type": "file"}] if exists else [],
            "suggestions": suggestions,
        }

    def _find_similar_names(self, name: str, reference_type: str) -> list[str]:
        """Find similar names in the codebase for suggestions.

        Args:
            name: The name that wasn't found
            reference_type: Type of reference

        Returns:
            List of similar names
        """
        suggestions = []
        name_lower = name.lower()

        # Check AST element names for similar matches
        for existing_name in self._element_names:
            if (
                name_lower in existing_name.lower()
                or existing_name.lower() in name_lower
            ):
                suggestions.append(existing_name)
                if len(suggestions) >= 5:
                    break

        # Also check for prefix matches
        if not suggestions:
            for existing_name in self._element_names:
                if existing_name.lower().startswith(name_lower[:3]):
                    suggestions.append(existing_name)
                    if len(suggestions) >= 5:
                        break

        return suggestions

    def _find_element_name(self, search_term: str) -> list[str]:
        """Find the exact code element name in the AST matching a search term.

        This is a direct tool call — the LLM uses it to look up the actual
        function/class/method name before writing source_elements in a fact.
        Uses substring matching: if the search term contains a known name
        or vice versa, it's returned as a match.

        Args:
            search_term: Descriptive or approximate name to search for

        Returns:
            List of actual element names from the AST that match.
            Empty list if nothing matched.
        """
        matches: list[str] = []
        search_lower = search_term.lower()

        for existing_name in self._element_names:
            if (
                search_lower in existing_name.lower()
                or existing_name.lower() in search_lower
            ):
                matches.append(existing_name)
                if len(matches) >= 5:
                    break

        return matches

    def _get_ast_elements(
        self,
        file_path: str | None = None,
        element_type: str | None = None,
    ) -> dict[str, Any]:
        """Get AST elements for files.

        Args:
            file_path: Specific file to get elements for, or None for all
            element_type: Filter by element type

        Returns:
            Dict with elements list
        """
        elements = []

        if file_path:
            # Get elements for specific file
            file_elements = self._file_elements.get(file_path, [])
            for elem in file_elements:
                elements.append(self._element_to_dict(elem))
        else:
            # Get all elements
            for _fp, file_elements in self._file_elements.items():
                for elem in file_elements:
                    elements.append(self._element_to_dict(elem))

        # Filter by element type
        if element_type:
            elements = [
                e
                for e in elements
                if e.get("element_type", "").lower() == element_type.lower()
            ]

        return {
            "total": len(elements),
            "elements": elements,
        }

    def _element_to_dict(self, elem: Any) -> dict[str, Any]:
        """Convert an AST element to a dict for tool results.

        Args:
            elem: CodeElement object or dict

        Returns:
            Dict representation
        """
        if isinstance(elem, dict):
            return elem

        return {
            "name": getattr(elem, "name", ""),
            "element_type": getattr(elem, "element_type", ""),
            "signature": getattr(elem, "signature", None),
            "docstring": getattr(elem, "docstring", None),
            "start_line": getattr(elem, "start_line", 0),
            "end_line": getattr(elem, "end_line", 0),
            "file_path": getattr(elem, "file_path", ""),
            "parent": getattr(elem, "parent", None),
            "children": getattr(elem, "children", []),
            "source_code": getattr(elem, "source_code", None),
        }

    def _get_element_source(
        self,
        element_name: str,
        file_path: str | None = None,
        max_lines: int = 50,
    ) -> dict[str, Any]:
        """Get the actual source code for a named code element.

        This is the primary anti-hallucination tool: it retrieves real source
        code so the LLM can reference actual implementations instead of
        fabricating code details.

        Args:
            element_name: Name of the code element (function, class, method)
            file_path: Optional file path to narrow search scope
            max_lines: Maximum number of source lines to return

        Returns:
            Dict with element source code, file path, line numbers, etc.
        """
        # Fast path: check pre-loaded source diffs cache first (no LLM request needed)
        if self._source_diffs_cache:
            # Try file_path::name first, then just name
            cache_key = f"{file_path}::{element_name}" if file_path else None
            cache_key_name_only = element_name

            cached = None
            if cache_key and cache_key in self._source_diffs_cache:
                cached = self._source_diffs_cache[cache_key]
            elif cache_key_name_only in self._source_diffs_cache:
                cached = self._source_diffs_cache[cache_key_name_only]

            if cached:
                return {
                    "element_name": cached.get("element_name", element_name),
                    "found": True,
                    "file_path": cached.get("file_path", file_path or ""),
                    "source_code": cached.get("after") or cached.get("before"),
                    "before_code": cached.get("before"),
                    "after_code": cached.get("after"),
                    "diff": cached.get("diff"),
                    "from_cache": True,
                }

        # Search through AST elements for matching name
        candidates = []

        for fp, elements in self._file_elements.items():
            # Filter by file_path if specified
            if file_path and file_path not in fp:
                continue

            for elem in elements:
                elem_name = getattr(elem, "name", None) or (
                    elem.get("name") if isinstance(elem, dict) else None
                )
                if elem_name == element_name:
                    candidates.append((fp, elem))

        if not candidates:
            # Try partial match
            for fp, elements in self._file_elements.items():
                if file_path and file_path not in fp:
                    continue
                for elem in elements:
                    elem_name = getattr(elem, "name", None) or (
                        elem.get("name") if isinstance(elem, dict) else None
                    )
                    if elem_name and element_name.lower() in elem_name.lower():
                        candidates.append((fp, elem))

        if not candidates:
            return {
                "error": f"Element '{element_name}' not found in AST data",
                "element_name": element_name,
                "found": False,
                "suggestions": list(self._element_names.keys())[:10],
            }

        # Use first match (or exact match if available)
        best_fp, best_elem = candidates[0]

        # Extract source code from element
        source_code = getattr(best_elem, "source_code", None) or (
            best_elem.get("source_code") if isinstance(best_elem, dict) else None
        )
        start_line = getattr(best_elem, "start_line", 0) or (
            best_elem.get("start_line") if isinstance(best_elem, dict) else 0
        )
        end_line = getattr(best_elem, "end_line", 0) or (
            best_elem.get("end_line") if isinstance(best_elem, dict) else 0
        )
        signature = getattr(best_elem, "signature", None) or (
            best_elem.get("signature") if isinstance(best_elem, dict) else None
        )
        docstring = getattr(best_elem, "docstring", None) or (
            best_elem.get("docstring") if isinstance(best_elem, dict) else None
        )
        elem_type = getattr(best_elem, "element_type", "") or (
            best_elem.get("element_type") if isinstance(best_elem, dict) else ""
        )
        parent = getattr(best_elem, "parent", None) or (
            best_elem.get("parent") if isinstance(best_elem, dict) else None
        )

        # If no source_code in AST data, try reading from file
        if not source_code:
            file_full_path = self.repo_path / best_fp
            if file_full_path.exists() and file_full_path.is_file():
                try:
                    content = file_full_path.read_text(errors="ignore")
                    lines = content.splitlines()
                    if start_line and end_line:
                        start_idx = max(0, start_line - 1)
                        end_idx = min(len(lines), end_line)
                        source_code = "\n".join(lines[start_idx:end_idx])
                    else:
                        source_code = content[: max_lines * 80]  # Rough estimate
                except Exception:
                    source_code = None

        # Truncate if too long
        if source_code:
            lines = source_code.splitlines()
            if len(lines) > max_lines:
                source_code = (
                    "\n".join(lines[:max_lines])
                    + f"\n... ({len(lines) - max_lines} more lines)"
                )

        result = {
            "element_name": element_name,
            "found": True,
            "file_path": best_fp,
            "element_type": str(elem_type),
            "start_line": start_line,
            "end_line": end_line,
            "signature": signature,
            "docstring": docstring[:200] if docstring else None,
            "parent": parent,
            "source_code": source_code,
        }

        # If multiple matches, list alternatives
        if len(candidates) > 1:
            result["alternative_files"] = [fp for fp, _ in candidates[1:6]]

        return result
