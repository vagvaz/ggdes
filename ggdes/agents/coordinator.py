"""Coordinator Agent for planning document generation."""

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt

from ggdes.llm import LLMFactory, ConversationContext
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    DiagramSpec,
    DocumentPlan,
    SectionPlan,
    StoragePolicy,
    TechnicalFact,
)

console = Console()


class Coordinator:
    """Plan document structure and content based on technical facts."""

    def __init__(
        self,
        repo_path: Path,
        config,
        analysis_id: str,
    ):
        """Initialize coordinator.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading/writing to KB
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.llm = LLMFactory.from_config(config)
        self.conversation: Optional[ConversationContext] = None

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context."""
        self.conversation = ConversationContext(
            system_prompt=get_prompt("coordinator", "system"),
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _load_facts(self) -> list[TechnicalFact]:
        """Load technical facts from KB."""
        from ggdes.config import get_kb_path

        facts_file = (
            get_kb_path(self.config, self.analysis_id)
            / "technical_facts"
            / "facts.json"
        )

        if not facts_file.exists():
            return []

        data = json.loads(facts_file.read_text())
        return [TechnicalFact(**fact_data) for fact_data in data]

    async def create_plan(
        self,
        target_formats: list[str],
        interactive: bool = True,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
    ) -> list[DocumentPlan]:
        """Create document plans for specified formats.

        Args:
            target_formats: List of output formats (markdown, docx, pptx, pdf)
            interactive: Whether to ask user for input
            storage_policy: How to persist conversation

        Returns:
            List of document plans (one per format)
        """
        # Initialize conversation
        self._init_conversation(storage_policy)

        # Load technical facts
        facts = self._load_facts()
        if not facts:
            raise ValueError(f"No technical facts found for {self.analysis_id}")

        console.print(f"\n[bold]Loaded {len(facts)} technical facts[/bold]")

        # Categorize facts for planning
        facts_by_category = self._categorize_facts(facts)

        # Get user context if interactive
        user_context = {}
        if interactive:
            user_context = await self._gather_user_input(facts_by_category)

        # Create plans for each format
        plans = []
        for fmt in target_formats:
            plan = await self._create_format_plan(
                fmt, facts, facts_by_category, user_context
            )
            plans.append(plan)

        # Save conversation
        from ggdes.config import get_kb_path

        kb_path = (
            get_kb_path(self.config, self.analysis_id) / "conversations" / "coordinator"
        )
        self.conversation.save(kb_path)

        # Save plans
        self._save_plans(plans)

        return plans

    def _categorize_facts(self, facts: list[TechnicalFact]) -> dict:
        """Group facts by category for planning."""
        categories = {}
        for fact in facts:
            cat = fact.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(fact)
        return categories

    async def _gather_user_input(self, facts_by_category: dict) -> dict:
        """Interactive mode: ask user for context and preferences."""
        context = {}

        console.print("\n[bold cyan]Document Planning Questions[/bold cyan]")
        console.print("Help me create the best documentation for your changes.\n")

        # Target audience
        context["audience"] = Prompt.ask(
            "Who is the target audience?",
            choices=["developers", "architects", "stakeholders", "all"],
            default="developers",
        )

        # Focus areas
        available_categories = list(facts_by_category.keys())
        if len(available_categories) > 1:
            focus = Prompt.ask(
                "Which aspects should the documentation focus on?",
                default="all",
            )
            context["focus"] = focus

        # Detail level
        context["detail_level"] = Prompt.ask(
            "What level of detail?",
            choices=["high", "medium", "low"],
            default="medium",
        )

        # Diagrams
        context["include_diagrams"] = Confirm.ask(
            "Include architecture diagrams?", default=True
        )

        # Special sections
        if "api" in facts_by_category:
            context["include_api_reference"] = Confirm.ask(
                "Include API reference section?", default=True
            )

        if "behavior" in facts_by_category:
            context["include_migration_guide"] = Confirm.ask(
                "Include migration guide for breaking changes?",
                default=len(facts_by_category.get("behavior", [])) > 0,
            )

        # Additional context
        additional = Prompt.ask(
            "Any additional context or specific aspects to cover? (optional)",
            default="",
        )
        if additional:
            context["additional_context"] = additional

        console.print("\n[green]✓ Preferences captured[/green]\n")

        return context

    async def _create_format_plan(
        self,
        fmt: str,
        facts: list[TechnicalFact],
        facts_by_category: dict,
        user_context: dict,
    ) -> DocumentPlan:
        """Create a document plan for a specific format."""
        console.print(f"[dim]Creating {fmt} plan...[/dim]")

        # Build prompt for LLM
        prompt = self._build_planning_prompt(
            fmt, facts, facts_by_category, user_context
        )

        self.conversation.add_user_message(prompt)
        context = self.conversation.get_context_for_llm()

        # Generate plan via LLM
        plan_data = await self._generate_plan_response(context, fmt)

        # Create DocumentPlan
        sections = []
        for i, sec_data in enumerate(plan_data.get("sections", [])):
            sections.append(
                SectionPlan(
                    title=sec_data.get("title", f"Section {i + 1}"),
                    description=sec_data.get("description", ""),
                    technical_facts=sec_data.get("technical_facts", []),
                    code_references=sec_data.get("code_references", []),
                    diagrams=sec_data.get("diagrams", []),
                )
            )

        diagrams = []
        for i, diag_data in enumerate(plan_data.get("diagrams", [])):
            diagrams.append(
                DiagramSpec(
                    diagram_type=diag_data.get("type", "architecture"),
                    title=diag_data.get("title", f"Diagram {i + 1}"),
                    description=diag_data.get("description", ""),
                    elements_to_include=diag_data.get("elements", []),
                    format="plantuml",
                )
            )

        plan = DocumentPlan(
            analysis_id=self.analysis_id,
            format=fmt,
            title=plan_data.get("title", f"Design Document - {self.analysis_id}"),
            audience=user_context.get("audience", "developers"),
            sections=sections,
            diagrams=diagrams,
        )

        console.print(
            f"  [green]✓[/green] {fmt}: {len(sections)} sections, {len(diagrams)} diagrams"
        )

        return plan

    def _build_planning_prompt(
        self,
        fmt: str,
        facts: list[TechnicalFact],
        facts_by_category: dict,
        user_context: dict,
    ) -> str:
        """Build prompt for document planning."""
        prompt = f"""Create a document plan for a {fmt.upper()} format design document.

Technical Facts Available ({len(facts)} total):
"""

        # Summarize facts by category
        for category, cat_facts in facts_by_category.items():
            prompt += f"\n{category.upper()} ({len(cat_facts)} facts):\n"
            for fact in cat_facts[:5]:  # Limit to first 5 per category
                prompt += f"  - {fact.fact_id}: {fact.description[:100]}...\n"
            if len(cat_facts) > 5:
                prompt += f"  ... and {len(cat_facts) - 5} more\n"

        prompt += f"""
User Requirements:
- Target Audience: {user_context.get("audience", "developers")}
- Detail Level: {user_context.get("detail_level", "medium")}
- Include Diagrams: {user_context.get("include_diagrams", True)}
"""

        if "focus" in user_context:
            prompt += f"- Focus Areas: {user_context['focus']}\n"

        if user_context.get("additional_context"):
            prompt += f"\nAdditional Context: {user_context['additional_context']}\n"

        # Format-specific guidance
        if fmt == "markdown":
            prompt += """
Format: Markdown - optimized for web viewing, code blocks, and links.
"""
        elif fmt == "docx":
            prompt += """
Format: Word Document - formal structure, page breaks, table of contents.
"""
        elif fmt == "pptx":
            prompt += """
Format: PowerPoint - visual emphasis, bullet points, minimal text per slide.
"""
        elif fmt == "pdf":
            prompt += """
Format: PDF - print-ready, bookmarks, formal layout.
"""

        prompt += """
Provide a document plan as JSON:
{
  "title": "Document title",
  "sections": [
    {
      "title": "Section name",
      "description": "What this section covers",
      "technical_facts": ["fact_id_1", "fact_id_2"],
      "code_references": ["function_name", "class_name"],
      "diagrams": ["diagram_id_1"]
    }
  ],
  "diagrams": [
    {
      "type": "architecture|flow|sequence|class",
      "title": "Diagram title",
      "description": "What to show",
      "elements": ["element_1", "element_2"]
    }
  ]
}
"""

        return prompt

    async def _generate_plan_response(self, context: list[dict], fmt: str) -> dict:
        """Generate document plan from conversation context."""
        response = self.llm.chat(
            messages=context,
            temperature=0.4,
            max_tokens=4096,
        )

        # Parse JSON response
        try:
            import json

            # Extract JSON from response
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()

            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback: return default plan
            return {
                "title": f"Design Document - {self.analysis_id}",
                "sections": [
                    {
                        "title": "Overview",
                        "description": "Summary of changes",
                        "technical_facts": [],
                        "code_references": [],
                        "diagrams": [],
                    }
                ],
                "diagrams": [],
            }

    def _save_plans(self, plans: list[DocumentPlan]) -> None:
        """Save document plans to knowledge base."""
        from ggdes.config import get_kb_path

        plans_dir = get_kb_path(self.config, self.analysis_id) / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)

        # Save each plan
        for plan in plans:
            plan_file = plans_dir / f"plan_{plan.format}.json"
            plan_file.write_text(json.dumps(plan.model_dump(), indent=2, default=str))

        # Save index
        index = {
            "analysis_id": self.analysis_id,
            "available_formats": [p.format for p in plans],
            "plans": [f"plan_{p.format}.json" for p in plans],
        }
        (plans_dir / "index.json").write_text(json.dumps(index, indent=2))

    @classmethod
    def load_plan(cls, kb_path: Path, fmt: str) -> Optional[DocumentPlan]:
        """Load a specific document plan from KB."""
        plan_file = kb_path / "plans" / f"plan_{fmt}.json"

        if not plan_file.exists():
            return None

        data = json.loads(plan_file.read_text())
        return DocumentPlan(**data)

    @classmethod
    def list_available_formats(cls, kb_path: Path) -> list[str]:
        """List available document formats in KB."""
        index_file = kb_path / "plans" / "index.json"

        if not index_file.exists():
            return []

        data = json.loads(index_file.read_text())
        return data.get("available_formats", [])
