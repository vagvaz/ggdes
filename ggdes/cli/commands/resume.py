"""Resume command."""

from pathlib import Path
from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.cli.utils import (
    _gather_user_context,
    _load_user_context_from_file,
    resolve_analysis,
)
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus


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
    found_id, found_metadata = resolve_analysis(kb_manager, analysis)

    # Setup logging for this analysis
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
        kb_manager.save_metadata(found_id, found_metadata)
        console.print(
            f"[green]✓ Target formats updated:[/green] {', '.join(target_formats)}"
        )

        # Reset coordinator_plan and output_generation stages to regenerate plans for new formats
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
    can_resume, reason = kb_manager.can_resume(found_id, retry_failed=retry_failed)
    if not can_resume:
        logger.error(f"Cannot resume: {reason}")
        console.print(f"[red]Cannot resume:[/red] {reason}")
        raise typer.Exit(1)

    # If retry_failed is set, reset all failed stages
    if retry_failed:
        reset_stages = kb_manager.reset_failed_stages(found_id)
        if reset_stages:
            logger.info(f"Reset failed stages for retry: {', '.join(reset_stages)}")
            console.print(
                f"[yellow]Reset {len(reset_stages)} failed stage(s) for retry:[/yellow] {', '.join(reset_stages)}"
            )
            # Reload metadata after reset
            found_metadata = kb_manager.load_metadata(found_id)
            if found_metadata is None:
                console.print("[red]Error:[/red] Could not load metadata after reset")
                raise typer.Exit(1)
        else:
            logger.info("No failed stages to reset")

    # Handle user context
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
        found_metadata.user_context = user_context
        kb_manager.save_metadata(found_id, found_metadata)
        logger.info(f"Updated user context: {user_context}")
        console.print("[green]✓ User context updated[/green]")

        # Reset coordinator_plan and output_generation stages to regenerate with new context
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
        found_metadata.user_context = user_context
        kb_manager.save_metadata(found_id, found_metadata)
        logger.info(f"User context saved: {user_context}")

    console.print(f"[dim]Target formats: {', '.join(target_formats)}[/dim]")
    console.print(f"[dim]User context: {bool(user_context)}[/dim]\n")

    # Run pipeline
    from ggdes.pipeline import AnalysisPipeline

    try:
        pipeline = AnalysisPipeline(config, found_id, interactive=interactive)

        if stage:
            # Run specific stage
            logger.info(f"Running specific stage: {stage}")
            console.print(f"[bold]Running stage:[/bold] {stage}")
            console.print(f"[dim]Target formats: {', '.join(target_formats)}[/dim]")
            success = pipeline.run_stage(stage)
        else:
            # Run all pending stages
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
