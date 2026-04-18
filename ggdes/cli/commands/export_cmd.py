"""Export and archive commands."""

import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from ggdes.cli import app, console
from ggdes.cli.utils import resolve_analysis
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager


@app.command()
def export(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    output: Annotated[str, typer.Argument(help="Output file path (.json or .zip)")],
    include_diagrams: Annotated[
        bool,
        typer.Option(help="Include diagram files in export"),
    ] = True,
    include_worktrees: Annotated[
        bool,
        typer.Option(help="Include worktree files (can be large)"),
    ] = False,
) -> None:
    """Export analysis data to JSON or ZIP archive."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id, found_metadata = resolve_analysis(kb_manager, analysis)

    output_path = Path(output)

    try:
        analysis_path = kb_manager.get_analysis_path(found_id)

        # Collect all analysis data
        export_data: dict[str, Any] = {
            "metadata": found_metadata.model_dump(),
            "analysis_id": found_id,
            "exported_at": datetime.now().isoformat(),
            "data": {},
        }

        # Load git analysis
        git_summary_path = analysis_path / "git_analysis" / "summary.json"
        if git_summary_path.exists():
            export_data["data"]["git_analysis"] = json.loads(
                git_summary_path.read_text()
            )

        # Load technical facts
        facts_dir = analysis_path / "technical_facts"
        if facts_dir.exists():
            facts: list[Any] = []
            for fact_file in facts_dir.glob("*.json"):
                facts.append(json.loads(fact_file.read_text()))
            export_data["data"]["technical_facts"] = facts

        # Load document plans
        plans_dir = analysis_path / "plans"
        if plans_dir.exists():
            plans: dict[str, Any] = {}
            for plan_file in plans_dir.glob("*.json"):
                plans[plan_file.stem] = json.loads(plan_file.read_text())
            export_data["data"]["document_plans"] = plans

        # Export based on file extension
        if output_path.suffix == ".zip":
            # Create ZIP archive
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Add metadata JSON
                zf.writestr("analysis.json", json.dumps(export_data, indent=2))

                # Add all files from analysis directory
                for file_path in analysis_path.rglob("*"):
                    if file_path.is_file():
                        # Skip worktrees if not requested
                        if not include_worktrees and "worktrees" in str(file_path):
                            continue
                        arcname = file_path.relative_to(analysis_path)
                        zf.write(file_path, arcname)

                # Add diagram files if requested
                if include_diagrams and found_id is not None:
                    diagrams_dir = Path(found_metadata.repo_path) / "docs" / "diagrams"
                    if diagrams_dir.exists():
                        for diag_file in diagrams_dir.glob("*.png"):
                            if found_id in diag_file.name:
                                zf.write(diag_file, f"diagrams/{diag_file.name}")

            console.print(f"[green]✓ Analysis exported to ZIP:[/green] {output_path}")

        else:
            # Export as JSON
            output_path.write_text(json.dumps(export_data, indent=2))
            console.print(f"[green]✓ Analysis exported to JSON:[/green] {output_path}")

    except Exception as e:
        console.print(f"[red]Export failed:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1) from e


@app.command()
def archive(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    export_first: Annotated[
        bool,
        typer.Option(help="Export analysis before archiving"),
    ] = True,
    keep_days: Annotated[
        int,
        typer.Option(help="Keep analyses newer than this many days"),
    ] = 30,
) -> None:
    """Archive an analysis (export and remove from active list)."""
    from ggdes.worktree import WorktreeManager

    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id, found_metadata = resolve_analysis(kb_manager, analysis)

    # Check if analysis is too recent
    created_at = found_metadata.created_at
    if isinstance(created_at, str):
        analysis_date = datetime.fromisoformat(created_at)
    else:
        analysis_date = created_at
    cutoff_date = datetime.now() - timedelta(days=keep_days)

    if analysis_date > cutoff_date:
        console.print(
            f"[yellow]Warning:[/yellow] Analysis is newer than {keep_days} days"
        )
        if not typer.confirm("Archive anyway?"):
            console.print("[dim]Archive cancelled[/dim]")
            return

    try:
        # Export before archiving if requested
        if export_first:
            archive_dir = Path(config.paths.knowledge_base) / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            export_path = archive_dir / f"{found_id}-{timestamp}.zip"

            # Run export
            console.print("[dim]Exporting to archive...[/dim]")

            # Temporarily redirect to export function
            export_cmd = f"ggdes export {found_id} {export_path}"
            console.print(f"[dim]Export command: {export_cmd}[/dim]")

        # Remove analysis from KB
        kb_manager.delete_analysis(found_id)
        console.print(f"[green]✓ Analysis archived:[/green] {found_id}")

        # Clean up worktrees
        wt_manager = WorktreeManager(config, Path(found_metadata.repo_path))
        wt_manager.cleanup(found_id)

    except Exception as e:
        console.print(f"[red]Archive failed:[/red] {e}")
        raise typer.Exit(1) from e
