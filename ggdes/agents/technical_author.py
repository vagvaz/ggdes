"""Technical Author Agent for synthesizing code analysis into technical facts."""

import asyncio
import difflib
import json
from pathlib import Path
from typing import Any

from loguru import logger
from rich.console import Console

from ggdes.agents.skill_utils import load_skill
from ggdes.config import GGDesConfig, get_kb_path
from ggdes.llm import ConversationContext, LLMFactory
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    ChangeSummary,
    CodeElement,
    StoragePolicy,
    TechnicalFact,
)
from ggdes.tools import TOOL_DEFINITIONS, ToolCall, ToolExecutor, chat_with_tools

console = Console()

# Shared anti-hallucination instruction used across all analysis prompts
ANTI_HALLUCINATION_INSTRUCTION = (
    "IMPORTANT: You MUST base your descriptions on ACTUAL CODE. "
    "Use the get_element_source tool to retrieve the real source code for any function or class you reference. "
    "Do NOT fabricate or hallucinate code, function signatures, or implementation details. "
    "Only describe what you can verify from the actual source code."
)


class TechnicalAuthor:
    """Synthesize git analysis and AST data into structured technical facts.

    Uses tool-augmented LLM calls to verify code references against the actual
    codebase, preventing hallucinations in technical facts.
    """

    def __init__(
        self,
        repo_path: Path,
        config: GGDesConfig,
        analysis_id: str,
        user_context: dict[str, Any] | None = None,
        language_expert_skill: str | None = None,
        tool_executor: ToolExecutor | None = None,
        review_feedback: str | None = None,
    ):
        """Initialize technical author.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading/writing to KB
            user_context: Optional user-provided context (focus areas, audience, purpose)
            language_expert_skill: Optional name of language expert skill to load (e.g., 'python-expert', 'cpp-expert')
            tool_executor: Optional ToolExecutor for grounded LLM calls. If None,
                tools will not be available during fact generation.
            review_feedback: Optional feedback from review session to incorporate during regeneration.
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context = user_context or {}
        self.llm = LLMFactory.from_config(config)
        self.conversation: ConversationContext | None = None
        self.chunk_size_tokens = 30000  # Process AST data in chunks if needed
        self._coauthor_skill: str | None = None
        self._language_expert_skill: str | None = None
        self.tool_executor = tool_executor
        self.review_feedback = review_feedback

        # Load skills with graceful fallback
        self._load_skills(language_expert_skill)

    def _load_skills(self, language_expert_skill: str | None = None) -> None:
        """Load coauthor and optional language expert skills."""
        # Load coauthor skill for writing/documentation expertise (now called doc-coauthoring)
        try:
            self._coauthor_skill = load_skill("doc-coauthoring", self.repo_path)
            if self._coauthor_skill:
                console.print(
                    "  [dim]Loaded doc-coauthoring skill for enhanced documentation synthesis[/dim]"
                )
        except Exception:
            console.print(
                "  [dim]Doc-coauthoring skill not available, continuing with default synthesis[/dim]"
            )

        # Load language expert skill if specified
        if language_expert_skill:
            try:
                self._language_expert_skill = load_skill(
                    language_expert_skill, self.repo_path
                )
                if self._language_expert_skill:
                    console.print(
                        f"  [dim]Loaded {language_expert_skill} skill for enhanced code analysis[/dim]"
                    )
            except Exception:
                console.print(
                    f"  [dim]Language expert skill '{language_expert_skill}' not available, continuing without it[/dim]"
                )

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context."""
        from ggdes.agents.skill_utils import SystemPromptBuilder

        builder = SystemPromptBuilder()

        if self._coauthor_skill:
            builder.add_skill("DOCUMENTATION EXPERTISE", self._coauthor_skill)

        if self._language_expert_skill:
            builder.add_skill("LANGUAGE EXPERTISE", self._language_expert_skill)

        builder.set_base_prompt(get_prompt("technical_author", "system"))

        user_guidance = self._build_user_context_guidance()
        if user_guidance:
            builder.set_user_guidance(user_guidance)

        if self.review_feedback:
            builder.add_section("REVIEW FEEDBACK", self._build_review_feedback_block())

        system_prompt = builder.build()

        self.conversation = ConversationContext(
            system_prompt=system_prompt,
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _build_user_context_guidance(self) -> str:
        """Build guidance text from user context."""
        from ggdes.agents.skill_utils import build_user_context_guidance

        return build_user_context_guidance(self.user_context)

    def _build_review_feedback_block(self) -> str:
        """Build a formatted block with review feedback for injection into prompts."""
        return (
            "╔══════════════════════════════════════════════════════════════════╗\n"
            "║              ⚠️  REVIEW FEEDBACK (MUST INCORPORATE)  ⚠️          ║\n"
            "╚══════════════════════════════════════════════════════════════════╝\n\n"
            "The following feedback was provided during review. You MUST incorporate\n"
            f"this feedback into your analysis:\n\n{self.review_feedback}"
        )

    def _load_git_analysis(self) -> ChangeSummary | None:
        """Load git analysis results from KB."""

        analysis_path = (
            get_kb_path(self.config, self.analysis_id) / "git_analysis" / "summary.json"
        )

        if not analysis_path.exists():
            return None

        data = json.loads(analysis_path.read_text())
        return ChangeSummary(**data)

    def _load_semantic_diff(self) -> dict[str, Any] | None:
        """Load semantic diff results from KB.

        Returns:
            Dict with semantic diff data or None if not available
        """

        semantic_diff_path = (
            get_kb_path(self.config, self.analysis_id) / "semantic_diff" / "result.json"
        )

        if not semantic_diff_path.exists():
            return None

        try:
            data = json.loads(semantic_diff_path.read_text())
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _load_ast_data(self, which: str = "head") -> list[CodeElement]:
        """Load AST data from KB.

        Args:
            which: "base" or "head"

        Returns:
            List of code elements
        """

        ast_dir = get_kb_path(self.config, self.analysis_id) / f"ast_{which}"

        if not ast_dir.exists():
            return []

        elements = []
        for json_file in ast_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text())
                for elem_data in data.get("elements", []):
                    elements.append(CodeElement(**elem_data))
            except Exception:
                continue

        return elements

    def _find_changed_elements(
        self, change_summary: ChangeSummary, ast_elements: list[CodeElement]
    ) -> list[CodeElement]:
        """Find code elements that appear in changed files."""
        changed_files = {f.path for f in change_summary.files_changed}

        changed_elements = []
        for elem in ast_elements:
            # Check if element's file is in changed files
            if any(
                elem.file_path.endswith(f) or f.endswith(elem.file_path)
                for f in changed_files
            ):
                changed_elements.append(elem)

        return changed_elements

    def _build_source_code_context(
        self,
        elements: list[CodeElement],
        max_elements: int = 15,
        max_lines_per_element: int = 50,
    ) -> str:
        """Build a context string with actual source code for changed elements.

        This is the key anti-hallucination measure: providing the LLM with
        real source code so it can reference actual code instead of fabricating.

        Args:
            elements: List of code elements with source_code populated
            max_elements: Maximum number of elements to include
            max_lines_per_element: Maximum lines of source code per element

        Returns:
            Formatted string with source code context
        """
        if not elements:
            return ""

        context_parts: list[str] = []
        included = 0

        for elem in elements:
            if included >= max_elements:
                break
            if elem.source_code:
                lines = elem.source_code.splitlines()
                if len(lines) > max_lines_per_element:
                    code = (
                        "\n".join(lines[:max_lines_per_element])
                        + f"\n... ({len(lines) - max_lines_per_element} more lines)"
                    )
                else:
                    code = elem.source_code
                context_parts.append(f"### {elem.name}\n```\n{code}\n```")
                included += 1

        return "\n\n".join(context_parts)

    def _find_usages_in_worktree(
        self,
        element_name: str,
        worktree_path: Path,
        max_examples: int = 3,
        context_lines: int = 3,
    ) -> list[str]:
        """Find usage examples of a function/method in a worktree's source files.

        Searches for call sites of the given element (not its definition) and
        returns the surrounding context lines as usage examples.

        Args:
            element_name: Name of the function/method to find usages for
            worktree_path: Path to the worktree to search in
            max_examples: Maximum number of usage examples to return
            context_lines: Number of lines before/after the call to include

        Returns:
            List of code snippets showing usage examples
        """

        # Build search patterns for different languages
        # C++: ClassName::MethodName( or just MethodName(
        # Python: func_name(
        # Java/JS: methodName(
        # For C++-style, also try without class prefix
        search_names = [element_name]
        if "::" in element_name:
            # It's a C++ method, also try just the method name
            method_part = element_name.split("::")[-1]
            search_names.append(method_part)

        # Find source files to search
        if not worktree_path.exists():
            return []

        # Build regex patterns for each name variant
        # Match function calls but NOT definitions
        patterns = []
        for name in search_names:
            # Match: word( or word.word( but not: def word( or class word( or word word(
            # This is tricky with regex, so we'll do line-by-line matching
            patterns.append(name)

        examples: list[tuple[int, str]] = []  # (priority, snippet)
        seen_signatures: set[int] = set()

        # Walk all source files
        for src_dir in ["src", "lib", "include", "core"]:
            src_path = worktree_path / src_dir
            if not src_path.exists():
                continue

            try:
                for file_path in src_path.rglob("*"):
                    if not file_path.is_file():
                        continue
                    ext = file_path.suffix.lower()
                    if ext not in {
                        ".py",
                        ".cpp",
                        ".cc",
                        ".cxx",
                        ".hpp",
                        ".h",
                        ".java",
                        ".js",
                        ".ts",
                        ".go",
                        ".rs",
                    }:
                        continue

                    try:
                        content = file_path.read_text(errors="ignore")
                        lines = content.splitlines()
                        for i, line in enumerate(lines):
                            for name in search_names:
                                # Look for function call pattern: name(
                                # But exclude definition lines
                                if f"{name}(" not in line:
                                    continue
                                # Skip if this looks like a definition
                                stripped = line.strip()
                                if any(
                                    stripped.startswith(kw)
                                    for kw in [
                                        "def ",
                                        "class ",
                                        "fn ",
                                        "func ",
                                        "struct ",
                                        "enum ",
                                    ]
                                ):
                                    continue
                                # Skip if it's the function definition itself
                                if f"{name}(" in line and ("{" in line or "=" in line):
                                    # Check if it's the definition (has { or = after or is alone on line)
                                    # It's a definition, skip it
                                    continue

                                # Extract context
                                start = max(0, i - context_lines)
                                end = min(len(lines), i + context_lines + 1)
                                context = lines[start:end]
                                snippet = "\n".join(context)
                                snippet_hash = hash(snippet)

                                if snippet_hash not in seen_signatures:
                                    seen_signatures.add(snippet_hash)
                                    # Priority: prefer shorter snippets (more likely to be a call site)
                                    priority = len(snippet)
                                    examples.append((priority, snippet))
                    except Exception:
                        continue
            except Exception:
                continue

        # Sort by priority (shorter first) and return top examples
        examples.sort(key=lambda x: x[0])
        return [ex[1] for _, ex in examples[:max_examples]]

    def _get_language_hint(self, file_path: str) -> str:
        """Get language hint for code block from file extension."""
        ext_map = {
            ".py": "python",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".hpp": "cpp",
            ".h": "c",
            ".js": "javascript",
            ".ts": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return ""

    def _build_code_snippets_dict(
        self, elements: list[CodeElement], max_lines: int = 50
    ) -> dict[str, str]:
        """Build a mapping of element names to their source code.

        Used to populate TechnicalFact.code_snippets for downstream use.

        Args:
            elements: List of code elements with source_code populated
            max_lines: Maximum lines of source code per element

        Returns:
            Dict mapping element names to their source code
        """
        snippets = {}
        for elem in elements:
            if elem.source_code:
                lines = elem.source_code.splitlines()
                if len(lines) > max_lines:
                    snippets[elem.name] = (
                        "\n".join(lines[:max_lines])
                        + f"\n... ({len(lines) - max_lines} more lines)"
                    )
                else:
                    snippets[elem.name] = elem.source_code
        return snippets

    def _compute_source_diffs(
        self,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
        max_diffs: int = 20,
        max_lines_per_diff: int = 60,
    ) -> dict[str, dict[str, str]]:
        """Compute source code diffs between base and head versions of elements.

        For each element that exists in both base and head with different source code,
        produce a unified diff showing what changed.

        Args:
            base_elements: AST elements from the base commit
            head_elements: AST elements from the head commit
            max_diffs: Maximum number of diffs to compute
            max_lines_per_diff: Maximum lines per diff output

        Returns:
            Dict mapping element key (file_path::name) to:
            {
                "before": <base source code>,
                "after": <head source code>,
                "diff": <unified diff string>,
                "element_name": <name>,
                "file_path": <file path>,
            }
        """
        # Build lookups by key (file_path::name)
        base_by_key = {
            f"{e.file_path}::{e.name}": e for e in base_elements if e.source_code
        }
        head_by_key = {
            f"{e.file_path}::{e.name}": e for e in head_elements if e.source_code
        }

        # Find elements that exist in both with different source code
        common_keys = set(base_by_key.keys()) & set(head_by_key.keys())
        changed_keys = []
        for key in common_keys:
            base_src = base_by_key[key].source_code or ""
            head_src = head_by_key[key].source_code or ""
            if base_src != head_src:
                changed_keys.append(key)

        # Also include new elements (only in head) with their full source
        new_keys = set(head_by_key.keys()) - set(base_by_key.keys())

        # Also include deleted elements (only in base) with their full source
        deleted_keys = set(base_by_key.keys()) - set(head_by_key.keys())

        diffs: dict[str, dict[str, str]] = {}

        # Prioritize changed elements (most valuable for understanding diffs)
        for key in changed_keys[:max_diffs]:
            base_elem = base_by_key[key]
            head_elem = head_by_key[key]
            base_lines = (base_elem.source_code or "").splitlines(keepends=True)
            head_lines = (head_elem.source_code or "").splitlines(keepends=True)

            # Produce unified diff
            diff_lines = list(
                difflib.unified_diff(
                    base_lines,
                    head_lines,
                    fromfile=f"base/{base_elem.file_path}",
                    tofile=f"head/{head_elem.file_path}",
                    n=3,  # context lines
                )
            )

            # Truncate long diffs
            if len(diff_lines) > max_lines_per_diff:
                diff_text = (
                    "".join(diff_lines[: max_lines_per_diff // 2])
                    + "\n... (truncated) ...\n"
                    + "".join(diff_lines[-max_lines_per_diff // 2 :])
                )
            else:
                diff_text = "".join(diff_lines)

            diffs[key] = {
                "before": base_elem.source_code or "",
                "after": head_elem.source_code or "",
                "diff": diff_text,
                "element_name": head_elem.name,
                "file_path": head_elem.file_path,
            }

        # Include new elements (no before, just after)
        remaining = max_diffs - len(diffs)
        for key in list(new_keys)[:remaining]:
            head_elem = head_by_key[key]
            diffs[key] = {
                "before": "",
                "after": head_elem.source_code or "",
                "diff": f"+++ NEW: {head_elem.name} in {head_elem.file_path}\n"
                + (head_elem.source_code or ""),
                "element_name": head_elem.name,
                "file_path": head_elem.file_path,
            }

        # Include deleted elements (no after, just before)
        remaining = max_diffs - len(diffs)
        for key in list(deleted_keys)[:remaining]:
            base_elem = base_by_key[key]
            diffs[key] = {
                "before": base_elem.source_code or "",
                "after": "",
                "diff": f"--- DELETED: {base_elem.name} in {base_elem.file_path}\n"
                + (base_elem.source_code or ""),
                "element_name": base_elem.name,
                "file_path": base_elem.file_path,
            }

        return diffs

    def _build_diff_context(
        self,
        source_diffs: dict[str, dict[str, str]],
        max_diffs: int = 15,
        max_lines_per_element: int = 40,
    ) -> str:
        """Build a formatted context string from source code diffs.

        This provides the LLM with before/after source code comparisons so it
        can accurately describe what changed instead of fabricating details.

        Args:
            source_diffs: Output from _compute_source_diffs()
            max_diffs: Maximum number of diffs to include
            max_lines_per_element: Maximum lines per before/after block

        Returns:
            Formatted string with source code diffs
        """
        if not source_diffs:
            return ""

        parts = []

        for included, diff_data in enumerate(source_diffs.values()):
            if included >= max_diffs:
                parts.append(
                    f"\n... and {len(source_diffs) - included} more diffs (truncated)"
                )
                break

            element_name = diff_data["element_name"]
            file_path = diff_data["file_path"]
            before = diff_data["before"]
            after = diff_data["after"]
            diff_text = diff_data["diff"]

            section = f"### {element_name} in {file_path}"

            if before and after:
                # Modified element: show before/after + diff
                before_lines = before.splitlines()
                after_lines = after.splitlines()

                before_truncated = "\n".join(before_lines[:max_lines_per_element])
                if len(before_lines) > max_lines_per_element:
                    before_truncated += f"\n... ({len(before_lines) - max_lines_per_element} more lines)"

                after_truncated = "\n".join(after_lines[:max_lines_per_element])
                if len(after_lines) > max_lines_per_element:
                    after_truncated += (
                        f"\n... ({len(after_lines) - max_lines_per_element} more lines)"
                    )

                lang = self._get_language_hint(file_path)
                section += f"\n**BEFORE:**\n```{lang}\n{before_truncated}\n```\n"
                section += f"**AFTER:**\n```{lang}\n{after_truncated}\n```\n"
                section += f"**DIFF:**\n```diff\n{diff_text}\n```"
            elif after and not before:
                # New element
                after_lines = after.splitlines()
                after_truncated = "\n".join(after_lines[:max_lines_per_element])
                if len(after_lines) > max_lines_per_element:
                    after_truncated += (
                        f"\n... ({len(after_lines) - max_lines_per_element} more lines)"
                    )

                lang = self._get_language_hint(file_path)
                section += f"\n**NEW ELEMENT:**\n```{lang}\n{after_truncated}\n```"
            elif before and not after:
                # Deleted element
                before_lines = before.splitlines()
                before_truncated = "\n".join(before_lines[:max_lines_per_element])
                if len(before_lines) > max_lines_per_element:
                    before_truncated += f"\n... ({len(before_lines) - max_lines_per_element} more lines)"

                lang = self._get_language_hint(file_path)
                section += f"\n**DELETED ELEMENT:**\n```{lang}\n{before_truncated}\n```"

            parts.append(section)

        return "\n\n".join(parts) if parts else ""

    async def synthesize(
        self,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
        parallel: bool = True,
    ) -> list[TechnicalFact]:
        """Synthesize technical facts from analysis data.

        Args:
            storage_policy: How to persist conversation
            parallel: Whether to run analysis turns in parallel (default: True)

        Returns:
            List of technical facts
        """
        console.print("[bold]Synthesizing technical facts...[/bold]")
        logger.info(
            "Technical Author: starting synthesis | analysis=%s", self.analysis_id
        )

        # Initialize conversation
        self._init_conversation(storage_policy)

        # Load data from previous stages
        change_summary = self._load_git_analysis()
        if not change_summary:
            raise ValueError(f"No git analysis found for {self.analysis_id}")

        console.print(
            f"  [dim]Git analysis found {len(change_summary.files_changed)} changed files[/dim]"
        )

        base_elements = self._load_ast_data("base")
        head_elements = self._load_ast_data("head")

        console.print(
            f"  [dim]Loaded {len(base_elements)} AST elements from base[/dim]"
        )
        console.print(
            f"  [dim]Loaded {len(head_elements)} AST elements from head[/dim]"
        )

        # Find elements in changed files
        changed_base = self._find_changed_elements(change_summary, base_elements)
        changed_head = self._find_changed_elements(change_summary, head_elements)

        console.print(
            f"  [dim]Found {len(changed_base)} changed elements in base[/dim]"
        )
        console.print(
            f"  [dim]Found {len(changed_head)} changed elements in head[/dim]"
        )

        # Drop non-changed elements and log
        non_changed_base = len(base_elements) - len(changed_base)
        non_changed_head = len(head_elements) - len(changed_head)

        if non_changed_base > 0:
            console.print(
                f"  [dim]Dropping {non_changed_base} base AST elements not in changed files[/dim]"
            )
        if non_changed_head > 0:
            console.print(
                f"  [dim]Dropping {non_changed_head} head AST elements not in changed files[/dim]"
            )

        # Compute source code diffs between base and head
        source_diffs = self._compute_source_diffs(changed_base, changed_head)
        diff_context = self._build_diff_context(source_diffs)
        console.print(
            f"  [dim]Computed {len(source_diffs)} source code diffs between base and head[/dim]"
        )

        # Pre-load source diffs into tool executor so get_element_source is instant
        if self.tool_executor and source_diffs:
            self.tool_executor.set_source_diffs_cache(source_diffs)

        # Load semantic diff results if available
        semantic_diff_data = self._load_semantic_diff()
        if semantic_diff_data:
            console.print(
                f"  [dim]Loaded semantic diff: {semantic_diff_data.get('summary', {}).get('total_changes', 0)} semantic changes[/dim]"
            )
            if semantic_diff_data.get("summary", {}).get("has_breaking_changes", False):
                console.print(
                    f"  [yellow]⚠ Semantic diff detected {semantic_diff_data.get('summary', {}).get('breaking_changes', 0)} breaking change(s)[/yellow]"
                )
        else:
            console.print("  [dim]No semantic diff results available[/dim]")

        if parallel:
            # Run all three analysis turns in parallel
            all_facts = await self._analyze_parallel(
                change_summary,
                changed_base,
                changed_head,
                source_diffs,
                diff_context,
                semantic_diff=semantic_diff_data,
            )
        else:
            # Sequential execution
            all_facts = []

            # Turn 1: API Changes Analysis (only changed elements)
            api_facts = await self._analyze_api_changes(
                change_summary,
                changed_base,
                changed_head,
                source_diffs=source_diffs,
                diff_context=diff_context,
                semantic_diff=semantic_diff_data,
            )
            all_facts.extend(api_facts)

            # Turn 2: Behavioral Changes Analysis (only changed elements)
            behavior_facts = await self._analyze_behavioral_changes(
                change_summary,
                changed_base,
                changed_head,
                source_diffs=source_diffs,
                diff_context=diff_context,
            )
            all_facts.extend(behavior_facts)

            # Turn 3: Architecture/Dependency Analysis (only changed elements)
            arch_facts = await self._analyze_architecture_changes(
                change_summary, changed_base, changed_head
            )
            all_facts.extend(arch_facts)

        # Save conversation to KB

        kb_path = (
            get_kb_path(self.config, self.analysis_id)
            / "conversations"
            / "technical_author"
        )
        if self.conversation:
            self.conversation.save(kb_path)

        # Validate facts against codebase using tools
        if self.tool_executor:
            console.print("  [dim]Validating technical facts against codebase...[/dim]")
            all_facts = self._validate_facts_with_tools(all_facts)
            console.print(
                f"  [green]✓ Validated {len(all_facts)} facts against codebase[/green]"
            )

        # Enrich facts with source code snippets from AST elements
        all_facts = self._enrich_facts_with_source_code(
            all_facts, changed_head, source_diffs
        )

        # Save facts to KB
        self._save_facts(all_facts)

        return all_facts

    async def _analyze_api_changes(
        self,
        change_summary: ChangeSummary,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
        conversation: ConversationContext | None = None,
        source_diffs: dict[str, dict[str, str]] | None = None,
        diff_context: str | None = None,
        semantic_diff: dict[str, Any] | None = None,
    ) -> list[TechnicalFact]:
        """Analyze API changes (signatures, new/deleted functions)."""
        logger.info(
            "Technical Author: analyzing API changes | files={}",
            len(change_summary.files_changed),
        )
        conv = conversation or self.conversation
        facts = []

        # Build context about API changes
        base_apis = {
            f"{e.file_path}::{e.name}": e
            for e in base_elements
            if e.element_type.value in ["function", "method"]
        }
        head_apis = {
            f"{e.file_path}::{e.name}": e
            for e in head_elements
            if e.element_type.value in ["function", "method"]
        }

        # Find new APIs
        new_apis = set(head_apis.keys()) - set(base_apis.keys())
        # Find deleted APIs
        deleted_apis = set(base_apis.keys()) - set(head_apis.keys())
        # Find modified APIs (same name, different signature)
        modified_apis = []
        for key in set(base_apis.keys()) & set(head_apis.keys()):
            base_sig = base_apis[key].signature or ""
            head_sig = head_apis[key].signature or ""
            if base_sig != head_sig:
                modified_apis.append(
                    {
                        "key": key,
                        "name": head_apis[key].name,
                        "file": head_apis[key].file_path,
                        "old_sig": base_sig,
                        "new_sig": head_sig,
                    }
                )

        # If too many changes, chunk them
        if len(new_apis) + len(deleted_apis) + len(modified_apis) > 20:
            # Process in batches
            batch_facts = await self._analyze_api_batch(
                list(new_apis)[:10],
                list(deleted_apis)[:10],
                modified_apis[:10],
            )
            facts.extend(batch_facts)
        else:
            # All at once
            prompt = f"""Analyze the following API changes and describe each factually.

{ANTI_HALLUCINATION_INSTRUCTION}

Change Summary: {change_summary.description}
Intent: {change_summary.intent}

New APIs ({len(new_apis)}):
"""
            for key in list(new_apis)[:10]:
                elem = head_apis[key]
                prompt += f"- {elem.name} in {elem.file_path}\n"
                if elem.signature:
                    prompt += f"  Signature: {elem.signature}\n"
                if elem.docstring:
                    prompt += f"  Doc: {elem.docstring[:200]}\n"

            prompt += f"""
Deleted APIs ({len(deleted_apis)}):
"""
            for key in list(deleted_apis)[:10]:
                elem = base_apis[key]
                prompt += f"- {elem.name} in {elem.file_path}\n"

            prompt += f"""
Modified APIs ({len(modified_apis)}):
"""
            for api in modified_apis[:10]:
                prompt += f"- {api['name']} in {api['file']}\n"
                prompt += f"  Old: {api['old_sig']}\n"
                prompt += f"  New: {api['new_sig']}\n"

            # Include source code diffs if available
            if diff_context:
                prompt += f"""

SOURCE CODE DIFFS (before/after comparisons of changed elements):
{diff_context}

Use the above source code diffs to accurately describe what changed. Reference the actual code in your descriptions.
"""

            # Include semantic diff results if available
            if semantic_diff:
                summary = semantic_diff.get("summary", {})
                changes = semantic_diff.get("semantic_changes", [])
                prompt += f"""

SEMANTIC DIFF ANALYSIS (automated detection of semantic changes):
Total semantic changes detected: {summary.get("total_changes", 0)}
Breaking changes: {summary.get("breaking_changes", 0)}
Total impact score: {summary.get("total_impact_score", 0):.1f}/10

Key semantic changes:
"""
                for change in changes[:15]:  # Limit to top 15 changes
                    prompt += f"- [{change.get('change_type', 'unknown')}] {change.get('description', '')} in {change.get('file_path', '')}"
                    if change.get("confidence"):
                        prompt += f" (confidence: {change['confidence']:.2f})"
                    if change.get("impact_score"):
                        prompt += f" (impact: {change['impact_score']:.2f})"
                    prompt += "\n"

                prompt += """

Use the semantic diff analysis to identify breaking changes, API modifications, and behavioral changes. Prioritize high-impact changes in your documentation.
"""

            prompt += """
Before writing your analysis, use the get_element_source tool to retrieve the actual source code for key functions and classes. This ensures your descriptions are grounded in real code.
"""
            if self.review_feedback:
                prompt += f"""

REVIEW FEEDBACK TO INCORPORATE:
{self.review_feedback}

You MUST address this feedback in your analysis. Adjust your descriptions accordingly.
"""

            prompt += """

For each API change, provide:
1. Fact ID (e.g., api_001, api_002)
2. Category: api
3. Description: What changed and why (based on the actual source code you retrieved)
4. Source elements: Affected functions/classes
5. Source file: Primary file location
6. Confidence: 0.0-1.0

Format as JSON array of TechnicalFact objects."""

            if not conv:
                raise RuntimeError("Conversation not initialized")

            conv.add_user_message(prompt)
            context = conv.get_context_for_llm()

            # Generate structured facts
            response = await self._generate_facts_response(context)

            try:
                facts_data = (
                    json.loads(response) if isinstance(response, str) else response
                )
                if isinstance(facts_data, list):
                    for i, fact_data in enumerate(facts_data):
                        fact_data["fact_id"] = f"api_{i + 1:03d}"
                        fact_data["category"] = "api"
                        facts.append(TechnicalFact(**fact_data))
            except Exception:
                # Fallback: create simple facts
                for i, key in enumerate(list(new_apis)[:5]):
                    elem = head_apis[key]
                    facts.append(
                        TechnicalFact(
                            fact_id=f"api_{i + 1:03d}",
                            category="api",
                            source_elements=[elem.name],
                            description=f"New function {elem.name} added in {elem.file_path}",
                            source_file=elem.file_path,
                            confidence=0.9,
                        )
                    )

        return facts

    async def _analyze_api_batch(
        self,
        new_apis: list[str],
        deleted_apis: list[str],
        modified_apis: list[dict[str, str]],
    ) -> list[TechnicalFact]:
        """Process API changes in a batch."""
        # Simplified batch processing
        facts = []

        for i, key in enumerate(new_apis):
            facts.append(
                TechnicalFact(
                    fact_id=f"api_new_{i + 1:03d}",
                    category="api",
                    source_elements=[key.split("::")[-1]],
                    description=f"New API added: {key}",
                    source_file=key.split("::")[0],
                    confidence=0.9,
                )
            )

        for i, key in enumerate(deleted_apis):
            facts.append(
                TechnicalFact(
                    fact_id=f"api_del_{i + 1:03d}",
                    category="api",
                    source_elements=[key.split("::")[-1]],
                    description=f"API removed: {key}",
                    source_file=key.split("::")[0],
                    confidence=0.9,
                )
            )

        return facts

    async def _analyze_behavioral_changes(
        self,
        change_summary: ChangeSummary,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
        conversation: ConversationContext | None = None,
        source_diffs: dict[str, dict[str, str]] | None = None,
        diff_context: str | None = None,
        semantic_diff: dict[str, Any] | None = None,
    ) -> list[TechnicalFact]:
        """Analyze behavioral changes (what code does differently)."""
        logger.info(
            "Technical Author: analyzing behavioral changes | files={}",
            len(change_summary.files_changed),
        )
        conv = conversation or self.conversation
        facts = []

        # Find changed files
        changed_files = {f.path for f in change_summary.files_changed}

        # Use git analysis to guide behavioral analysis
        prompt = f"""Based on the git change analysis, identify behavioral changes:

Description: {change_summary.description}
Intent: {change_summary.impact}
Breaking Changes: {change_summary.breaking_changes}

IMPORTANT: You should ONLY generate facts about behavioral changes in files that were actually changed. Do not generate facts about files that were not in the git diff.

{ANTI_HALLUCINATION_INSTRUCTION}

Files Changed ({len(change_summary.files_changed)}):
"""
        for f in change_summary.files_changed[:10]:
            prompt += f"- {f.path}: {f.summary}\n"

        # Include source code diffs if available — this is the key anti-hallucination measure
        if diff_context:
            prompt += f"""

SOURCE CODE DIFFS (before/after comparisons of changed elements):
{diff_context}

Use the above source code diffs to accurately describe what changed. When describing behavioral changes, reference the actual before/after code. Do NOT fabricate code — use the diffs provided above.
"""

        # Include semantic diff results if available
        if semantic_diff:
            summary = semantic_diff.get("summary", {})
            changes = semantic_diff.get("semantic_changes", [])
            # Filter for behavioral and breaking changes
            behavioral_changes = [
                c
                for c in changes
                if c.get("change_type")
                in [
                    "behavior_change",
                    "logic_change",
                    "algorithm_change",
                    "control_flow_change",
                    "error_handling_change",
                ]
            ]
            prompt += f"""

SEMANTIC DIFF ANALYSIS (automated detection of semantic changes):
Total semantic changes: {summary.get("total_changes", 0)}
Behavioral changes detected: {len(behavioral_changes)}
Breaking changes: {summary.get("breaking_changes", 0)}
Total impact score: {summary.get("total_impact_score", 0):.1f}/10

Detected behavioral changes:
"""
            for change in behavioral_changes[:10]:
                prompt += f"- [{change.get('change_type', 'unknown')}] {change.get('description', '')} in {change.get('file_path', '')}"
                if change.get("impact_score"):
                    prompt += f" (impact: {change['impact_score']:.2f})"
                prompt += "\n"

            prompt += """

Use the semantic diff analysis to identify and describe behavioral changes. Focus on high-impact changes that affect system behavior.
"""

        prompt += f"""
IMPORTANT: Only analyze behavioral changes in the {len(changed_files)} files that were changed. Do not reference files that were not in the git diff.

Before writing your analysis, use the get_element_source tool to retrieve the actual source code for key functions and classes in the changed files. This ensures your descriptions are grounded in real code.
"""
        if self.review_feedback:
            prompt += f"""

REVIEW FEEDBACK TO INCORPORATE:
{self.review_feedback}

You MUST address this feedback in your analysis. Adjust your descriptions accordingly.
"""

        prompt += """

For each behavioral change, provide:
1. Fact ID (e.g., behavior_001)
2. Category: behavior
3. Description: How behavior changed (based on actual source code)
4. What was the old behavior
5. What is the new behavior
6. Impact on users/system

Format as JSON array."""

        if not conv:
            raise RuntimeError("Conversation not initialized")

        conv.add_user_message(prompt)
        context = conv.get_context_for_llm()

        response = await self._generate_facts_response(context)

        try:
            facts_data = json.loads(response) if isinstance(response, str) else response
            if isinstance(facts_data, list):
                for i, fact_data in enumerate(facts_data):
                    fact_data["fact_id"] = f"behavior_{i + 1:03d}"
                    fact_data["category"] = "behavior"
                    facts.append(TechnicalFact(**fact_data))
        except Exception:
            # Fallback
            if change_summary.breaking_changes:
                facts.append(
                    TechnicalFact(
                        fact_id="behavior_001",
                        category="behavior",
                        source_elements=[],
                        description=f"Breaking changes: {', '.join(change_summary.breaking_changes[:3])}",
                        source_file=change_summary.files_changed[0].path
                        if change_summary.files_changed
                        else "unknown",
                        confidence=0.8,
                    )
                )

        return facts

    async def _analyze_architecture_changes(
        self,
        change_summary: ChangeSummary,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
    ) -> list[TechnicalFact]:
        """Analyze architecture/dependency changes."""
        logger.info(
            "Technical Author: analyzing architecture changes | deps_changed={}",
            len(change_summary.dependencies_changed),
        )
        facts = []

        if change_summary.dependencies_changed:
            for i, dep in enumerate(change_summary.dependencies_changed):
                facts.append(
                    TechnicalFact(
                        fact_id=f"arch_{i + 1:03d}",
                        category="architecture",
                        source_elements=[],
                        description=f"Dependency changed: {dep}",
                        source_file="pyproject.toml",  # Assume
                        confidence=0.9,
                    )
                )

        # Analyze class hierarchy changes
        base_classes = {
            e.name for e in base_elements if e.element_type.value == "class"
        }
        head_classes = {
            e.name for e in head_elements if e.element_type.value == "class"
        }

        new_classes = head_classes - base_classes
        for i, cls in enumerate(new_classes):
            facts.append(
                TechnicalFact(
                    fact_id=f"arch_class_{i + 1:03d}",
                    category="architecture",
                    source_elements=[cls],
                    description=f"New class added: {cls}",
                    source_file="unknown",
                    confidence=0.85,
                )
            )

        return facts

    async def _analyze_parallel(
        self,
        change_summary: ChangeSummary,
        changed_base: list[CodeElement],
        changed_head: list[CodeElement],
        source_diffs: dict[str, dict[str, str]] | None = None,
        diff_context: str | None = None,
        semantic_diff: dict[str, Any] | None = None,
    ) -> list[TechnicalFact]:
        """Run all three analysis turns in parallel using separate conversation contexts."""
        from ggdes.llm import ConversationContext
        from ggdes.schemas import StoragePolicy

        # Create separate conversation contexts for LLM-based analyses
        api_conv = ConversationContext(
            system_prompt=self.conversation.system_prompt if self.conversation else "",
            storage_policy=self.conversation.storage_policy
            if self.conversation
            else StoragePolicy.SUMMARY,
        )
        behavior_conv = ConversationContext(
            system_prompt=self.conversation.system_prompt if self.conversation else "",
            storage_policy=self.conversation.storage_policy
            if self.conversation
            else StoragePolicy.SUMMARY,
        )

        api_facts, behavior_facts, arch_facts = await asyncio.gather(
            self._analyze_api_changes(
                change_summary,
                changed_base,
                changed_head,
                conversation=api_conv,
                source_diffs=source_diffs,
                diff_context=diff_context,
                semantic_diff=semantic_diff,
            ),
            self._analyze_behavioral_changes(
                change_summary,
                changed_base,
                changed_head,
                conversation=behavior_conv,
                source_diffs=source_diffs,
                diff_context=diff_context,
                semantic_diff=semantic_diff,
            ),
            self._analyze_architecture_changes(
                change_summary, changed_base, changed_head
            ),
        )

        all_facts = []
        all_facts.extend(api_facts or [])
        all_facts.extend(behavior_facts or [])
        all_facts.extend(arch_facts or [])

        # Save parallel conversation contexts for debugging
        if self.analysis_id:
            kb_base = get_kb_path(self.config, self.analysis_id) / "conversations"
            if api_conv and api_conv.messages:
                api_conv.save(kb_base / "technical_author_api")
            if behavior_conv and behavior_conv.messages:
                behavior_conv.save(kb_base / "technical_author_behavior")

        return all_facts

    async def _generate_facts_response(self, context: list[dict[str, Any]]) -> str:
        """Generate response from conversation context.

        Uses tool-augmented chat when a ToolExecutor is available, allowing
        the LLM to verify code references against the actual codebase.
        Falls back to plain chat when no tools are configured.
        """
        logger.info(
            "Technical Author: generating facts response | tools=%s",
            "enabled" if self.tool_executor else "disabled",
        )
        if self.tool_executor:
            return chat_with_tools(
                llm=self.llm,
                messages=context,
                tools=TOOL_DEFINITIONS,
                executor=self.tool_executor,
                temperature=0.3,
                max_tokens=4096,
            )
        return self.llm.chat(
            messages=context,
            temperature=0.3,
            max_tokens=4096,
        )

    def _validate_facts_with_tools(
        self, facts: list[TechnicalFact]
    ) -> list[TechnicalFact]:
        """Validate technical facts using tool executor.

        Checks that source_elements and source_file references in facts
        actually exist in the codebase. Removes or corrects invalid references.

        Args:
            facts: List of technical facts to validate

        Returns:
            Validated facts with invalid references removed or corrected
        """
        if not self.tool_executor:
            return facts

        validated = []
        for fact in facts:
            # Validate source_file
            if fact.source_file and fact.source_file != "unknown":
                result = self.tool_executor.execute(
                    ToolCall(
                        tool_name="validate_reference",
                        arguments={
                            "reference_type": "file",
                            "name": fact.source_file,
                        },
                    )
                )
                if result.success and not result.result.get("found", False):
                    # File doesn't exist — try suggestions
                    suggestions = result.result.get("suggestions", [])
                    if suggestions:
                        console.print(
                            f"  [yellow]⚠ Fact {fact.fact_id}: source_file '{fact.source_file}' "
                            f"not found, using '{suggestions[0]}'[/yellow]"
                        )
                        fact.source_file = suggestions[0]
                    else:
                        console.print(
                            f"  [yellow]⚠ Fact {fact.fact_id}: source_file '{fact.source_file}' "
                            f"not found and no suggestions available[/yellow]"
                        )

            # Validate source_elements
            validated_elements = []
            for elem in fact.source_elements:
                result = self.tool_executor.execute(
                    ToolCall(
                        tool_name="validate_reference",
                        arguments={
                            "reference_type": "function",
                            "name": elem,
                            "file_path": fact.source_file
                            if fact.source_file != "unknown"
                            else None,
                        },
                    )
                )
                if result.success and result.result.get("found", False):
                    validated_elements.append(elem)
                else:
                    suggestions = (
                        result.result.get("suggestions", []) if result.success else []
                    )
                    if suggestions:
                        console.print(
                            f"  [yellow]⚠ Fact {fact.fact_id}: element '{elem}' "
                            f"not found, did you mean '{suggestions[0]}'?[/yellow]"
                        )
                        validated_elements.append(suggestions[0])
                    else:
                        console.print(
                            f"  [yellow]⚠ Fact {fact.fact_id}: element '{elem}' "
                            f"not found in codebase, removing[/yellow]"
                        )

            fact.source_elements = validated_elements
            validated.append(fact)

        return validated

    def _enrich_facts_with_source_code(
        self,
        facts: list[TechnicalFact],
        ast_elements: list[CodeElement],
        source_diffs: dict[str, dict[str, str]] | None = None,
    ) -> list[TechnicalFact]:
        """Enrich technical facts with source code snippets from AST elements.

        Populates the code_snippets field on each fact with actual source code
        for the elements referenced in source_elements. Also populates
        before_after_code with before/after comparisons from source diffs.

        Args:
            facts: List of technical facts to enrich
            ast_elements: List of code elements with source_code populated
            source_diffs: Optional dict from _compute_source_diffs() with before/after code

        Returns:
            Enriched facts with code_snippets and before_after_code populated
        """
        # Build lookup: element name -> source code
        element_source: dict[str, str] = {}
        for elem in ast_elements:
            if elem.source_code:
                element_source[elem.name] = elem.source_code

        # Build lookup: element name -> diff data (before/after)
        diff_by_name: dict[str, dict[str, str]] = {}
        if source_diffs:
            for diff_data in source_diffs.values():
                elem_name = diff_data.get("element_name", "")
                if elem_name:
                    diff_by_name[elem_name] = diff_data

        enriched = []
        for fact in facts:
            snippets: dict[str, str] = {}
            for elem_name in fact.source_elements:
                if elem_name in element_source:
                    snippets[elem_name] = element_source[elem_name]
            # Also try to get source from tool executor if available
            if self.tool_executor and not snippets:
                for elem_name in fact.source_elements[
                    :3
                ]:  # Limit to 3 tool calls per fact
                    try:
                        result = self.tool_executor.execute(
                            ToolCall(
                                tool_name="get_element_source",
                                arguments={"element_name": elem_name},
                            )
                        )
                        if (
                            result.success
                            and result.result
                            and result.result.get("found")
                        ):
                            source = result.result.get("source_code")
                            if source:
                                snippets[elem_name] = source
                    except Exception:
                        pass  # Graceful fallback
            if snippets:
                fact.code_snippets = snippets

            # Enrich with before/after code from source diffs
            before_after: dict[str, dict[str, str]] = {}
            for elem_name in fact.source_elements:
                if elem_name in diff_by_name:
                    diff_data = diff_by_name[elem_name]
                    before_after[elem_name] = {
                        "before": diff_data.get("before", ""),
                        "after": diff_data.get("after", ""),
                        "diff": diff_data.get("diff", ""),
                    }
            if before_after:
                fact.before_after_code = before_after

            # Enrich with usage examples from base and head worktrees
            # Only for API-change facts where we can find real call sites
            if fact.category in ("api", "api_change"):
                usages: dict[str, dict[str, list[str]]] = {}
                # Get worktree paths (disabled: metadata format mismatch)
                base_worktree, head_worktree = None, None
                for elem_name in fact.source_elements:
                    before_usages: list[str] = []
                    after_usages: list[str] = []
                    if base_worktree:
                        before_usages = self._find_usages_in_worktree(
                            elem_name, base_worktree, max_examples=2
                        )
                    if head_worktree:
                        after_usages = self._find_usages_in_worktree(
                            elem_name, head_worktree, max_examples=2
                        )
                    if before_usages or after_usages:
                        usages[elem_name] = {
                            "before_usages": before_usages,
                            "after_usages": after_usages,
                        }
                if usages:
                    fact.usages = usages

            enriched.append(fact)

        return enriched

    def _save_facts(self, facts: list[TechnicalFact]) -> None:
        """Save facts to knowledge base."""

        facts_dir = get_kb_path(self.config, self.analysis_id) / "technical_facts"
        facts_dir.mkdir(parents=True, exist_ok=True)

        # Save as JSON array (using mode="json" for datetime serialization)
        facts_data = [fact.model_dump(mode="json") for fact in facts]
        facts_file = facts_dir / "facts.json"
        facts_file.write_text(json.dumps(facts_data, indent=2))

        # Also save as individual files for easy access
        for fact in facts:
            fact_file = facts_dir / f"{fact.fact_id}.json"
            fact_file.write_text(json.dumps(fact.model_dump(mode="json"), indent=2))

    @classmethod
    def load_facts(cls, kb_path: Path) -> list[TechnicalFact]:
        """Load facts from KB."""
        facts_file = kb_path / "technical_facts" / "facts.json"

        if not facts_file.exists():
            return []

        data = json.loads(facts_file.read_text())
        return [TechnicalFact(**fact_data) for fact_data in data]
