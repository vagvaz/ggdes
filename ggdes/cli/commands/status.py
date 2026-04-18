"""Status and list commands."""

from typing import Annotated

import typer
from rich.table import Table

from ggdes.cli import app, console
from ggdes.cli.utils import resolve_analysis
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus


@app.command()
def status(
    analysis: Annotated[str | None, typer.Argument(help="Analysis ID or name")] = None,
) -> None:
    """Show status of analyses."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    if analysis:
        # Show specific analysis
        found_id, found_metadata = resolve_analysis(kb_manager, analysis)

        console.print(f"[bold]Analysis:[/bold] {found_metadata.name}")
        console.print(f"  ID: {found_id}")
        console.print(f"  Repository: {found_metadata.repo_path}")
        console.print(f"  Commits: {found_metadata.commit_range}")
        if found_metadata.focus_commits:
            console.print(f"  Focus commits: {', '.join(found_metadata.focus_commits)}")
        console.print(
            f"  Formats: {', '.join(found_metadata.target_formats) if found_metadata.target_formats else 'markdown'}"
        )
        console.print(f"  Created: {found_metadata.created_at}")
        console.print(f"  Updated: {found_metadata.updated_at}")
        console.print("\n[bold]Stages:[/bold]")

        for stage_name, stage in found_metadata.stages.items():
            status_color = {
                StageStatus.PENDING: "dim",
                StageStatus.IN_PROGRESS: "yellow",
                StageStatus.COMPLETED: "green",
                StageStatus.FAILED: "red",
                StageStatus.SKIPPED: "blue",
            }.get(stage.status, "white")

            console.print(
                f"  [{status_color}]{stage.status.value:12}[/{status_color}] {stage_name}"
            )

        if found_metadata.documents:
            console.print("\n[bold]Generated Documents:[/bold]")
            for doc in found_metadata.documents:
                if doc.generated_at:
                    console.print(f"  [green]{doc.format}[/green]: {doc.path}")
                else:
                    console.print(f"  [dim]{doc.format}[/dim]: pending")
    else:
        # List all analyses
        analyses = kb_manager.list_analyses()

        if not analyses:
            console.print(
                "[dim]No analyses found. Run 'ggdes analyze' to create one.[/dim]"
            )
            return

        table = Table(title="Analyses")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Repository")
        table.add_column("Formats")
        table.add_column("Status", style="yellow")
        table.add_column("Completed", justify="right")
        table.add_column("Pending", justify="right")

        for aid, metadata in analyses:
            completed = len(metadata.get_completed_stages())
            pending = len(metadata.get_pending_stages())
            total = len(metadata.stages)
            target_formats = metadata.target_formats or ["markdown"]
            formats_str = ", ".join(target_formats)

            if completed == total:
                status_text = "[green]complete[/green]"
            elif completed > 0:
                status_text = f"[yellow]in progress ({completed}/{total})[/yellow]"
            else:
                status_text = "[dim]initialized[/dim]"

            # Truncate repo path for display
            repo_display = str(metadata.repo_path)
            if len(repo_display) > 40:
                repo_display = "..." + repo_display[-37:]

            table.add_row(
                aid[:40] + "..." if len(aid) > 40 else aid,
                metadata.name,
                repo_display,
                formats_str,
                status_text,
                str(completed),
                str(pending),
            )

        console.print(table)


@app.command(name="list")
def list_analyses() -> None:
    """List all analyses (alias for status)."""
    status()
