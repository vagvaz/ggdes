"""Shared CLI utilities."""

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import tomli
import typer
import yaml
from rich.prompt import Prompt

from ggdes.kb import KnowledgeBaseManager, StageStatus


# Import console from the cli package (set in __init__.py)
# We use a late import to avoid circular dependency
def _get_console():
    from ggdes.cli import console

    return console


def _get_version() -> str:
    """Read version from pyproject.toml."""
    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        return str(tomli.load(f)["project"]["version"])


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


def resolve_analysis(
    kb_manager: KnowledgeBaseManager, analysis: str
) -> tuple[str, Any]:
    """Resolve analysis ID or name to (id, metadata).

    Args:
        kb_manager: KnowledgeBaseManager instance
        analysis: Analysis ID or name

    Returns:
        Tuple of (analysis_id, metadata)

    Raises:
        typer.Exit(1): If analysis not found
    """
    console = _get_console()
    for aid, metadata in kb_manager.list_analyses():
        if aid == analysis or metadata.name == analysis:
            return aid, metadata

    console.print(f"[red]Analysis not found:[/red] {analysis}")
    raise typer.Exit(1)


def _gather_user_context() -> dict[str, Any]:
    """Gather user context through interactive questionnaire.

    Returns:
        Dictionary with user-provided context for all agents
    """
    console = _get_console()
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


def validate_commit_range(commits: str, repo_path: Path) -> int:
    """Validate a git commit range.

    Args:
        commits: Commit range string (e.g., 'HEAD~5..HEAD')
        repo_path: Path to the git repository

    Returns:
        Number of commits in the range

    Raises:
        typer.Exit: If the commit range is invalid
    """
    console = _get_console()

    # Validate format
    if ".." not in commits:
        console.print(f"[red]Error:[/red] Invalid commit range format: {commits}")
        console.print(
            "Commit range must contain '..' (e.g., 'HEAD~5..HEAD' or 'abc123..def456')"
        )
        console.print(
            "\nTip: Use quotes around the commit range to prevent shell interpretation:"
        )
        console.print('  ggdes analyze --feature test --commits "HEAD~5..HEAD"')
        raise typer.Exit(1)

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

    return commit_count


def parse_and_validate_formats(formats: str | None) -> list[str]:
    """Parse and validate output format strings.

    Args:
        formats: Comma-separated format string or None

    Returns:
        List of validated format names

    Raises:
        typer.Exit: If any format is invalid
    """
    console = _get_console()
    target_formats = ["markdown"]  # Default
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
    return target_formats


def parse_and_validate_storage(storage: str) -> str:
    """Validate storage policy string.

    Args:
        storage: Storage policy string

    Returns:
        Validated storage policy value

    Raises:
        typer.Exit: If the storage policy is invalid
    """
    console = _get_console()
    from ggdes.schemas import StoragePolicy

    valid_storage_policies = {s.value for s in StoragePolicy}
    storage_policy = storage.lower().strip()
    if storage_policy not in valid_storage_policies:
        console.print(f"[red]Error:[/red] Invalid storage policy: '{storage}'")
        console.print(f"Valid options: {', '.join(sorted(valid_storage_policies))}")
        raise typer.Exit(1)
    return storage_policy


def create_analysis_metadata(
    kb_manager: KnowledgeBaseManager,
    analysis_id: str,
    feature: str,
    repo_path: Path,
    commits: str,
    focus_commits: list[str] | None,
    target_formats: list[str],
    storage_policy: str,
    render_png: bool,
    no_filter: bool,
) -> Any:
    """Create analysis metadata in the knowledge base.

    Args:
        kb_manager: KnowledgeBaseManager instance
        analysis_id: Unique analysis ID
        feature: Feature name
        repo_path: Path to repository
        commits: Commit range
        focus_commits: List of focus commit hashes
        target_formats: List of output formats
        storage_policy: Storage policy value
        render_png: Whether to render PNG diagrams
        no_filter: Whether to disable semantic change filtering

    Returns:
        Created metadata object
    """
    from ggdes.schemas import StoragePolicy

    metadata = kb_manager.create_analysis(
        analysis_id=analysis_id,
        name=feature,
        repo_path=repo_path,
        commit_range=commits,
        focus_commits=focus_commits,
        prompt_version="v1.0.0",
        target_formats=target_formats,
        storage_policy=StoragePolicy(storage_policy),
    )

    metadata.render_png = render_png
    metadata.feature_description = feature
    metadata.no_filter = no_filter
    kb_manager.save_metadata(analysis_id, metadata)

    return metadata


def run_analysis_pipeline(
    config: Any,
    analysis_id: str,
    kb_manager: KnowledgeBaseManager,
    metadata: Any,
    repo_path: Path,
    commits: str,
    target_formats: list[str],
    storage_policy: str,
    interactive: bool,
    setup_only: bool,
    semantic_diff: bool,
    no_filter: bool,
    auto: bool,
    context_file: str | None,
) -> None:
    """Run the analysis pipeline.

    Args:
        config: GGDesConfig instance
        analysis_id: Unique analysis ID
        kb_manager: KnowledgeBaseManager instance
        metadata: Analysis metadata object
        repo_path: Path to repository
        commits: Commit range
        target_formats: List of output formats
        storage_policy: Storage policy value
        interactive: Enable interactive review mode
        setup_only: Only setup worktrees, don't run analysis
        semantic_diff: Enable semantic diff analysis
        no_filter: Disable semantic change filtering
        auto: Run all stages without prompting
        context_file: Path to user context file

    Raises:
        typer.Exit: If the pipeline fails
    """
    console = _get_console()
    from ggdes.logging_config import get_logger, setup_file_logging
    from ggdes.pipeline import AnalysisPipeline

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
        logger.info("Setup complete (setup-only mode)")
        console.print(f"\n[green]✓ Setup complete:[/green] {analysis_id}")
        console.print(f"Run 'ggdes resume {analysis_id}' to run analysis later")
        return

    # Gather user context for analysis
    user_context = {}
    if not auto:
        # Interactive mode: ask user for context
        console.print("\n[bold]Setup complete. Ready to run analysis.[/bold]")
        console.print("This will analyze the commits and generate documentation.")
        if not typer.confirm("Continue with analysis?"):
            logger.info("Analysis paused by user")
            console.print("\n[yellow]Analysis paused.[/yellow]")
            console.print(f"Run 'ggdes resume {analysis_id}' to continue later")
            return

        # Gather user context
        if context_file:
            user_context = _load_user_context_from_file(Path(context_file))
            console.print(f"[green]✓[/green] Loaded user context from: {context_file}")
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
        console.print("[dim]Semantic diff disabled - running faster analysis[/dim]")

        metadata.stages[kb_manager.STAGE_AST_PARSING_BASE].status = StageStatus.SKIPPED
        metadata.stages[kb_manager.STAGE_SEMANTIC_DIFF].status = StageStatus.SKIPPED
        kb_manager.save_metadata(analysis_id, metadata)

    # Configure change filter stage
    if no_filter:
        logger.info("Semantic change filtering disabled - skipping change filter stage")
        console.print("[dim]Change filtering disabled - analyzing all changes[/dim]")

        metadata.stages[kb_manager.STAGE_CHANGE_FILTER].status = StageStatus.SKIPPED
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
        console.print(f"\n[yellow]⚠ Analysis incomplete:[/yellow] {analysis_id}")
        console.print(f"Run 'ggdes resume {analysis_id}' to retry")
        raise typer.Exit(1)
