"""Compare command."""

from pathlib import Path
from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager


@app.command()
def compare(
    analysis1: Annotated[str, typer.Argument(help="First analysis ID or name")],
    analysis2: Annotated[str, typer.Argument(help="Second analysis ID or name")],
    output: Annotated[
        str | None,
        typer.Option(help="Export comparison to JSON file"),
    ] = None,
) -> None:
    """Compare two analyses side-by-side."""
    from ggdes.comparison import AnalysisComparator, export_comparison, print_comparison

    config, _ = load_config()
    comparator = AnalysisComparator(config)

    try:
        # Resolve analysis IDs
        kb_manager = KnowledgeBaseManager(config)

        resolved_id1 = None
        resolved_id2 = None

        for aid, metadata in kb_manager.list_analyses():
            if aid == analysis1 or metadata.name == analysis1:
                resolved_id1 = aid
            if aid == analysis2 or metadata.name == analysis2:
                resolved_id2 = aid

        if not resolved_id1:
            console.print(f"[red]Analysis not found:[/red] {analysis1}")
            raise typer.Exit(1)

        if not resolved_id2:
            console.print(f"[red]Analysis not found:[/red] {analysis2}")
            raise typer.Exit(1)

        # Perform comparison
        result = comparator.compare(resolved_id1, resolved_id2)

        # Print comparison
        print_comparison(result)

        # Export if requested
        if output:
            output_path = Path(output)
            export_comparison(result, output_path)
            console.print(f"\n[green]✓ Comparison exported to:[/green] {output_path}")

    except Exception as e:
        console.print(f"[red]Comparison failed:[/red] {e}")
        raise typer.Exit(1) from e
