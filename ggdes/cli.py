"""CLI for GGDes."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from ggdes.config import GGDesConfig, load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.utils.lock import LockContext
from ggdes.worktree import WorktreeManager

app = typer.Typer(help="GGDes: Git-based Design Documentation Generator")
console = Console()


def generate_analysis_id(name: str, repo_path: Path, commit_range: str) -> str:
    """Generate a unique analysis ID.

    Args:
        name: User-provided name
        repo_path: Path to repository
        commit_range: Commit range

    Returns:
        Unique analysis ID
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Add hash of repo + commits for uniqueness
    hash_input = f"{repo_path}:{commit_range}:{timestamp}"
    short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    return f"{name}-{timestamp}-{short_hash}"


@app.command()
def analyze(
    feature: Annotated[str, typer.Option(help="Name for this analysis")],
    commits: Annotated[str, typer.Option(help="Git commit range (e.g., HEAD~5..HEAD)")],
    repo: Annotated[Optional[str], typer.Option(help="Path to repository")] = None,
    model: Annotated[Optional[str], typer.Option(help="LLM model to use")] = None,
    force: Annotated[bool, typer.Option(help="Force run even if locked")] = False,
    interactive: Annotated[bool, typer.Option(help="Interactive mode")] = False,
) -> None:
    """Start a new analysis of git commits."""
    # Load configuration
    config, repo_path = load_config(cli_repo_path=repo, cli_model=model)

    # Check if repo is a git repo
    git_dir = repo_path / ".git"
    if not git_dir.exists() and not (repo_path / ".git").is_dir():
        console.print(f"[red]Error:[/red] {repo_path} is not a git repository")
        raise typer.Exit(1)

    # Generate analysis ID
    analysis_id = generate_analysis_id(feature, repo_path, commits)

    # Check for existing analysis with same name
    kb_manager = KnowledgeBaseManager(config)
    for existing_id, metadata in kb_manager.list_analyses():
        if metadata.name == feature:
            console.print(
                f"[yellow]Warning:[/yellow] Analysis '{feature}' already exists: {existing_id}"
            )
            if not typer.confirm("Continue and create new analysis?"):
                console.print("Aborted.")
                raise typer.Exit(0)
            break

    console.print(f"[green]Starting analysis:[/green] {analysis_id}")
    console.print(f"  Repository: {repo_path}")
    console.print(f"  Commits: {commits}")
    console.print(f"  Feature: {feature}")

    # Acquire lock
    try:
        with LockContext(repo_path, analysis_id, force=force):
            # Create KB structure
            metadata = kb_manager.create_analysis(
                analysis_id=analysis_id,
                name=feature,
                repo_path=repo_path,
                commit_range=commits,
                prompt_version="v1.0.0",  # Use current version
            )
            console.print(
                f"[green]Created knowledge base:[/green] {kb_manager.get_analysis_path(analysis_id)}"
            )

            # Create worktrees (stub - full implementation in Phase 2)
            wt_manager = WorktreeManager(config, repo_path)
            console.print("[dim]Creating worktrees...[/dim]")

            # For Phase 1, just mark stage as completed with stub
            metadata.start_stage(kb_manager.STAGE_WORKTREE_SETUP)
            # TODO: Parse commit range, create actual worktrees
            metadata.complete_stage(kb_manager.STAGE_WORKTREE_SETUP)

            # Mark git analysis as pending
            metadata.start_stage(kb_manager.STAGE_GIT_ANALYSIS)
            console.print("[dim]Git analysis staged (Phase 2 implementation)[/dim]")

            kb_manager.save_metadata(analysis_id, metadata)

            console.print(f"\n[green]Analysis initialized:[/green] {analysis_id}")
            console.print(f"Run 'ggdes status {analysis_id}' to check progress")
            console.print(f"Run 'ggdes resume {analysis_id}' to continue (Phase 2+)")

    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status(
    analysis: Annotated[
        Optional[str], typer.Argument(help="Analysis ID or name")
    ] = None,
) -> None:
    """Show status of analyses."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    if analysis:
        # Show specific analysis
        # Try to find by full ID or by name
        found_id = None
        found_metadata = None

        for aid, metadata in kb_manager.list_analyses():
            if aid == analysis or metadata.name == analysis:
                found_id = aid
                found_metadata = metadata
                break

        if not found_metadata:
            console.print(f"[red]Analysis not found:[/red] {analysis}")
            raise typer.Exit(1)

        console.print(f"[bold]Analysis:[/bold] {found_metadata.name}")
        console.print(f"  ID: {found_id}")
        console.print(f"  Repository: {found_metadata.repo_path}")
        console.print(f"  Commits: {found_metadata.commit_range}")
        console.print(f"  Created: {found_metadata.created_at}")
        console.print(f"  Updated: {found_metadata.updated_at}")
        console.print(f"\n[bold]Stages:[/bold]")

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
            console.print(f"\n[bold]Generated Documents:[/bold]")
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
        table.add_column("Status", style="yellow")
        table.add_column("Completed", justify="right")
        table.add_column("Pending", justify="right")

        for aid, metadata in analyses:
            completed = len(metadata.get_completed_stages())
            pending = len(metadata.get_pending_stages())
            total = len(metadata.stages)

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
                status_text,
                str(completed),
                str(pending),
            )

        console.print(table)


@app.command()
def resume(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    force: Annotated[bool, typer.Option(help="Force resume even if locked")] = False,
) -> None:
    """Resume an incomplete analysis."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id = None
    found_metadata = None

    for aid, metadata in kb_manager.list_analyses():
        if aid == analysis or metadata.name == analysis:
            found_id = aid
            found_metadata = metadata
            break

    if not found_metadata:
        console.print(f"[red]Analysis not found:[/red] {analysis}")
        raise typer.Exit(1)

    # Check if can resume
    can_resume, reason = kb_manager.can_resume(found_id)
    if not can_resume:
        console.print(f"[red]Cannot resume:[/red] {reason}")
        raise typer.Exit(1)

    repo_path = Path(found_metadata.repo_path)

    # Acquire lock
    try:
        with LockContext(repo_path, found_id, force=force):
            console.print(f"[green]Resuming analysis:[/green] {found_id}")
            console.print(f"[dim]Phase 2+ implementation will continue from:[/dim]")
            for stage in found_metadata.get_pending_stages()[:3]:
                console.print(f"  - {stage}")
            console.print("[dim]... (CLI stub for Phase 1)[/dim]")

    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def cleanup(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    remove_kb: Annotated[
        bool, typer.Option(help="Also remove from knowledge base")
    ] = False,
) -> None:
    """Clean up worktrees for an analysis."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id = None
    found_metadata = None

    for aid, metadata in kb_manager.list_analyses():
        if aid == analysis or metadata.name == analysis:
            found_id = aid
            found_metadata = metadata
            break

    if not found_metadata:
        console.print(f"[red]Analysis not found:[/red] {analysis}")
        raise typer.Exit(1)

    # Clean worktrees
    wt_manager = WorktreeManager(config, Path(found_metadata.repo_path))
    wt_manager.cleanup(found_id)
    console.print(f"[green]Cleaned up worktrees for:[/green] {found_id}")

    # Optionally remove from KB
    if remove_kb:
        if typer.confirm(
            f"Remove analysis '{found_metadata.name}' from knowledge base?"
        ):
            kb_manager.delete_analysis(found_id)
            console.print(f"[green]Removed from knowledge base:[/green] {found_id}")


@app.command()
def list() -> None:
    """List all analyses (alias for status)."""
    status()


@app.command()
def config(
    show: Annotated[bool, typer.Option(help="Show current configuration")] = True,
) -> None:
    """View or edit configuration."""
    config_obj, _ = load_config()

    if show:
        console.print("[bold]Configuration:[/bold]")
        console.print(f"  Model: {config_obj.model.default}")
        console.print(f"  KB Path: {config_obj.paths.knowledge_base}")
        console.print(f"  Worktrees Path: {config_obj.paths.worktrees}")
        console.print(f"  Default Format: {config_obj.output.default_format}")
        console.print(
            f"  Dual State Analysis: {config_obj.features.dual_state_analysis}"
        )
        console.print(f"  Auto Cleanup: {config_obj.features.auto_cleanup}")


@app.command()
def tui() -> None:
    """Launch the interactive TUI."""
    from ggdes.tui import run_tui

    run_tui()


def main() -> None:
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
