"""Stage reviewer for interactive pipeline review.

Generates summaries of stage output, presents CLI review interface,
and collects user feedback for regeneration.
"""

import json
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

from ggdes.config import get_kb_path
from ggdes.review.review import ReviewDecision, StageReview

console = Console()


# Stages that produce reviewable output
REVIEWABLE_STAGES = {
    "git_analysis": "Git Analysis",
    "change_filter": "Semantic Change Filter",
    "technical_author": "Technical Facts",
    "coordinator_plan": "Document Plans",
    "output_generation": "Generated Documents",
}

# Stages that are not reviewable (infrastructure/internal)
SKIP_STAGES = {
    "worktree_setup",
    "ast_parsing_base",
    "ast_parsing_head",
    "semantic_diff",  # Often runs without explicit user-facing output
}


@dataclass
class StagePreview:
    """A preview of a stage's output for review."""

    stage_name: str
    display_name: str
    summary: str  # One-line summary
    item_count: int  # Total items in output
    key_items: list[dict[str, Any]]  # 3-5 representative items
    item_keys: list[str]  # All item keys for partial selection
    raw_data: Any  # Full output for detailed view
    format_hint: str = "json"  # How to format for display


class StageReviewer:
    """Generates previews and handles CLI review interaction for pipeline stages."""

    def __init__(self, config: Any, analysis_id: str):
        self.config = config
        self.analysis_id = analysis_id
        self.kb_path = get_kb_path(config, analysis_id)

    # -------------------------------------------------------------------------
    # Preview generation per stage
    # -------------------------------------------------------------------------

    def generate_preview(self, stage_name: str) -> StagePreview | None:
        """Generate a reviewable preview of a stage's output."""
        method = f"_preview_{stage_name}"
        if hasattr(self, method):
            preview_method = getattr(self, method)
            return preview_method()  # type: ignore[no-any-return]
        return None

    def _preview_git_analysis(self) -> StagePreview | None:
        """Preview git_analysis output."""
        summary_file = self.kb_path / "git_analysis" / "summary.json"
        if not summary_file.exists():
            return None

        data = json.loads(summary_file.read_text())
        files = data.get("files_changed", [])

        key_items = []
        for f in files[:5]:
            key_items.append(
                {
                    "id": f.get("path", "unknown"),
                    "label": f"{f.get('path', '?')} ({f.get('change_type', 'modified')})",
                    "detail": f"+{f.get('lines_added', 0)}/-{f.get('lines_deleted', 0)}: {f.get('summary', '')[:80]}",
                }
            )

        return StagePreview(
            stage_name="git_analysis",
            display_name="Git Analysis",
            summary=f"{len(files)} files changed across {len(set(f.get('commit_hash', '') for f in files))} commits",
            item_count=len(files),
            key_items=key_items,
            item_keys=[f.get("path", f) for f in files],
            raw_data=data,
        )

    def _preview_change_filter(self) -> StagePreview | None:
        """Preview semantic change filter output."""
        summary_file = self.kb_path / "git_analysis" / "summary.json"
        if not summary_file.exists():
            return None

        data = json.loads(summary_file.read_text())
        is_filtered = data.get("is_filtered", False)
        files = data.get("files_changed", [])

        if is_filtered:
            summary = f"Filtered to {len(files)} relevant files (feature: {data.get('feature_description', '')})"
        else:
            summary = f"{len(files)} files (no filtering applied)"

        key_items = []
        for f in files[:5]:
            ranges = f.get("relevant_line_ranges")
            range_str = ""
            if ranges:
                range_str = f" [lines: {', '.join(f'{s}-{e}' for s, e in ranges[:3])}]"
            key_items.append(
                {
                    "id": f.get("path", "unknown"),
                    "label": f"{f.get('path', '?')} ({f.get('change_type', 'modified')})",
                    "detail": f"+{f.get('lines_added', 0)}/-{f.get('lines_deleted', 0)}{range_str}",
                }
            )

        return StagePreview(
            stage_name="change_filter",
            display_name="Semantic Change Filter",
            summary=summary,
            item_count=len(files),
            key_items=key_items,
            item_keys=[f.get("path", f) for f in files],
            raw_data=data,
        )

    def _preview_technical_author(self) -> StagePreview | None:
        """Preview technical facts output."""
        facts_file = self.kb_path / "technical_facts" / "facts.json"
        if not facts_file.exists():
            return None

        facts_data = json.loads(facts_file.read_text())

        # Group by category
        categories: dict[str, int] = {}
        for f in facts_data:
            cat = f.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        key_items = []
        for f in facts_data[:5]:
            key_items.append(
                {
                    "id": f.get("fact_id", "?"),
                    "label": f"[{f.get('category', '?')}] {f.get('fact_id', '?')}",
                    "detail": f.get("description", "")[:100],
                }
            )

        category_summary = ", ".join(f"{k}: {v}" for k, v in categories.items())

        return StagePreview(
            stage_name="technical_author",
            display_name="Technical Facts",
            summary=f"{len(facts_data)} facts across categories: {category_summary}",
            item_count=len(facts_data),
            key_items=key_items,
            item_keys=[f.get("fact_id", str(i)) for i, f in enumerate(facts_data)],
            raw_data=facts_data,
        )

    def _preview_coordinator_plan(self) -> StagePreview | None:
        """Preview document plans output."""
        plans_dir = self.kb_path / "plans"
        if not plans_dir.exists():
            return None

        plan_files = list(plans_dir.glob("plan_*.json"))
        plans_data = []
        for pf in plan_files:
            plans_data.append(json.loads(pf.read_text()))

        key_items = []
        for p in plans_data[:5]:
            fmt = p.get("format", "?")
            sections = p.get("sections", [])
            key_items.append(
                {
                    "id": fmt,
                    "label": f"Format: {fmt}",
                    "detail": f"{len(sections)} sections",
                }
            )

        return StagePreview(
            stage_name="coordinator_plan",
            display_name="Document Plans",
            summary=f"{len(plans_data)} document plan(s)",
            item_count=len(plans_data),
            key_items=key_items,
            item_keys=[p.get("format", f"plan_{i}") for i, p in enumerate(plans_data)],
            raw_data=plans_data,
        )

    def _preview_output_generation(self) -> StagePreview | None:
        """Preview generated documents."""
        output_dir = self.kb_path / "outputs"
        if not output_dir.exists():
            return None

        generated = []
        for f in output_dir.iterdir():
            if f.is_file() and f.suffix in {".md", ".docx", ".pdf", ".pptx"}:
                size = f.stat().st_size
                generated.append(
                    {
                        "id": f.name,
                        "label": f"{f.name} ({f.suffix[1:]})",
                        "detail": f"{size / 1024:.1f} KB",
                    }
                )

        return StagePreview(
            stage_name="output_generation",
            display_name="Generated Documents",
            summary=f"{len(generated)} document(s) generated",
            item_count=len(generated),
            key_items=generated[:5],
            item_keys=[g["id"] for g in generated],
            raw_data={"files": generated, "output_dir": str(output_dir)},
        )

    # -------------------------------------------------------------------------
    # CLI review interface
    # -------------------------------------------------------------------------

    def review_stage(self, preview: StagePreview) -> StageReview:
        """Present a stage preview to the user and collect their decision.

        Returns a StageReview with the user's decision and optional feedback.
        """
        console.print()
        console.print(Panel(f"[bold]{preview.display_name}[/bold]"))
        console.print(f"[dim]{preview.summary}[/dim]")

        # Show key items table
        if preview.key_items:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Item", style="cyan", width=30)
            table.add_column("Detail", style="dim")
            for item in preview.key_items[:5]:
                table.add_row(item["label"], item["detail"])
            console.print(table)

        if preview.item_count > 5:
            console.print(f"[dim]  ... and {preview.item_count - 5} more items[/dim]")

        console.print()

        # Ask for decision
        choices = [
            "Accept (continue to next stage)",
            "Regenerate all (with feedback)",
            "Regenerate specific items",
            "Skip review for remaining stages",
        ]

        choice = self._prompt_choice(
            "What would you like to do?",
            choices,
            default="0",
        )

        if choice == "0":
            return StageReview(
                stage_name=preview.stage_name,
                decision=ReviewDecision.ACCEPT,
                items_reviewed=preview.item_count,
                items_accepted=preview.item_count,
            )
        elif choice == "1":
            # Regenerate all
            console.print()
            feedback = Prompt.ask(
                "[yellow]Feedback for regeneration[/yellow]\n"
                "Describe what to change or improve (or press Enter to continue with generic guidance)"
            )
            return StageReview(
                stage_name=preview.stage_name,
                decision=ReviewDecision.REGENERATE_ALL,
                feedback=feedback if feedback.strip() else None,
                items_reviewed=preview.item_count,
                items_accepted=0,
            )
        elif choice == "2":
            # Partial regeneration
            partial_keys = self._select_items(preview)
            console.print()
            feedback = Prompt.ask(
                "[yellow]Feedback for selected items[/yellow]\n"
                "Describe what to change about these specific items"
            )
            return StageReview(
                stage_name=preview.stage_name,
                decision=ReviewDecision.REGENERATE_PARTIAL,
                feedback=feedback if feedback.strip() else None,
                partial_keys=partial_keys,
                items_reviewed=preview.item_count,
                items_accepted=preview.item_count - len(partial_keys),
            )
        else:
            # Skip remaining
            return StageReview(
                stage_name=preview.stage_name,
                decision=ReviewDecision.SKIP,
                items_reviewed=0,
                items_accepted=0,
            )

    def _prompt_choice(self, prompt_text: str, choices: list[str], default: str) -> str:
        """Prompt user to select from numbered choices."""
        console.print(f"[yellow]{prompt_text}[/yellow]")
        for i, c in enumerate(choices):
            console.print(f"  [cyan]{i}[/cyan] {c}")
        console.print()

        while True:
            answer = console.input(
                f"[yellow]Enter choice (default: {default}): [/yellow]"
            ).strip()
            if answer == "":
                return default
            if answer.isdigit() and 0 <= int(answer) < len(choices):
                return answer
            console.print(
                f"[red]Invalid choice. Enter a number 0-{len(choices) - 1}.[/red]"
            )

    def _select_items(self, preview: StagePreview) -> list[str]:
        """Prompt user to select specific items for partial regeneration."""
        console.print()
        console.print(
            "[yellow]Select items to regenerate (comma-separated numbers or ranges):[/yellow]"
        )
        for i, item in enumerate(preview.key_items[:10]):
            console.print(f"  [cyan]{i}[/cyan]  {item['label']}")
            console.print(f"       {item['detail']}")

        if preview.item_count > 10:
            console.print(
                f"  [dim]  ... and {preview.item_count - 10} more (showing first 10)[/dim]"
            )

        console.print()
        console.print("[dim]Examples: 0,2,5  |  1-3,7  |  all[/dim]")

        while True:
            answer = console.input("[yellow]Selected items: [/yellow]").strip().lower()
            if answer == "all":
                return preview.item_keys

            keys: list[str] = []
            valid = True
            parts = answer.replace(" ", ",").split(",")

            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    range_parts = part.split("-")
                    if (
                        len(range_parts) == 2
                        and range_parts[0].isdigit()
                        and range_parts[1].isdigit()
                    ):
                        start, end = int(range_parts[0]), int(range_parts[1])
                        for idx in range(start, min(end + 1, len(preview.key_items))):
                            if idx < len(preview.key_items):
                                keys.append(preview.key_items[idx]["id"])
                    else:
                        valid = False
                elif part.isdigit():
                    idx = int(part)
                    if idx < len(preview.key_items):
                        keys.append(preview.key_items[idx]["id"])
                    else:
                        valid = False
                else:
                    valid = False

                if not valid:
                    break

            if valid and keys:
                return keys

            console.print("[red]Invalid selection. Try again.[/red]")

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def show_full_output(self, preview: StagePreview) -> None:
        """Show the full raw output of a stage for inspection."""
        console.print()
        console.print(f"[bold]Full output: {preview.display_name}[/bold]")
        console.print(
            f"[dim]File: {self._get_stage_output_path(preview.stage_name)}[/dim]"
        )
        console.print()

        if preview.format_hint == "json":
            text = json.dumps(preview.raw_data, indent=2)
            if len(text) > 3000:
                text = text[:3000] + f"\n... [truncated, {len(text) - 3000} more chars]"
            syntax = Syntax(text, "json", theme="monokai", line_numbers=True)
            console.print(syntax)
        else:
            console.print(str(preview.raw_data)[:3000])

    def _get_stage_output_path(self, stage_name: str) -> str:
        """Return the path to a stage's output file."""
        paths = {
            "git_analysis": self.kb_path / "git_analysis" / "summary.json",
            "change_filter": self.kb_path / "git_analysis" / "summary.json",
            "technical_author": self.kb_path / "technical_facts" / "facts.json",
            "coordinator_plan": self.kb_path / "plans",
            "output_generation": str(self.kb_path / "outputs"),
        }
        return str(paths.get(stage_name, "unknown"))
