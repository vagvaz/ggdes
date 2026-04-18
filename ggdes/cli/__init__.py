"""CLI for GGDes."""

import typer
from rich.console import Console

app = typer.Typer(help="GGDes: Git-based Design Documentation Generator")
console = Console()

# Import commands (they register themselves with app via @app.command())
# ruff: noqa: E402, F401, F403
from ggdes.cli.commands.analyze import *
from ggdes.cli.commands.compare import *
from ggdes.cli.commands.config_cmd import *
from ggdes.cli.commands.doctor import *
from ggdes.cli.commands.export_cmd import *
from ggdes.cli.commands.manage import *
from ggdes.cli.commands.resume import *
from ggdes.cli.commands.server import *
from ggdes.cli.commands.status import *


@app.callback(invoke_without_command=True)
def version_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", is_flag=True, help="Show version"),
) -> None:
    """Show version information."""
    if version:
        from ggdes.cli.utils import _get_version
        console.print(f"[bold]ggdes[/bold] version [cyan]{_get_version()}[/cyan]")
        raise typer.Exit()


def main() -> None:
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
