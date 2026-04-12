"""Technical Author Agent for synthesizing code analysis into technical facts."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from ggdes.agents.skill_utils import load_skill
from ggdes.config import GGDesConfig
from ggdes.llm import ConversationContext, LLMFactory
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    ChangeSummary,
    CodeElement,
    StoragePolicy,
    TechnicalFact,
)
from ggdes.tools import ToolCall, ToolExecutor, TOOL_DEFINITIONS, chat_with_tools

console = Console()


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
        user_context: Optional[Dict[str, Any]] = None,
        language_expert_skill: Optional[str] = None,
        tool_executor: Optional[ToolExecutor] = None,
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
        """Initialize conversation context.

        System prompt structure (in order of priority):
        1. Skills first (coauthor + language expertise) - foundational knowledge
        2. Base system prompt - core instructions
        3. User guidance - marked as VERY IMPORTANT
        """
        system_prompt_parts = []

        # 1. SKILLS FIRST - Documentation and language expertise
        if self._coauthor_skill:
            system_prompt_parts.append(
                f"=== DOCUMENTATION EXPERTISE ===\n"
                f"{self._coauthor_skill}\n"
                f"=== END DOCUMENTATION EXPERTISE ==="
            )

        if self._language_expert_skill:
            system_prompt_parts.append(
                f"=== LANGUAGE EXPERTISE ===\n"
                f"{self._language_expert_skill}\n"
                f"=== END LANGUAGE EXPERTISE ==="
            )

        # 2. BASE SYSTEM PROMPT - Core instructions
        base_prompt = get_prompt("technical_author", "system")
        system_prompt_parts.append(base_prompt)

        # 3. USER GUIDANCE - Marked as VERY IMPORTANT
        user_guidance = self._build_user_context_guidance()
        if user_guidance:
            system_prompt_parts.append(
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════════╗\n"
                f"║                    ⚠️  VERY IMPORTANT  ⚠️                        ║\n"
                f"║              USER REQUIREMENTS (MUST FOLLOW)                   ║\n"
                f"╚══════════════════════════════════════════════════════════════════╝\n"
                f"\n{user_guidance}\n"
                f"\n═══════════════════════════════════════════════════════════════════\n"
                f"YOU MUST ADHERE TO ALL USER REQUIREMENTS ABOVE. "
                f"THESE OVERRIDE ANY DEFAULT BEHAVIORS."
            )

        # Combine all parts
        system_prompt = "\n\n".join(system_prompt_parts)

        self.conversation = ConversationContext(
            system_prompt=system_prompt,
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _build_user_context_guidance(self) -> str:
        """Build guidance text from user context."""
        from ggdes.agents.skill_utils import build_user_context_guidance

        return build_user_context_guidance(self.user_context)

    def _load_git_analysis(self) -> ChangeSummary | None:
        """Load git analysis results from KB."""
        from ggdes.config import get_kb_path

        analysis_path = (
            get_kb_path(self.config, self.analysis_id) / "git_analysis" / "summary.json"
        )

        if not analysis_path.exists():
            return None

        data = json.loads(analysis_path.read_text())
        return ChangeSummary(**data)

    def _load_ast_data(self, which: str = "head") -> list[CodeElement]:
        """Load AST data from KB.

        Args:
            which: "base" or "head"

        Returns:
            List of code elements
        """
        from ggdes.config import get_kb_path

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

        if parallel:
            # Run all three analysis turns in parallel
            all_facts = await self._analyze_parallel(
                change_summary, changed_base, changed_head
            )
        else:
            # Sequential execution
            all_facts = []

            # Turn 1: API Changes Analysis (only changed elements)
            api_facts = await self._analyze_api_changes(
                change_summary, changed_base, changed_head
            )
            all_facts.extend(api_facts)

            # Turn 2: Behavioral Changes Analysis (only changed elements)
            behavior_facts = await self._analyze_behavioral_changes(
                change_summary, changed_base, changed_head
            )
            all_facts.extend(behavior_facts)

            # Turn 3: Architecture/Dependency Analysis (only changed elements)
            arch_facts = await self._analyze_architecture_changes(
                change_summary, changed_base, changed_head
            )
            all_facts.extend(arch_facts)

        # Save conversation to KB
        from ggdes.config import get_kb_path

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

        # Save facts to KB
        self._save_facts(all_facts)

        return all_facts

    async def _analyze_api_changes(
        self,
        change_summary: ChangeSummary,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
        conversation: ConversationContext | None = None,
    ) -> list[TechnicalFact]:
        """Analyze API changes (signatures, new/deleted functions)."""
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
            prompt = f"""Analyze the following API changes and describe each factually:

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

            prompt += """
For each API change, provide:
1. Fact ID (e.g., api_001, api_002)
2. Category: api
3. Description: What changed and why
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
        new_apis: List[str],
        deleted_apis: List[str],
        modified_apis: List[dict[str, str]],
    ) -> List[TechnicalFact]:
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
    ) -> list[TechnicalFact]:
        """Analyze behavioral changes (what code does differently)."""
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

Files Changed ({len(change_summary.files_changed)}):
"""
        for f in change_summary.files_changed[:10]:
            prompt += f"- {f.path}: {f.summary}\n"

        prompt += f"""
IMPORTANT: Only analyze behavioral changes in the {len(changed_files)} files that were changed. Do not reference files that were not in the git diff.

For each behavioral change, provide:
1. Fact ID (e.g., behavior_001)
2. Category: behavior
3. Description: How behavior changed
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
                change_summary, changed_base, changed_head, conversation=api_conv
            ),
            self._analyze_behavioral_changes(
                change_summary, changed_base, changed_head, conversation=behavior_conv
            ),
            self._analyze_architecture_changes(
                change_summary, changed_base, changed_head
            ),
        )

        all_facts = []
        all_facts.extend(api_facts or [])
        all_facts.extend(behavior_facts or [])
        all_facts.extend(arch_facts or [])
        return all_facts

    async def _generate_facts_response(self, context: List[Dict[str, Any]]) -> str:
        """Generate response from conversation context.

        Uses tool-augmented chat when a ToolExecutor is available, allowing
        the LLM to verify code references against the actual codebase.
        Falls back to plain chat when no tools are configured.
        """
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

    def _save_facts(self, facts: list[TechnicalFact]) -> None:
        """Save facts to knowledge base."""
        from ggdes.config import get_kb_path

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
