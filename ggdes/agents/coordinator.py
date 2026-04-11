"""Coordinator Agent for planning document generation."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt

from ggdes.config import GGDesConfig
from ggdes.llm import ConversationContext, LLMFactory
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
        config: GGDesConfig,
        analysis_id: str,
        user_context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize coordinator.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading/writing to KB
            user_context: Optional user-provided context from CLI questionnaire
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context = user_context or {}
        self.llm = LLMFactory.from_config(config)
        self.conversation: ConversationContext | None = None

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context.

        System prompt structure (in order of priority):
        1. Base system prompt - core instructions
        2. User guidance - marked as VERY IMPORTANT
        """
        system_prompt_parts = []

        # 1. BASE SYSTEM PROMPT - Core instructions
        base_prompt = get_prompt("coordinator", "system")
        system_prompt_parts.append(base_prompt)

        # 2. USER GUIDANCE - Marked as VERY IMPORTANT
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
        parallel: bool = True,
    ) -> list[DocumentPlan]:
        """Create document plans for specified formats.

        Args:
            target_formats: List of output formats (markdown, docx, pptx, pdf)
            interactive: Whether to ask user for input
            storage_policy: How to persist conversation
            parallel: Whether to create plans in parallel (default: True)

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

        # Get user context - use pre-populated context from CLI if available
        user_context = dict(self.user_context)  # Copy to avoid modifying original
        if interactive and not user_context:
            # Only ask questions if no context was provided from CLI
            user_context = await self._gather_user_input(facts_by_category)

        # Create plans for each format
        if parallel and len(target_formats) > 1:
            # Run format plans in parallel
            tasks = [
                self._create_format_plan(fmt, facts, facts_by_category, user_context)
                for fmt in target_formats
            ]
            plans = await asyncio.gather(*tasks, return_exceptions=True)
            # Filter out exceptions, log errors
            successful_plans = []
            for i, result in enumerate(plans):
                if isinstance(result, Exception):
                    console.print(
                        f"[red]Plan creation failed for {target_formats[i]}: {result}[/red]"
                    )
                else:
                    successful_plans.append(result)
            plans = successful_plans
        else:
            # Sequential (original behavior)
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
        if self.conversation:
            self.conversation.save(kb_path)

        # Save plans
        self._save_plans(plans)

        return plans

    def _categorize_facts(
        self, facts: List[TechnicalFact]
    ) -> Dict[str, List[TechnicalFact]]:
        """Group facts by category for planning."""
        categories: dict[str, list[TechnicalFact]] = {}
        for fact in facts:
            cat = fact.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(fact)
        return categories

    async def _gather_user_input(
        self, facts_by_category: Dict[str, List[TechnicalFact]]
    ) -> Dict[str, Any]:
        """Interactive mode: ask user for context and preferences."""
        # Use pre-populated context from CLI as defaults
        context = dict(self.user_context)

        console.print("\n[bold cyan]Document Planning Questions[/bold cyan]")
        console.print("Help me create the best documentation for your changes.\n")

        # Target audience (use CLI value as default if available)
        default_audience = context.get("audience", "developers")
        context["audience"] = Prompt.ask(
            "Who is the target audience?",
            choices=["business", "technical_managers", "developers", "all"],
            default=default_audience,
        )

        # Focus areas (use CLI value as default if available)
        available_categories = list(facts_by_category.keys())
        if len(available_categories) > 1:
            default_focus = context.get("focus_areas", "all")
            focus = Prompt.ask(
                "Which aspects should the documentation focus on?",
                default=default_focus,
            )
            context["focus"] = focus

        # Detail level (use CLI value as default if available)
        default_detail = context.get("detail_level", "medium")
        # Map CLI values to coordinator choices if needed
        detail_map = {
            "quick_summary": "low",
            "medium": "medium",
            "comprehensive": "high",
        }
        mapped_detail = detail_map.get(default_detail, default_detail)
        context["detail_level"] = Prompt.ask(
            "What level of detail?",
            choices=["high", "medium", "low"],
            default=mapped_detail,
        )

        # Diagrams
        context["include_diagrams"] = Confirm.ask(
            "Include architecture diagrams?", default=True
        )

        # Special sections - use CLI purpose to guide defaults
        purposes = context.get("purpose", [])
        if isinstance(purposes, str):
            purposes = [purposes]

        if "api" in facts_by_category or "api_reference" in purposes:
            context["include_api_reference"] = Confirm.ask(
                "Include API reference section?",
                default="api_reference" in purposes,
            )

        if "behavior" in facts_by_category or "migration_guide" in purposes:
            context["include_migration_guide"] = Confirm.ask(
                "Include migration guide for breaking changes?",
                default=(
                    len(facts_by_category.get("behavior", [])) > 0
                    or "migration_guide" in purposes
                ),
            )

        # Additional context (use CLI value as default if available)
        default_additional = context.get("additional_context", "")
        additional = Prompt.ask(
            "Any additional context or specific aspects to cover? (optional)",
            default=default_additional,
        )
        if additional:
            context["additional_context"] = additional

        console.print("\n[green]✓ Preferences captured[/green]\n")

        return context

    async def _create_format_plan(
        self,
        fmt: str,
        facts: List[TechnicalFact],
        facts_by_category: Dict[str, List[TechnicalFact]],
        user_context: Dict[str, Any],
    ) -> DocumentPlan:
        """Create a document plan for a specific format with its own conversation context."""
        from ggdes.llm import ConversationContext, StoragePolicy

        # Create a fresh conversation context for this format
        conv = ConversationContext(
            system_prompt=self.conversation.system_prompt if self.conversation else "",
            storage_policy=self.conversation.storage_policy
            if self.conversation
            else StoragePolicy.SUMMARY,
        )

        console.print(f"[dim]Creating {fmt} plan...[/dim]")

        # Build prompt for LLM
        prompt = self._build_planning_prompt(
            fmt, facts, facts_by_category, user_context
        )

        conv.add_user_message(prompt)
        context = conv.get_context_for_llm()

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
            template=None,
            user_context=user_context,
        )

        console.print(
            f"  [green]✓[/green] {fmt}: {len(sections)} sections, {len(diagrams)} diagrams"
        )

        return plan

    def _build_planning_prompt(
        self,
        fmt: str,
        facts: List[TechnicalFact],
        facts_by_category: Dict[str, List[TechnicalFact]],
        user_context: Dict[str, Any],
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

        # Handle focus from CLI (focus_areas) or coordinator (focus)
        focus_value = user_context.get("focus", user_context.get("focus_areas", ""))
        if focus_value:
            prompt += f"- Focus Areas: {focus_value}\n"

        # Handle purpose from CLI
        purposes = user_context.get("purpose", [])
        if purposes:
            if isinstance(purposes, list):
                prompt += f"- Document Purpose: {', '.join(purposes)}\n"
            else:
                prompt += f"- Document Purpose: {purposes}\n"

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

    async def _generate_plan_response(
        self, context: List[Dict[str, Any]], fmt: str
    ) -> Dict[str, Any]:
        """Generate document plan from conversation context."""
        response = self.llm.chat(
            messages=context,
            temperature=0.4,
            max_tokens=4096,
        )

        # Parse JSON response
        try:
            # Extract JSON from response
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()

            result: dict[str, Any] = json.loads(response)
            return result
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
    def load_plan(cls, kb_path: Path, fmt: str) -> DocumentPlan | None:
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

        data: dict[str, Any] = json.loads(index_file.read_text())
        formats: list[str] = data.get("available_formats", [])
        return formats
