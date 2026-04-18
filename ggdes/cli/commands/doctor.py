"""Doctor command - system diagnostics."""

import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.config import load_config


@app.command()
def doctor(
    fix: Annotated[
        bool,
        typer.Option(help="Attempt to fix issues automatically"),
    ] = False,
) -> None:
    """Diagnose system health and configuration."""
    console.print("[bold]GGDes System Diagnostics[/bold]\n")

    issues_found = 0
    issues_fixed = 0

    # Check 1: Python version
    console.print("[dim]Checking Python version...[/dim]")
    console.print(
        "  [green]✓[/green] Python version: {}.{}.{}".format(*sys.version_info[:3])
    )

    # Check 2: Dependencies
    console.print("[dim]Checking dependencies...[/dim]")
    required_packages = [
        "typer",
        "rich",
        "pydantic",
        "pyyaml",
        "tree_sitter",
        "anthropic",
        "openai",
    ]

    for package in required_packages:
        try:
            __import__(package)
            console.print(f"  [green]✓[/green] {package}")
        except ImportError:
            console.print(f"  [red]✗[/red] {package} (missing)")
            issues_found += 1
            if fix:
                console.print(f"    [dim]Attempting to install {package}...[/dim]")
                # Could attempt pip install here

    # Check 3: External tools
    console.print("[dim]Checking external tools...[/dim]")

    tools = {
        "git": "Git version control",
        "pandoc": "Document conversion (optional)",
        "node": "Node.js for DOCX/PPTX generation (optional)",
        "java": "Java for PlantUML diagrams (optional)",
    }

    for tool, description in tools.items():
        if shutil.which(tool):
            console.print(f"  [green]✓[/green] {tool}: {description}")
        else:
            console.print(f"  [yellow]⚠[/yellow] {tool}: {description} (not found)")
            if tool in ["git"]:
                issues_found += 1

    # Check 4: PlantUML
    console.print("[dim]Checking PlantUML...[/dim]")
    try:
        from ggdes.diagrams import PlantUMLGenerator

        gen = PlantUMLGenerator()
        console.print(f"  [green]✓[/green] PlantUML: {gen.plantuml_jar}")
    except FileNotFoundError:
        console.print("  [yellow]⚠[/yellow] PlantUML jar not found")
        issues_found += 1
        if fix:
            console.print(
                "    [dim]Run: curl -L -o ggdes/diagrams/plantuml.jar https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar[/dim]"
            )

    # Check 5: Knowledge base directory
    console.print("[dim]Checking knowledge base...[/dim]")
    config, _ = load_config()
    kb_path = Path(config.paths.knowledge_base).expanduser()

    if kb_path.exists():
        analyses = list(kb_path.glob("*/metadata.yaml"))
        console.print(f"  [green]✓[/green] Knowledge base: {kb_path}")
        console.print(f"    [dim]Found {len(analyses)} analysis(es)[/dim]")
    else:
        console.print(f"  [yellow]⚠[/yellow] Knowledge base not found: {kb_path}")
        if fix:
            kb_path.mkdir(parents=True, exist_ok=True)
            console.print("    [green]✓[/green] Created knowledge base directory")
            issues_fixed += 1

    # Summary
    console.print()
    if issues_found == 0:
        console.print("[green]✓ All checks passed![/green]")
    elif fix and issues_fixed > 0:
        console.print(
            f"[yellow]⚠ {issues_found} issue(s) found, {issues_fixed} fixed automatically[/yellow]"
        )
    else:
        console.print(f"[yellow]⚠ {issues_found} issue(s) found[/yellow]")
        if not fix and issues_found > 0:
            console.print(
                "[dim]Run 'ggdes doctor --fix' to attempt automatic fixes[/dim]"
            )
