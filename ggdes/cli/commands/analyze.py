"""Analyze command."""

from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.cli.utils import (
    create_analysis_metadata,
    generate_analysis_id,
    parse_and_validate_formats,
    parse_and_validate_storage,
    run_analysis_pipeline,
    validate_commit_range,
)
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager
from ggdes.utils.lock import LockContext


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
    commits = commits.strip().strip("'\"")  # Remove surrounding quotes if present

    # Validate commit range
    commit_count = validate_commit_range(commits, repo_path)

    # Parse and validate inputs
    target_formats = parse_and_validate_formats(formats)
    focus_commits = [c.strip() for c in focus.split(",") if c.strip()] if focus else None
    storage_policy = parse_and_validate_storage(storage)

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

    # Acquire lock and run pipeline
    try:
        with LockContext(repo_path, analysis_id, force=force):
            metadata = create_analysis_metadata(
                kb_manager=kb_manager,
                analysis_id=analysis_id,
                feature=feature,
                repo_path=repo_path,
                commits=commits,
                focus_commits=focus_commits,
                target_formats=target_formats,
                storage_policy=storage_policy,
                render_png=render_png,
                no_filter=no_filter,
            )

            run_analysis_pipeline(
                config=config,
                analysis_id=analysis_id,
                kb_manager=kb_manager,
                metadata=metadata,
                repo_path=repo_path,
                commits=commits,
                target_formats=target_formats,
                storage_policy=storage_policy,
                interactive=interactive,
                setup_only=setup_only,
                semantic_diff=semantic_diff,
                no_filter=no_filter,
                auto=auto,
                context_file=context_file,
            )

    except RuntimeError as e:
        from ggdes.logging_config import get_logger

        logger = get_logger(__name__)
        logger.exception(f"Runtime error during analysis: {e}")
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e
