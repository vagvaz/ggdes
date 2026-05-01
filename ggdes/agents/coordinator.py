"""Programmatic coordinator — loads and prepares shared context for output agents.

No longer an LLM agent. Each output agent plans its own content for its medium.
"""

import json
from pathlib import Path
from typing import Any

from loguru import logger
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ggdes.config import GGDesConfig, get_kb_path
from ggdes.schemas import StoragePolicy, TechnicalFact

console = Console()


class Coordinator:
    """Prepare shared data context that all output agents consume.

    Responsibilities:
    - Load technical facts, semantic diff, and pipeline metadata from the KB.
    - Categorize facts for downstream use.
    - Gather user context interactively (when not provided via CLI).
    - Persist the assembled context so each output agent can load it.
    """

    def __init__(
        self,
        repo_path: Path,
        config: GGDesConfig,
        analysis_id: str,
        user_context: dict[str, Any] | None = None,
        review_feedback: str | None = None,
    ):
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context = user_context or {}
        self.review_feedback = review_feedback

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def prepare_data(
        self,
        target_formats: list[str],
        interactive: bool = True,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
    ) -> dict[str, Any]:
        """Load and prepare shared context for all output agents.

        Returns the assembled context dict and persists it to the KB so that
        each ``OutputAgent`` subclass can load it independently.

        Args:
            target_formats: List of output formats (markdown, docx, pptx, pdf).
            interactive: Whether to prompt the user when CLI context is missing.
            storage_policy: Ignored by the programmatic coordinator (retained for
                            signature compatibility).

        Returns:
            Shared context dict with keys ``technical_facts``, ``facts_by_category``,
            ``user_context``, ``semantic_diff``.
        """
        # Load raw data
        facts = self._load_facts()
        if not facts:
            raise ValueError(f"No technical facts found for {self.analysis_id}")

        logger.info(
            "Coordinator: preparing context | facts=%d formats=%s analysis=%s",
            len(facts),
            target_formats,
            self.analysis_id,
        )

        console.print(f"\n[bold]Loaded {len(facts)} technical facts[/bold]")

        # Categorise facts
        facts_by_category = self._categorize_facts(facts)
        for cat, items in facts_by_category.items():
            console.print(f"  [dim]{cat}: {len(items)} facts[/dim]")

        # Semantic diff
        semantic_diff_data = self._load_semantic_diff()
        if semantic_diff_data:
            summary = semantic_diff_data.get("summary", {})
            console.print(
                f"  [dim]Loaded semantic diff: {summary.get('total_changes', 0)} changes, "
                f"impact {summary.get('total_impact_score', 0):.1f}/10[/dim]"
            )
            if summary.get("has_breaking_changes", False):
                console.print(
                    f"  [yellow]⚠ {summary.get('breaking_changes', 0)} breaking change(s)[/yellow]"
                )
        else:
            console.print("  [dim]No semantic diff results[/dim]")

        # Gather user context (interactive fallback when CLI omitted)
        user_context = dict(self.user_context)
        if interactive and not user_context:
            user_context = await self._gather_user_input(facts_by_category)

        # Assemble shared context
        context: dict[str, Any] = {
            "analysis_id": self.analysis_id,
            "technical_facts": [f.model_dump() for f in facts],
            "facts_by_category": {
                cat: [f.model_dump() for f in cat_facts]
                for cat, cat_facts in facts_by_category.items()
            },
            "user_context": user_context,
            "semantic_diff": semantic_diff_data,
            "target_formats": target_formats,
            "review_feedback": self.review_feedback,
        }

        self._save_shared_context(context)
        return context

    # ------------------------------------------------------------------
    # Data loaders
    # ------------------------------------------------------------------

    def _load_facts(self) -> list[TechnicalFact]:
        """Load technical facts from KB."""
        facts_file = (
            get_kb_path(self.config, self.analysis_id)
            / "technical_facts"
            / "facts.json"
        )
        if not facts_file.exists():
            return []
        data = json.loads(facts_file.read_text())
        return [TechnicalFact(**fact_data) for fact_data in data]

    def _load_semantic_diff(self) -> dict[str, Any] | None:
        """Load semantic diff results from KB."""
        path = (
            get_kb_path(self.config, self.analysis_id) / "semantic_diff" / "result.json"
        )
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _categorize_facts(
        facts: list[TechnicalFact],
    ) -> dict[str, list[TechnicalFact]]:
        """Group facts by category."""
        categories: dict[str, list[TechnicalFact]] = {}
        for fact in facts:
            cat = fact.category
            categories.setdefault(cat, []).append(fact)
        return categories

    async def _gather_user_input(
        self,
        facts_by_category: dict[str, list[TechnicalFact]],
    ) -> dict[str, Any]:
        """Interactive mode: ask the user for context and preferences.

        Only called when no CLI-provided user context exists.
        """
        context = dict(self.user_context)

        console.print("\n[bold cyan]Document Planning Questions[/bold cyan]")
        console.print("Help me create the best documentation for your changes.\n")

        default_audience = context.get("audience", "developers")
        context["audience"] = Prompt.ask(
            "Who is the target audience?",
            choices=["business", "technical_managers", "developers", "all"],
            default=default_audience,
        )

        available_categories = list(facts_by_category.keys())
        if len(available_categories) > 1:
            default_focus = context.get("focus_areas", "all")
            context["focus"] = Prompt.ask(
                "Which aspects should the documentation focus on?",
                default=default_focus,
            )

        default_detail = context.get("detail_level", "medium")
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

        context["include_diagrams"] = Confirm.ask(
            "Include architecture diagrams?", default=True
        )

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

        default_additional = context.get("additional_context", "")
        additional = Prompt.ask(
            "Any additional context or specific aspects to cover? (optional)",
            default=default_additional,
        )
        if additional:
            context["additional_context"] = additional

        console.print("\n[green]✓ Preferences captured[/green]\n")
        return context

    def _save_shared_context(self, context: dict[str, Any]) -> None:
        """Persist the assembled context for output agents to consume."""
        context_dir = get_kb_path(self.config, self.analysis_id) / "shared_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "context.json").write_text(
            json.dumps(context, indent=2, default=str)
        )

    # ------------------------------------------------------------------
    # Utility class methods (used by agents during content generation)
    # ------------------------------------------------------------------

    @classmethod
    def load_shared_context(cls, kb_path: Path) -> dict[str, Any] | None:
        """Load the shared context saved by :meth:`prepare_data`."""
        ctx_file = kb_path / "shared_context" / "context.json"
        if not ctx_file.exists():
            return None
        return json.loads(ctx_file.read_text())

    @classmethod
    def load_plan(cls, kb_path: Path, fmt: str) -> dict[str, Any] | None:
        """Load a format-specific plan from KB.

        Plans are now generated by each output agent rather than the coordinator,
        but this method remains for backward compatibility with saved plans.
        """
        plan_file = kb_path / "plans" / f"plan_{fmt}.json"
        if not plan_file.exists():
            return None
        return json.loads(plan_file.read_text())

    @classmethod
    def list_available_formats(cls, kb_path: Path) -> list[str]:
        """List available document formats in KB."""
        index_file = kb_path / "plans" / "index.json"
        if not index_file.exists():
            return []
        data: dict[str, Any] = json.loads(index_file.read_text())
        return data.get("available_formats", [])
