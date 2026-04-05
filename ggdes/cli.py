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
    provider: Annotated[
        Optional[str], typer.Option(help="Model provider (anthropic, openai, ollama)")
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option(help="Model name (e.g., claude-3-5-sonnet-20241022)"),
    ] = None,
    api_key: Annotated[
        Optional[str],
        typer.Option(help="API key (or env var like ${ANTHROPIC_API_KEY})"),
    ] = None,
    formats: Annotated[
        Optional[str],
        typer.Option(
            help="Output formats (comma-separated: markdown,docx,pdf,pptx). Default: markdown"
        ),
    ] = None,
    focus: Annotated[
        Optional[str],
        typer.Option(
            help="Focus on specific commits (comma-separated hashes, e.g., 'abc123,def456')"
        ),
    ] = None,
    force: Annotated[bool, typer.Option(help="Force run even if locked")] = False,
    auto: Annotated[
        bool,
        typer.Option(help="Run all stages without prompting (non-interactive mode)"),
    ] = False,
    setup_only: Annotated[
        bool, typer.Option(help="Only set up worktrees, don't run analysis")
    ] = False,
) -> None:
    """Start a new analysis of git commits."""
    # Load configuration
    config, repo_path = load_config(
        cli_repo_path=repo,
        cli_provider=provider,
        cli_model_name=model,
        cli_api_key=api_key,
    )

    # Parse formats if provided
    target_formats = ["markdown"]  # Default
    if formats:
        target_formats = [fmt.strip().lower() for fmt in formats.split(",")]
        # Validate formats
        valid_formats = {"markdown", "docx", "pdf", "pptx"}
        invalid_formats = set(target_formats) - valid_formats
        if invalid_formats:
            console.print(
                f"[red]Error:[/red] Invalid format(s): {', '.join(invalid_formats)}"
            )
            console.print(f"Valid formats: {', '.join(sorted(valid_formats))}")
            raise typer.Exit(1)

    # Parse focus commits if provided
    focus_commits = None
    if focus:
        focus_commits = [c.strip() for c in focus.split(",") if c.strip()]

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
    if focus_commits:
        console.print(f"  Focus commits: {', '.join(focus_commits)}")
    console.print(f"  Feature: {feature}")
    console.print(f"  Formats: {', '.join(target_formats)}")

    # Acquire lock
    try:
        with LockContext(repo_path, analysis_id, force=force):
            # Create KB structure
            metadata = kb_manager.create_analysis(
                analysis_id=analysis_id,
                name=feature,
                repo_path=repo_path,
                commit_range=commits,
                focus_commits=focus_commits,
                prompt_version="v1.0.0",  # Use current version
                target_formats=target_formats,
            )
            console.print(
                f"[green]Created knowledge base:[/green] {kb_manager.get_analysis_path(analysis_id)}"
            )

            # Run pipeline
            from ggdes.pipeline import AnalysisPipeline

            pipeline = AnalysisPipeline(config, analysis_id)

            # Step 1: Setup worktrees (always needed)
            success = pipeline.run_stage(kb_manager.STAGE_WORKTREE_SETUP)
            if not success:
                console.print(f"\n[red]✗ Setup failed[/red]")
                raise typer.Exit(1)

            # Determine what to do next
            if setup_only:
                # User only wanted setup
                console.print(f"\n[green]✓ Setup complete:[/green] {analysis_id}")
                console.print(f"Run 'ggdes resume {analysis_id}' to run analysis later")
                return

            if not auto:
                # Interactive mode: ask user if they want to continue
                console.print("\n[bold]Setup complete. Ready to run analysis.[/bold]")
                console.print(
                    f"This will analyze the commits and generate documentation."
                )
                if not typer.confirm("Continue with analysis?"):
                    console.print(f"\n[yellow]Analysis paused.[/yellow]")
                    console.print(f"Run 'ggdes resume {analysis_id}' to continue later")
                    return

            # Step 2: Run full analysis
            console.print("\n[bold]Running analysis...[/bold]")
            success = pipeline.run_all_pending()
            if success:
                console.print(f"\n[green]✓ Analysis complete:[/green] {analysis_id}")
            else:
                console.print(
                    f"\n[yellow]⚠ Analysis incomplete:[/yellow] {analysis_id}"
                )
                console.print(f"Run 'ggdes resume {analysis_id}' to retry")
                raise typer.Exit(1)

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
        if found_metadata.focus_commits:
            console.print(f"  Focus commits: {', '.join(found_metadata.focus_commits)}")
        console.print(
            f"  Formats: {', '.join(found_metadata.target_formats) if found_metadata.target_formats else 'markdown'}"
        )
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


@app.command()
def resume(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    force: Annotated[bool, typer.Option(help="Force resume even if locked")] = False,
    stage: Annotated[
        Optional[str], typer.Option(help="Run specific stage only")
    ] = None,
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

    # Run pipeline
    from ggdes.pipeline import AnalysisPipeline

    try:
        pipeline = AnalysisPipeline(config, found_id)

        if stage:
            # Run specific stage
            console.print(f"[bold]Running stage:[/bold] {stage}")
            success = pipeline.run_stage(stage)
        else:
            # Run all pending stages
            console.print(f"[bold]Resuming analysis:[/bold] {found_id}")
            success = pipeline.run_all_pending()

        if success:
            console.print(f"\n[green]✓ Analysis updated:[/green] {found_id}")
        else:
            console.print(f"\n[yellow]⚠ Analysis incomplete:[/yellow] {found_id}")
            raise typer.Exit(1)

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
def conversations(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    agent: Annotated[
        Optional[str],
        typer.Option(
            help="Filter by agent (git_analyzer, technical_author, coordinator, markdown)"
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(help="Show raw conversation with full messages"),
    ] = False,
) -> None:
    """View stored LLM conversations for an analysis."""
    import json

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

    analysis_path = kb_manager.get_analysis_path(found_id)
    conversations_path = analysis_path / "conversations"

    if not conversations_path.exists():
        console.print(f"[yellow]No conversations found for:[/yellow] {found_id}")
        console.print("Conversations are saved during analysis execution.")
        return

    # List available conversation files
    conversation_files = []
    for conv_dir in conversations_path.iterdir():
        if conv_dir.is_dir():
            agent_name = conv_dir.name
            if agent and agent != agent_name:
                continue

            raw_file = conv_dir / "conversation_raw.json"
            summary_file = conv_dir / "conversation_summary.json"

            if raw_file.exists():
                conversation_files.append((agent_name, raw_file, "raw"))
            elif summary_file.exists():
                conversation_files.append((agent_name, summary_file, "summary"))

    if not conversation_files:
        console.print(f"[yellow]No conversation files found[/yellow]")
        return

    console.print(f"[bold]Conversations for:[/bold] {found_metadata.name}")
    console.print(f"Analysis ID: {found_id}\n")

    # Display conversations
    for agent_name, file_path, storage_type in sorted(conversation_files):
        console.print(f"[bold]{agent_name}[/bold] ({storage_type})")

        try:
            data = json.loads(file_path.read_text())

            if storage_type == "raw" and raw:
                # Show full raw conversation
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Messages: {len(data.get('messages', []))}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                console.print("\n  [dim]Messages:[/dim]")
                for i, msg in enumerate(data.get("messages", [])):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    preview = content[:150].replace("\n", " ")
                    if len(content) > 150:
                        preview += "..."
                    console.print(f"    {i + 1}. [{role}] {preview}")
            elif storage_type == "raw":
                # Show raw summary
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Messages: {len(data.get('messages', []))}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                console.print(f"  [dim]Use --raw to see full messages[/dim]")
            else:
                # Show summary
                summaries = data.get("summaries", [])
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Message count: {data.get('message_count', 0)}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                if summaries:
                    console.print(f"  Latest summary: {summaries[-1][:100]}...")

            console.print()

        except Exception as e:
            console.print(f"  [red]Error reading conversation:[/red] {e}")
            console.print()


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
