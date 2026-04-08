"""Technical Author Agent for synthesizing code analysis into technical facts."""

import json
from pathlib import Path
from typing import Optional

from rich.console import Console

from ggdes.llm import LLMFactory, ConversationContext, estimate_tokens
from ggdes.llm.conversation import estimate_tokens
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    ChangeSummary,
    CodeElement,
    StoragePolicy,
    TechnicalFact,
)
from ggdes.agents.skill_utils import load_skill

console = Console()


class TechnicalAuthor:
    """Synthesize git analysis and AST data into structured technical facts."""

    def __init__(
        self,
        repo_path: Path,
        config,
        analysis_id: str,
        user_context: Optional[dict] = None,
        language_expert_skill: Optional[str] = None,
    ):
        """Initialize technical author.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading/writing to KB
            user_context: Optional user-provided context (focus areas, audience, purpose)
            language_expert_skill: Optional name of language expert skill to load (e.g., 'python-expert', 'cpp-expert')
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context = user_context or {}
        self.llm = LLMFactory.from_config(config)
        self.conversation: Optional[ConversationContext] = None
        self.chunk_size_tokens = 30000  # Process AST data in chunks if needed
        self._coauthor_skill: Optional[str] = None
        self._language_expert_skill: Optional[str] = None

        # Load skills with graceful fallback
        self._load_skills(language_expert_skill)

    def _load_skills(self, language_expert_skill: Optional[str] = None) -> None:
        """Load coauthor and optional language expert skills."""
        # Load coauthor skill for writing/documentation expertise (now called doc-coauthoring)
        try:
            self._coauthor_skill = load_skill("doc-coauthoring", self.repo_path)
            if self._coauthor_skill:
                console.print(
                    f"  [dim]Loaded doc-coauthoring skill for enhanced documentation synthesis[/dim]"
                )
        except Exception:
            console.print(
                f"  [dim]Doc-coauthoring skill not available, continuing with default synthesis[/dim]"
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
        # Build system prompt with loaded skills
        system_prompt = get_prompt("technical_author", "system")

        # Add coauthor skill content if available
        if self._coauthor_skill:
            system_prompt += f"\n\n=== DOCUMENTATION EXPERTISE ===\n{self._coauthor_skill}\n=== END EXPERTISE ==="

        # Add language expert skill content if available
        if self._language_expert_skill:
            system_prompt += f"\n\n=== LANGUAGE EXPERTISE ===\n{self._language_expert_skill}\n=== END EXPERTISE ==="

        # Add user context guidance if provided
        user_guidance = self._build_user_context_guidance()
        if user_guidance:
            system_prompt += (
                f"\n\n=== USER FOCUS ===\n{user_guidance}\n=== END FOCUS ==="
            )

        self.conversation = ConversationContext(
            system_prompt=system_prompt,
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _build_user_context_guidance(self) -> str:
        """Build guidance text from user context."""
        guidance_parts = []

        if "focus_areas" in self.user_context:
            guidance_parts.append(f"Focus Areas: {self.user_context['focus_areas']}")

        if "audience" in self.user_context:
            guidance_parts.append(f"Target Audience: {self.user_context['audience']}")

        if "purpose" in self.user_context:
            purposes = self.user_context["purpose"]
            if isinstance(purposes, list):
                guidance_parts.append(f"Document Purpose: {', '.join(purposes)}")
            else:
                guidance_parts.append(f"Document Purpose: {purposes}")

        if "detail_level" in self.user_context:
            guidance_parts.append(f"Detail Level: {self.user_context['detail_level']}")

        if "additional_context" in self.user_context:
            guidance_parts.append(
                f"Additional Context: {self.user_context['additional_context']}"
            )

        return "\n".join(guidance_parts) if guidance_parts else ""

    def _load_git_analysis(self) -> Optional[ChangeSummary]:
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
    ) -> list[TechnicalFact]:
        """Synthesize technical facts from analysis data.

        Args:
            storage_policy: How to persist conversation

        Returns:
            List of technical facts
        """
        # Initialize conversation
        self._init_conversation(storage_policy)

        # Load data from previous stages
        change_summary = self._load_git_analysis()
        if not change_summary:
            raise ValueError(f"No git analysis found for {self.analysis_id}")

        base_elements = self._load_ast_data("base")
        head_elements = self._load_ast_data("head")

        # Find elements in changed files
        changed_base = self._find_changed_elements(change_summary, base_elements)
        changed_head = self._find_changed_elements(change_summary, head_elements)

        all_facts = []

        # Turn 1: API Changes Analysis
        api_facts = await self._analyze_api_changes(
            change_summary, changed_base, changed_head
        )
        all_facts.extend(api_facts)

        # Turn 2: Behavioral Changes Analysis
        behavior_facts = await self._analyze_behavioral_changes(
            change_summary, changed_base, changed_head
        )
        all_facts.extend(behavior_facts)

        # Turn 3: Architecture/Dependency Analysis
        arch_facts = await self._analyze_architecture_changes(
            change_summary, base_elements, head_elements
        )
        all_facts.extend(arch_facts)

        # Save conversation to KB
        from ggdes.config import get_kb_path

        kb_path = (
            get_kb_path(self.config, self.analysis_id)
            / "conversations"
            / "technical_author"
        )
        self.conversation.save(kb_path)

        # Save facts to KB
        self._save_facts(all_facts)

        return all_facts

    async def _analyze_api_changes(
        self,
        change_summary: ChangeSummary,
        base_elements: list[CodeElement],
        head_elements: list[CodeElement],
    ) -> list[TechnicalFact]:
        """Analyze API changes (signatures, new/deleted functions)."""
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

            self.conversation.add_user_message(prompt)
            context = self.conversation.get_context_for_llm()

            # Generate structured facts
            response = await self._generate_facts_response(context)

            try:
                import json

                facts_data = (
                    json.loads(response) if isinstance(response, str) else response
                )
                if isinstance(facts_data, list):
                    for i, fact_data in enumerate(facts_data):
                        fact_data["fact_id"] = f"api_{i + 1:03d}"
                        fact_data["category"] = "api"
                        facts.append(TechnicalFact(**fact_data))
            except Exception as e:
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
        self, new_apis: list, deleted_apis: list, modified_apis: list
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
    ) -> list[TechnicalFact]:
        """Analyze behavioral changes (what code does differently)."""
        facts = []

        # Use git analysis to guide behavioral analysis
        prompt = f"""Based on the git change analysis, identify behavioral changes:

Description: {change_summary.description}
Intent: {change_summary.impact}
Breaking Changes: {change_summary.breaking_changes}

Files Changed ({len(change_summary.files_changed)}):
"""
        for f in change_summary.files_changed[:10]:
            prompt += f"- {f.path}: {f.summary}\n"

        prompt += """
For each behavioral change, provide:
1. Fact ID (e.g., behavior_001)
2. Category: behavior
3. Description: How behavior changed
4. What was the old behavior
5. What is the new behavior
6. Impact on users/system

Format as JSON array."""

        self.conversation.add_user_message(prompt)
        context = self.conversation.get_context_for_llm()

        response = await self._generate_facts_response(context)

        try:
            import json

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

    async def _generate_facts_response(self, context: list[dict]) -> str:
        """Generate response from conversation context."""
        return self.llm.chat(
            messages=context,
            temperature=0.3,
            max_tokens=4096,
        )

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
