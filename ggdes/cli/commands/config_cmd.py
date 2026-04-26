"""Config command."""

from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.config import load_config


@app.command()
def config(
    show: Annotated[bool, typer.Option(help="Show current configuration")] = True,
) -> None:
    """View or edit configuration."""
    config_obj, _ = load_config()

    if show:
        console.print("[bold]Configuration:[/bold]")
        console.print(f"  [bold]Model Provider:[/bold] {config_obj.model.provider}")
        console.print(f"  [bold]Model Name:[/bold] {config_obj.model.model_name}")
        # Don't print full API key, just show if it's set
        api_key_display = (
            "set"
            if config_obj.model.api_key
            and not config_obj.model.api_key.startswith("${")
            else "not set (will use env var)"
        )
        console.print(f"  [bold]API Key:[/bold] {api_key_display}")
        console.print(f"  KB Path: {config_obj.paths.knowledge_base}")
        console.print(f"  Worktrees Path: {config_obj.paths.worktrees}")
        console.print(f"  Default Format: {config_obj.output.default_format}")
        console.print(
            f"  Semantic Diff: {config_obj.features.semantic_diff}"
        )
        console.print(f"  Auto Cleanup: {config_obj.features.auto_cleanup}")
