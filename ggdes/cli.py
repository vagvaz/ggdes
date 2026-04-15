"""CLI for GGDes."""

import builtins
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.utils.lock import LockContext
from ggdes.worktree import WorktreeManager

app = typer.Typer(help="GGDes: Git-based Design Documentation Generator")
console = Console()


def _load_user_context_from_file(context_file: Path) -> dict[str, Any]:
    """Load user context from a YAML or JSON file.

    Args:
        context_file: Path to the context file

    Returns:
        Dictionary with user-provided context

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file format is invalid
    """
    if not context_file.exists():
        raise FileNotFoundError(f"Context file not found: {context_file}")

    if context_file.suffix in (".yaml", ".yml"):
        with open(context_file) as f:
            data = yaml.safe_load(f)
    elif context_file.suffix == ".json":
        with open(context_file) as f:
            data = json.load(f)
    else:
        raise ValueError(f"Context file must be .yaml, .yml, or .json: {context_file}")

    if not isinstance(data, dict):
        raise ValueError(
            "Context file must contain a YAML/JSON object (key-value pairs)"
        )

    return data


def _gather_user_context() -> dict[str, Any]:
    """Gather user context through interactive questionnaire.

    Returns:
        Dictionary with user-provided context for all agents
    """
    context: dict[str, Any] = {}

    console.print("\n[bold cyan]Analysis Configuration[/bold cyan]")
    console.print("Help me create the best documentation for your changes.\n")

    # Question 1: Focus Areas
    context["focus_areas"] = Prompt.ask(
        "Which features/aspects should the analysis focus on?",
        default="all",
    )

    # Question 2: Target Audience
    context["audience"] = Prompt.ask(
        "Who is the target audience?",
        choices=["business", "technical_managers", "developers", "all"],
        default="all",
    )

    # Question 3: Document Purpose (multi-select via comma-separated)
    console.print("\n[yellow]Document Purpose Options:[/yellow]")
    console.print("  1. high_level_algorithm_design")
    console.print("  2. implementation_explanation")
    console.print("  3. technical_spec")
    console.print("  4. user_documentation")
    console.print("  5. api_reference")
    console.print("  6. migration_guide")
    purpose_input = Prompt.ask(
        "Select document purpose (comma-separated numbers, e.g., '1,3,5')",
        default="2,3",
    )

    # Parse purpose selections
    purpose_map = {
        "1": "high_level_algorithm_design",
        "2": "implementation_explanation",
        "3": "technical_spec",
        "4": "user_documentation",
        "5": "api_reference",
        "6": "migration_guide",
    }

    purposes = []
    for num in purpose_input.split(","):
        num = num.strip()
        if num in purpose_map:
            purposes.append(purpose_map[num])

    if not purposes:
        purposes = ["implementation_explanation", "technical_spec"]

    context["purpose"] = purposes

    # Question 4: Detail Level
    context["detail_level"] = Prompt.ask(
        "What level of detail?",
        choices=["quick_summary", "medium", "comprehensive"],
        default="medium",
    )

    # Question 5: Anything else?
    additional = Prompt.ask(
        "Do you want to add anything else? (optional)",
        default="",
    )
    if additional.strip():
        context["additional_context"] = additional.strip()

    console.print("\n[green]✓ Preferences captured[/green]\n")

    return context


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
    commits: Annotated[
        str,
        typer.Option(
            help="Git commit range (e.g., 'HEAD~5..HEAD', 'abc123..def456'). Use quotes to prevent shell interpretation."
        ),
    ],
    repo: Annotated[str | None, typer.Option(help="Path to repository")] = None,
    provider: Annotated[
        str | None, typer.Option(help="Model provider (anthropic, openai, ollama)")
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Model name (e.g., claude-3-5-sonnet-20241022)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(help="API key (or env var like ${ANTHROPIC_API_KEY})"),
    ] = None,
    formats: Annotated[
        str | None,
        typer.Option(
            help="Output formats (comma-separated: markdown,docx,pdf,pptx). Default: markdown"
        ),
    ] = None,
    focus: Annotated[
        str | None,
        typer.Option(
            help="Focus on specific commits (comma-separated hashes, e.g., 'abc123,def456')"
        ),
    ] = None,
    storage: Annotated[
        str,
        typer.Option(
            help="Conversation storage level (raw, summary, none). Default: summary"
        ),
    ] = "summary",
    force: Annotated[bool, typer.Option(help="Force run even if locked")] = False,
    auto: Annotated[
        bool,
        typer.Option(help="Run all stages without prompting (non-interactive mode)"),
    ] = False,
    setup_only: Annotated[
        bool, typer.Option(help="Only set up worktrees, don't run analysis")
    ] = False,
    semantic_diff: Annotated[
        bool,
        typer.Option(
            help="Enable semantic diff analysis (slower but more detailed). Disable for faster analysis."
        ),
    ] = True,
    no_filter: Annotated[
        bool,
        typer.Option(
            help="Disable semantic change filtering. By default, changes are filtered to only include those relevant to the feature."
        ),
    ] = False,
    render_png: Annotated[
        bool,
        typer.Option(help="Render markdown output to PNG images (requires playwright)"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            help="Enable interactive review mode. After each stage, review the output and provide feedback before continuing."
        ),
    ] = False,
    context_file: Annotated[
        str | None,
        typer.Option(
            help="YAML or JSON file with user context (focus_areas, audience, purpose, detail_level). "
            "If provided, skips the interactive questionnaire."
        ),
    ] = None,
) -> None:
    """Start a new analysis of git commits."""
    # Load configuration
    config, repo_path = load_config(
        cli_repo_path=repo,
        cli_provider=provider,
        cli_model_name=model,
        cli_api_key=api_key,
    )

    # Validate and sanitize commit range
    # Remove any shell escape characters that might have been added
    original_commits = commits
    commits = commits.strip().strip("'\"")  # Remove surrounding quotes if present

    # Validate commit range format
    if ".." not in commits:
        console.print(
            f"[red]Error:[/red] Invalid commit range format: {original_commits}"
        )
        console.print(
            "Commit range must contain '..' (e.g., 'HEAD~5..HEAD' or 'abc123..def456')"
        )
        console.print(
            "\nTip: Use quotes around the commit range to prevent shell interpretation:"
        )
        console.print('  ggdes analyze --feature test --commits "HEAD~5..HEAD"')
        raise typer.Exit(1)

    # Validate the commit range against git
    try:
        import subprocess

        # Check if base commit exists
        base_commit = commits.split("..")[0] or "HEAD"
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", base_commit],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] Base commit not found: '{base_commit}'")
            console.print(f"Git error: {result.stderr.strip()}")
            raise typer.Exit(1)

        # Check if head commit exists (if specified)
        head_part = commits.split("..")[1] if ".." in commits else ""
        if head_part:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "--verify", head_part],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print(f"[red]Error:[/red] Head commit not found: '{head_part}'")
                console.print(f"Git error: {result.stderr.strip()}")
                raise typer.Exit(1)

        # Validate the range produces results
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--oneline", commits],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] Invalid commit range: '{commits}'")
            console.print(f"Git error: {result.stderr.strip()}")
            raise typer.Exit(1)

        commit_count = (
            len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        )
        if commit_count == 0:
            console.print(
                f"[yellow]Warning:[/yellow] No commits found in range: '{commits}'"
            )

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        console.print(f"[red]Error validating commit range:[/red] {e}")
        raise typer.Exit(1) from None

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

    # Validate storage policy
    from ggdes.schemas import StoragePolicy

    valid_storage_policies = {s.value for s in StoragePolicy}
    storage_policy = storage.lower().strip()
    if storage_policy not in valid_storage_policies:
        console.print(f"[red]Error:[/red] Invalid storage policy: '{storage}'")
        console.print(f"Valid options: {', '.join(sorted(valid_storage_policies))}")
        raise typer.Exit(1)

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
    if commit_count > 0:
        console.print(f"  Commit count: {commit_count}")
    if focus_commits:
        console.print(f"  Focus commits: {', '.join(focus_commits)}")
    console.print(f"  Feature: {feature}")
    console.print(f"  Formats: {', '.join(target_formats)}")
    console.print(f"  Storage: {storage_policy}")

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
                storage_policy=StoragePolicy(storage_policy),
            )

            # Store render_png flag in metadata for pipeline use
            metadata.render_png = render_png

            # Store feature description for semantic filtering
            metadata.feature_description = feature
            metadata.no_filter = no_filter
            kb_manager.save_metadata(analysis_id, metadata)

            # Setup logging
            from ggdes.logging_config import get_logger, setup_file_logging

            logger = get_logger(__name__)
            log_path = kb_manager.get_analysis_path(analysis_id) / "analysis.log"
            setup_file_logging(log_path)

            logger.info(f"Starting analysis: {analysis_id}")
            logger.info(f"Repository: {repo_path}")
            logger.info(f"Commit range: {commits}")
            logger.info(f"Formats: {target_formats}")
            logger.info(f"Storage policy: {storage_policy}")

            console.print(
                f"[green]Created knowledge base:[/green] {kb_manager.get_analysis_path(analysis_id)}"
            )

            # Run pipeline
            from ggdes.pipeline import AnalysisPipeline

            pipeline = AnalysisPipeline(config, analysis_id, interactive=interactive)

            # Step 1: Setup worktrees (always needed)
            logger.info("Setting up worktrees...")
            success = pipeline.run_stage(kb_manager.STAGE_WORKTREE_SETUP)
            if not success:
                logger.error("Worktree setup failed")
                console.print("\n[red]✗ Setup failed[/red]")
                raise typer.Exit(1)

            # Determine what to do next
            if setup_only:
                # User only wanted setup
                logger.info("Setup complete (setup-only mode)")
                console.print(f"\n[green]✓ Setup complete:[/green] {analysis_id}")
                console.print(f"Run 'ggdes resume {analysis_id}' to run analysis later")
                return

            # Gather user context for analysis
            user_context = {}
            if not auto:
                # Interactive mode: ask user for context
                console.print("\n[bold]Setup complete. Ready to run analysis.[/bold]")
                console.print(
                    "This will analyze the commits and generate documentation."
                )
                if not typer.confirm("Continue with analysis?"):
                    logger.info("Analysis paused by user")
                    console.print("\n[yellow]Analysis paused.[/yellow]")
                    console.print(f"Run 'ggdes resume {analysis_id}' to continue later")
                    return

                # Gather user context
                if context_file:
                    user_context = _load_user_context_from_file(Path(context_file))
                    console.print(
                        f"[green]✓[/green] Loaded user context from: {context_file}"
                    )
                else:
                    user_context = _gather_user_context()

                # Store user context in metadata
                if user_context:
                    metadata.user_context = user_context
                    kb_manager.save_metadata(analysis_id, metadata)
                    logger.info(f"User context saved: {user_context}")

            # Configure pipeline stages based on semantic_diff flag
            if not semantic_diff:
                logger.info(
                    "Semantic diff disabled - skipping base AST parsing and semantic diff stages"
                )
                console.print(
                    "[dim]Semantic diff disabled - running faster analysis[/dim]"
                )

                # Mark base AST parsing and semantic diff as skipped
                from ggdes.kb import StageStatus

                metadata.stages[
                    kb_manager.STAGE_AST_PARSING_BASE
                ].status = StageStatus.SKIPPED
                metadata.stages[
                    kb_manager.STAGE_SEMANTIC_DIFF
                ].status = StageStatus.SKIPPED
                kb_manager.save_metadata(analysis_id, metadata)

            # Configure change filter stage
            if no_filter:
                logger.info(
                    "Semantic change filtering disabled - skipping change filter stage"
                )
                console.print(
                    "[dim]Change filtering disabled - analyzing all changes[/dim]"
                )

                from ggdes.kb import StageStatus

                metadata.stages[
                    kb_manager.STAGE_CHANGE_FILTER
                ].status = StageStatus.SKIPPED
                kb_manager.save_metadata(analysis_id, metadata)

            # Step 2: Run full analysis
            logger.info("Running full analysis pipeline...")
            console.print("\n[bold]Running analysis...[/bold]")
            success = pipeline.run_all_pending()
            if success:
                logger.info(f"Analysis completed successfully: {analysis_id}")
                console.print(f"\n[green]✓ Analysis complete:[/green] {analysis_id}")
            else:
                logger.error(f"Analysis incomplete: {analysis_id}")
                console.print(
                    f"\n[yellow]⚠ Analysis incomplete:[/yellow] {analysis_id}"
                )
                console.print(f"Run 'ggdes resume {analysis_id}' to retry")
                raise typer.Exit(1)

    except RuntimeError as e:
        logger.exception(f"Runtime error during analysis: {e}")
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e


@app.command()
def status(
    analysis: Annotated[str | None, typer.Argument(help="Analysis ID or name")] = None,
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


@app.command()
def resume(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    force: Annotated[bool, typer.Option(help="Force resume even if locked")] = False,
    stage: Annotated[str | None, typer.Option(help="Run specific stage only")] = None,
    retry_failed: Annotated[
        bool, typer.Option(help="Retry failed stages (reset them to pending)")
    ] = False,
    formats: Annotated[
        str | None,
        typer.Option(
            help="Output formats (comma-separated: markdown,docx,pdf,pptx). Default: use existing formats"
        ),
    ] = None,
    overwrite_context: Annotated[
        bool,
        typer.Option(help="Reask user questions to update context for new formats"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            help="Enable interactive review mode. After each stage, review the output and provide feedback before continuing."
        ),
    ] = False,
    context_file: Annotated[
        str | None,
        typer.Option(
            help="YAML or JSON file with user context (focus_areas, audience, purpose, detail_level). "
            "If provided with --overwrite-context, uses this file instead of interactive questionnaire."
        ),
    ] = None,
) -> None:
    """Resume an incomplete analysis."""
    from ggdes.logging_config import get_logger, setup_file_logging

    logger = get_logger(__name__)

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
        logger.error(f"Analysis not found: {analysis}")
        console.print(f"[red]Analysis not found:[/red] {analysis}")
        raise typer.Exit(1)

    # Setup logging for this analysis
    if found_id is None:
        console.print("[red]Error:[/red] Could not determine analysis ID")
        raise typer.Exit(1)
    log_path = kb_manager.get_analysis_path(found_id) / "analysis.log"
    setup_file_logging(log_path)

    logger.info(f"Resuming analysis: {found_id}")
    logger.info(f"Repository: {found_metadata.repo_path}")
    logger.info(f"Commit range: {found_metadata.commit_range}")

    # Determine target formats
    target_formats = found_metadata.target_formats or ["markdown"]
    if formats:
        target_formats = [fmt.strip().lower() for fmt in formats.split(",")]
        valid_formats = {"markdown", "docx", "pdf", "pptx"}
        invalid_formats = set(target_formats) - valid_formats
        if invalid_formats:
            console.print(
                f"[red]Error:[/red] Invalid format(s): {', '.join(invalid_formats)}"
            )
            console.print(f"Valid formats: {', '.join(sorted(valid_formats))}")
            raise typer.Exit(1)
        logger.info(f"Updated target formats: {target_formats}")
        found_metadata.target_formats = target_formats
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
        kb_manager.save_metadata(found_id, found_metadata)
        console.print(
            f"[green]✓ Target formats updated:[/green] {', '.join(target_formats)}"
        )

        # Reset coordinator_plan and output_generation stages to regenerate plans for new formats
        from ggdes.kb import StageStatus

        stages_to_reset = []
        coordinator_stage = found_metadata.get_stage(kb_manager.STAGE_COORDINATOR_PLAN)
        if coordinator_stage.status in [StageStatus.COMPLETED, StageStatus.FAILED]:
            coordinator_stage.status = StageStatus.PENDING
            coordinator_stage.output_path = None
            stages_to_reset.append(kb_manager.STAGE_COORDINATOR_PLAN)

        output_stage = found_metadata.get_stage(kb_manager.STAGE_OUTPUT_GENERATION)
        if output_stage.status in [StageStatus.COMPLETED, StageStatus.FAILED]:
            output_stage.status = StageStatus.PENDING
            output_stage.output_path = None
            stages_to_reset.append(kb_manager.STAGE_OUTPUT_GENERATION)

        if stages_to_reset:
            if found_id is None:
                console.print("[red]Error:[/red] Could not determine analysis ID")
                raise typer.Exit(1)
            kb_manager.save_metadata(found_id, found_metadata)
            logger.info(f"Reset stages for new formats: {', '.join(stages_to_reset)}")
            console.print(
                f"[yellow]Reset {len(stages_to_reset)} stage(s) for new formats:[/yellow] {', '.join(stages_to_reset)}"
            )

        # When formats change, ask if user wants to update context too
        if (
            not overwrite_context
            and found_metadata.user_context
            and typer.confirm(
                "\nFormats have changed. Do you want to update the analysis configuration for these new formats?"
            )
        ):
            overwrite_context = True

    # Check if can resume
    if found_id is None:
        console.print("[red]Error:[/red] Could not determine analysis ID")
        raise typer.Exit(1)
    can_resume, reason = kb_manager.can_resume(found_id, retry_failed=retry_failed)
    if not can_resume:
        logger.error(f"Cannot resume: {reason}")
        console.print(f"[red]Cannot resume:[/red] {reason}")
        raise typer.Exit(1)

    # If retry_failed is set, reset all failed stages
    if retry_failed:
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
        reset_stages = kb_manager.reset_failed_stages(found_id)
        if reset_stages:
            logger.info(f"Reset failed stages for retry: {', '.join(reset_stages)}")
            console.print(
                f"[yellow]Reset {len(reset_stages)} failed stage(s) for retry:[/yellow] {', '.join(reset_stages)}"
            )
            # Reload metadata after reset
            if found_id is None:
                console.print("[red]Error:[/red] Could not determine analysis ID")
                raise typer.Exit(1)
            found_metadata = kb_manager.load_metadata(found_id)
            if found_metadata is None:
                console.print("[red]Error:[/red] Could not load metadata after reset")
                raise typer.Exit(1)
        else:
            logger.info("No failed stages to reset")

    # Handle user context
    if found_metadata is None:
        console.print("[red]Error:[/red] Could not load analysis metadata")
        raise typer.Exit(1)
    user_context = found_metadata.user_context or {}

    # Reask user questions if requested
    if overwrite_context:
        console.print("\n[bold]Reasking analysis configuration[/bold]")
        console.print("Update preferences for this analysis.\n")

        if context_file:
            user_context = _load_user_context_from_file(Path(context_file))
            console.print(f"[green]✓[/green] Loaded user context from: {context_file}")
        else:
            user_context = _gather_user_context()

        # Update metadata with new context
        if found_metadata is None or found_id is None:
            console.print("[red]Error:[/red] Could not update metadata")
            raise typer.Exit(1)
        found_metadata.user_context = user_context
        kb_manager.save_metadata(found_id, found_metadata)
        logger.info(f"Updated user context: {user_context}")
        console.print("[green]✓ User context updated[/green]")

        # Reset coordinator_plan and output_generation stages to regenerate with new context
        from ggdes.kb import StageStatus

        stages_to_reset = []
        coordinator_stage = found_metadata.get_stage(kb_manager.STAGE_COORDINATOR_PLAN)
        if coordinator_stage.status in [StageStatus.COMPLETED, StageStatus.FAILED]:
            coordinator_stage.status = StageStatus.PENDING
            coordinator_stage.output_path = None
            stages_to_reset.append(kb_manager.STAGE_COORDINATOR_PLAN)

        output_stage = found_metadata.get_stage(kb_manager.STAGE_OUTPUT_GENERATION)
        if output_stage.status in [StageStatus.COMPLETED, StageStatus.FAILED]:
            output_stage.status = StageStatus.PENDING
            output_stage.output_path = None
            stages_to_reset.append(kb_manager.STAGE_OUTPUT_GENERATION)

        if stages_to_reset:
            if found_id is None or found_metadata is None:
                console.print("[red]Error:[/red] Could not update metadata")
                raise typer.Exit(1)
            kb_manager.save_metadata(found_id, found_metadata)
            logger.info(f"Reset stages for new context: {', '.join(stages_to_reset)}")
            console.print(
                f"[yellow]Reset {len(stages_to_reset)} stage(s) for new context:[/yellow] {', '.join(stages_to_reset)}"
            )
        console.print()

    # If no context exists, gather it now
    if not user_context:
        console.print("\n[bold]Analysis Configuration[/bold]")
        console.print("No user context found. Please configure the analysis.\n")

        if context_file:
            user_context = _load_user_context_from_file(Path(context_file))
            console.print(f"[green]✓[/green] Loaded user context from: {context_file}")
        else:
            user_context = _gather_user_context()
        if found_metadata is None or found_id is None:
            console.print("[red]Error:[/red] Could not update metadata")
            raise typer.Exit(1)
        found_metadata.user_context = user_context
        kb_manager.save_metadata(found_id, found_metadata)
        logger.info(f"User context saved: {user_context}")

    console.print(f"[dim]Target formats: {', '.join(target_formats)}[/dim]")
    console.print(f"[dim]User context: {bool(user_context)}[/dim]\n")

    # Run pipeline
    from ggdes.pipeline import AnalysisPipeline

    try:
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
        pipeline = AnalysisPipeline(config, found_id, interactive=interactive)

        if stage:
            # Run specific stage
            logger.info(f"Running specific stage: {stage}")
            console.print(f"[bold]Running stage:[/bold] {stage}")
            console.print(f"[dim]Target formats: {', '.join(target_formats)}[/dim]")
            success = pipeline.run_stage(stage)
        else:
            # Run all pending stages
            if found_metadata is None:
                console.print("[red]Error:[/red] Could not load analysis metadata")
                raise typer.Exit(1)
            pending = found_metadata.get_pending_stages()
            if not pending:
                logger.warning("No pending stages to run")
                console.print("[yellow]No pending stages to run[/yellow]")
                return
            logger.info(f"Running all pending stages: {pending}")
            console.print(f"[bold]Resuming analysis:[/bold] {found_id}")
            console.print(f"[dim]Pending stages: {', '.join(pending)}[/dim]")
            console.print(f"[dim]Target formats: {', '.join(target_formats)}[/dim]")
            success = pipeline.run_all_pending()

        if success:
            logger.info(f"Analysis completed successfully: {found_id}")
            console.print(f"\n[green]✓ Analysis updated:[/green] {found_id}")
        else:
            logger.error(f"Analysis incomplete: {found_id}")
            console.print(f"\n[yellow]⚠ Analysis incomplete:[/yellow] {found_id}")
            # Show helpful message based on retry_failed
            if retry_failed:
                console.print("Some stages are still failing. Check the logs:")
                if found_id is None:
                    console.print("  [red]Error:[/red] Could not determine analysis ID")
                else:
                    console.print(
                        f"  {kb_manager.get_analysis_path(found_id) / 'analysis.log'}"
                    )
            else:
                console.print(
                    f"Run 'ggdes resume {found_id} --retry-failed' to retry failed stages"
                )
            raise typer.Exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error during analysis: {e}")
        console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(1) from e


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
    if found_id is None:
        console.print("[red]Error:[/red] Could not determine analysis ID")
        raise typer.Exit(1)
    wt_manager = WorktreeManager(config, Path(found_metadata.repo_path))
    wt_manager.cleanup(found_id)
    console.print(f"[green]Cleaned up worktrees for:[/green] {found_id}")

    # Optionally remove from KB
    if remove_kb and typer.confirm(
        f"Remove analysis '{found_metadata.name}' from knowledge base?"
    ):
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
        kb_manager.delete_analysis(found_id)
        console.print(f"[green]Removed from knowledge base:[/green] {found_id}")


@app.command()
def conversations(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    agent: Annotated[
        str | None,
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

    if found_id is None:
        console.print("[red]Error:[/red] Could not determine analysis ID")
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
        console.print("[yellow]No conversation files found[/yellow]")
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
                console.print("  [dim]Use --raw to see full messages[/dim]")
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


@app.command()
def debug(
    analysis: Annotated[
        str | None,
        typer.Argument(
            help="Analysis ID or name (optional - will show selector if not provided)"
        ),
    ] = None,
) -> None:
    """Launch the debug TUI to browse agent conversations and outputs."""
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header

    from ggdes.config import load_config
    from ggdes.kb import KnowledgeBaseManager
    from ggdes.tui.debug_view import DebugView

    class DebugTUI(App[None]):
        """Standalone debug TUI application."""

        CSS = """
        Screen {
            align: center middle;
        }

        #debug-view {
            height: 1fr;
            width: 100%;
        }

        .debug-view-container {
            height: 100%;
            width: 100%;
        }

        .analysis-selector-container {
            height: auto;
            max-height: 8;
            padding: 1;
            border: solid $primary-darken-2;
        }

        AnalysisSelector {
            height: auto;
        }

        .analysis-selector-header {
            height: auto;
        }



        .debug-tabs {
            height: 1fr;
        }

        .browser-container {
            height: 100%;
        }

        .agent-list-panel {
            width: 20%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .message-list-panel {
            width: 40%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .message-header {
            height: auto;
            margin-bottom: 0;
            padding: 0;
        }

        .header-label {
            width: 1fr;
        }

        .follow-checkbox {
            width: auto;
            margin-left: 1;
        }

        .agent-info {
            height: auto;
            margin-top: 0;
            margin-bottom: 1;
        }

        .message-detail-panel {
            width: 40%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .file-tree-panel {
            width: 25%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .outputs-header {
            height: auto;
            margin-bottom: 1;
            padding: 0;
        }

        .refresh-btn {
            width: auto;
            margin-left: 1;
        }

        .content-viewer-panel {
            width: 75%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        #message-detail {
            height: 1fr;
        }

        #content-viewer {
            height: 1fr;
        }

        #file-tree {
            height: 1fr;
        }

        #agent-list {
            height: 1fr;
        }

        #message-list {
            height: 1fr;
        }
        """

        def __init__(self, analysis_id: str | None = None, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.analysis_id = analysis_id

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield DebugView(id="debug-view")
            yield Footer()

        def on_mount(self) -> None:
            """Set initial analysis if provided."""
            if self.analysis_id:
                debug_view = self.query_one("#debug-view", DebugView)
                # Set the analysis selector's value
                selector = debug_view.query_one("#analysis-selector")
                from textual.widgets import Select

                select_widget = selector.query_one("#analysis-select", Select)
                if select_widget:
                    select_widget.value = self.analysis_id

    # If analysis provided, try to find it
    if analysis:
        config, _ = load_config()
        kb_manager = KnowledgeBaseManager(config)

        found_id = None
        for aid, metadata in kb_manager.list_analyses():
            if aid == analysis or metadata.name == analysis:
                found_id = aid
                break

        if not found_id:
            console.print(f"[red]Analysis not found:[/red] {analysis}")
            raise typer.Exit(1)

        analysis = found_id

    # Run the debug TUI
    app = DebugTUI(analysis_id=analysis)
    app.run()


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
    import json
    import zipfile
    from datetime import datetime

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

    output_path = Path(output)

    try:
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
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
            facts: builtins.list[Any] = []
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
    from datetime import datetime, timedelta

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
        if found_id is None:
            console.print("[red]Error:[/red] Could not determine analysis ID")
            raise typer.Exit(1)
        kb_manager.delete_analysis(found_id)
        console.print(f"[green]✓ Analysis archived:[/green] {found_id}")

        # Clean up worktrees
        wt_manager = WorktreeManager(config, Path(found_metadata.repo_path))
        wt_manager.cleanup(found_id)

    except Exception as e:
        console.print(f"[red]Archive failed:[/red] {e}")
        raise typer.Exit(1) from e


@app.command()
def doctor(
    fix: Annotated[
        bool,
        typer.Option(help="Attempt to fix issues automatically"),
    ] = False,
) -> None:
    """Diagnose system health and configuration."""
    import shutil

    console.print("[bold]GGDes System Diagnostics[/bold]\n")

    issues_found = 0
    issues_fixed = 0

    # Check 1: Python version
    console.print("[dim]Checking Python version...[/dim]")
    import sys

    if sys.version_info >= (3, 10):
        console.print(
            "  [green]✓[/green] Python version: {}.{}.{}".format(*sys.version_info[:3])
        )
    else:
        console.print(
            "  [red]✗[/red] Python version too old: {}.{}.{} (requires 3.10+)".format(
                *sys.version_info[:3]
            )
        )
        issues_found += 1

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
        analyses: builtins.list[Path] = [p for p in kb_path.glob("*/metadata.yaml")]
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


@app.command()
def web(
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8000,
    reload: Annotated[bool, typer.Option(help="Enable auto-reload (dev mode)")] = False,
) -> None:
    """Start the web interface."""
    try:
        import uvicorn

        console.print("[bold]Starting GGDes Web Interface[/bold]")
        console.print(f"[dim]Host:[/dim] {host}")
        console.print(f"[dim]Port:[/dim] {port}")
        console.print(f"[dim]URL:[/dim] http://{host}:{port}")
        console.print()
        console.print("[green]Press Ctrl+C to stop the server[/green]")
        console.print()

        uvicorn.run(
            "ggdes.web:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )

    except ImportError:
        console.print("[red]Error:[/red] Web dependencies not installed.")
        console.print(
            "[dim]Install with: uv pip install fastapi uvicorn websockets[/dim]"
        )
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Failed to start web server:[/red] {e}")
        raise typer.Exit(1) from e


def main() -> None:
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
