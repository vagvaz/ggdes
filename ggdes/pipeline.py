"""Pipeline orchestrator for running analysis stages."""

import asyncio
import concurrent.futures
import json
import threading
import traceback
from pathlib import Path
from typing import Any

from loguru import logger
from rich.console import Console

from ggdes.agents import GitAnalyzer
from ggdes.config import GGDesConfig, ParsingMode
from ggdes.kb import KnowledgeBaseManager
from ggdes.parsing import ASTParser
from ggdes.review import ReviewSession
from ggdes.schemas import ChangeSummary, CodeElement
from ggdes.stages import StageResult as StageResultData, get_stage
from ggdes.tools import ToolExecutor
from ggdes.utils.lock import LockContext
from ggdes.worktree import WorktreeManager

console = Console()


class AnalysisPipeline:
    """Orchestrate the multi-stage analysis pipeline."""

    def __init__(
        self, config: GGDesConfig, analysis_id: str, interactive: bool = False
    ):
        """Initialize pipeline.

        Args:
            config: GGDes configuration
            analysis_id: Analysis identifier
            interactive: If True, pause after each stage for user review
        """
        self.config = config
        self.analysis_id = analysis_id
        self.interactive = interactive
        self.kb_manager = KnowledgeBaseManager(config)
        metadata = self.kb_manager.load_metadata(analysis_id)

        if not metadata:
            raise ValueError(f"Analysis not found: {analysis_id}")

        self.metadata = metadata
        self.repo_path = Path(self.metadata.repo_path)
        self.wt_manager = WorktreeManager(config, self.repo_path)
        self._metadata_lock = threading.Lock()
        self._review_session: ReviewSession | None = None
        self._load_review_session()

    def _load_review_session(self) -> None:
        """Load review session from KB if it exists (for resume scenarios)."""
        review_data = self.kb_manager.load_review_session(self.analysis_id)
        if review_data:
            self._review_session = ReviewSession.from_dict(review_data)
            console.print(
                f"[dim]Loaded review session with {len(self._review_session.stage_reviews)} prior review(s)[/dim]"
            )

    def _save_review_session(self) -> None:
        """Persist review session to KB."""
        if self._review_session:
            self.kb_manager.save_review_session(
                self.analysis_id, self._review_session.to_dict()
            )

    def _get_feedback_for_stage(self, stage_name: str) -> str | None:
        """Get accumulated feedback for a stage from review session."""
        if self._review_session:
            return self._review_session.get_feedback(stage_name)
        return None

    def run_stage(self, stage_name: str) -> bool:
        """Run a specific stage.

        Args:
            stage_name: Name of stage to run

        Returns:
            True if successful, False otherwise
        """
        with self._metadata_lock:
            if self.metadata.is_stage_completed(stage_name):
                console.print(
                    f"[dim]Stage '{stage_name}' already completed, skipping[/dim]"
                )
                return True

        console.print(f"\n[bold]Running stage:[/bold] {stage_name}")
        logger.info(
            "Pipeline stage starting | stage=%s analysis=%s",
            stage_name,
            self.analysis_id,
        )

        with self._metadata_lock:
            self.metadata.start_stage(stage_name)
            self.kb_manager.save_metadata(self.analysis_id, self.metadata)

        try:
            # --- EXTRACTED STAGES (via registry) ---
            stage_class = get_stage(stage_name)
            if stage_class is not None:
                stage = stage_class()
                result = asyncio.run(
                    stage.run(
                        metadata=self.metadata,
                        config=self.config,
                        kb=self.kb_manager,
                        console=console,
                        feedback=self._get_feedback_for_stage(stage_name),
                    )
                )
                with self._metadata_lock:
                    if result.skipped:
                        self.metadata.skip_stage(stage_name)
                        self.kb_manager.save_metadata(
                            self.analysis_id, self.metadata
                        )
                        logger.info(
                            "Pipeline stage skipped | stage=%s analysis=%s",
                            stage_name,
                            self.analysis_id,
                        )
                        return True
                    elif result.success:
                        self.metadata.complete_stage(stage_name)
                        self.kb_manager.save_metadata(
                            self.analysis_id, self.metadata
                        )
                        console.print(
                            f"[green]✓ Stage completed:[/green] {stage_name}"
                        )
                        logger.info(
                            "Pipeline stage completed | stage=%s analysis=%s",
                            stage_name,
                            self.analysis_id,
                        )
                        if self.interactive:
                            should_continue = self._maybe_review(stage_name)
                            if not should_continue:
                                console.print(
                                    "[yellow]Analysis paused for review.[/yellow]"
                                )
                                return False
                        return True
                    else:
                        error_msg = result.error or "Stage failed"
                        self.metadata.fail_stage(stage_name, error_msg)
                        self.kb_manager.save_metadata(
                            self.analysis_id, self.metadata
                        )
                        console.print(
                            f"[red]✗ Stage failed:[/red] {stage_name} - {error_msg}"
                        )
                        logger.error(
                            "Pipeline stage failed | stage=%s analysis=%s error=%s",
                            stage_name,
                            self.analysis_id,
                            error_msg,
                        )
                        return False
                # (end of with self._metadata_lock)

            # --- LEGACY DISPATCH (non-extracted stages) ---
            if stage_name == self.kb_manager.STAGE_GIT_ANALYSIS:
                success = self._run_git_analysis()
            elif stage_name == self.kb_manager.STAGE_CHANGE_FILTER:
                success = self._run_change_filter()
            elif stage_name == self.kb_manager.STAGE_AST_PARSING_BASE:
                success = self._run_ast_parsing("base")
            elif stage_name == self.kb_manager.STAGE_AST_PARSING_HEAD:
                success = self._run_ast_parsing("head")
            elif stage_name == self.kb_manager.STAGE_TECHNICAL_AUTHOR:
                success = self._run_technical_author()
            elif stage_name == self.kb_manager.STAGE_COORDINATOR_PLAN:
                success = self._run_coordinator_plan()
            elif stage_name == self.kb_manager.STAGE_OUTPUT_GENERATION:
                success = self._run_output_generation()
            elif stage_name == self.kb_manager.STAGE_SEMANTIC_DIFF:
                success = self._run_semantic_diff()
            else:
                console.print(
                    f"[yellow]Stage '{stage_name}' not yet implemented[/yellow]"
                )
                with self._metadata_lock:
                    self.metadata.skip_stage(stage_name)
                    self.kb_manager.save_metadata(self.analysis_id, self.metadata)
                return True

            with self._metadata_lock:
                if success:
                    self.metadata.complete_stage(stage_name)
                    self.kb_manager.save_metadata(self.analysis_id, self.metadata)
                    console.print(f"[green]✓ Stage completed:[/green] {stage_name}")
                    logger.info(
                        "Pipeline stage completed | stage=%s analysis=%s",
                        stage_name,
                        self.analysis_id,
                    )
                    # Interactive review after stage completion
                    if self.interactive:
                        should_continue = self._maybe_review(stage_name)
                        if not should_continue:
                            console.print(
                                "[yellow]Analysis paused for review.[/yellow]"
                            )
                            return False
                    return True
                else:
                    self.metadata.fail_stage(stage_name, "Stage returned False")
                    self.kb_manager.save_metadata(self.analysis_id, self.metadata)
                    console.print(f"[red]✗ Stage failed:[/red] {stage_name}")
                    logger.error(
                        "Pipeline stage failed | stage=%s analysis=%s",
                        stage_name,
                        self.analysis_id,
                    )
                    return False

        except Exception as e:
            with self._metadata_lock:
                self.metadata.fail_stage(stage_name, str(e))
                self.kb_manager.save_metadata(self.analysis_id, self.metadata)
            console.print(f"[red]✗ Stage failed:[/red] {stage_name} - {e}")
            logger.exception(
                "Pipeline stage exception | stage=%s analysis=%s",
                stage_name,
                self.analysis_id,
            )
            return False

    def _maybe_review(self, stage_name: str) -> bool:
        """Present interactive review UI after a stage completes.

        Args:
            stage_name: The stage that just completed

        Returns:
            True if analysis should continue, False if paused
        """
        from ggdes.review import REVIEWABLE_STAGES, SKIP_STAGES, StageReviewer

        # Skip review for infrastructure/non-reviewable stages
        if stage_name in SKIP_STAGES:
            return True

        # Skip review for stages not in our reviewable list
        if stage_name not in REVIEWABLE_STAGES:
            return True

        # Initialize review session if not already done
        if self._review_session is None:
            from ggdes.pipeline.review import ReviewSession

            self._review_session = ReviewSession(
                analysis_id=self.analysis_id,
                interactive=True,
            )

        # Check if user chose to skip remaining reviews
        if self._review_session.is_skipping():
            return True

        # Generate preview of stage output
        reviewer = StageReviewer(self.config, self.analysis_id)
        preview = reviewer.generate_preview(stage_name)

        if preview is None:
            console.print(
                f"[dim]No output found for {stage_name}, skipping review[/dim]"
            )
            return True

        # Present review UI and get user decision
        review = reviewer.review_stage(preview)
        self._review_session.add_review(review)

        console.print(f"[dim]Decision: {review.decision.value}[/dim]")

        if review.decision.value == "skip":
            return True

        if review.decision.value == "accept":
            return True

        # Regeneration requested
        if review.decision.value in ("regenerate_all", "regenerate_partial"):
            # Invalidate this stage and all subsequent stages so they re-run
            self._invalidate_from_stage(stage_name)
            # Persist review session so feedback survives resume
            self._save_review_session()
            console.print(
                f"[yellow]Stages will be regenerated on resume. "
                f"Feedback: {review.feedback or '(no specific feedback)'}[/yellow]"
            )
            return True

        # Save review session after any review decision
        self._save_review_session()
        return True

    def _invalidate_from_stage(self, stage_name: str) -> None:
        """Reset a stage and all subsequent stages to pending so they re-run.

        Args:
            stage_name: First stage to invalidate
        """

        stage_order = [
            self.kb_manager.STAGE_WORKTREE_SETUP,
            self.kb_manager.STAGE_GIT_ANALYSIS,
            self.kb_manager.STAGE_CHANGE_FILTER,
            self.kb_manager.STAGE_AST_PARSING_BASE,
            self.kb_manager.STAGE_AST_PARSING_HEAD,
            self.kb_manager.STAGE_SEMANTIC_DIFF,
            self.kb_manager.STAGE_TECHNICAL_AUTHOR,
            self.kb_manager.STAGE_COORDINATOR_PLAN,
            self.kb_manager.STAGE_OUTPUT_GENERATION,
        ]

        try:
            start_idx = stage_order.index(stage_name)
        except ValueError:
            return

        with self._metadata_lock:
            for stage in stage_order[start_idx:]:
                if self.metadata.is_stage_completed(stage):
                    self.metadata.reset_stage(stage)
            self.kb_manager.save_metadata(self.analysis_id, self.metadata)

    def run_parallel_group(self, stage_names: list[str]) -> dict[str, bool]:
        """Run multiple stages in parallel using ThreadPoolExecutor.

        Args:
            stage_names: List of stage names to run in parallel

        Returns:
            Dict mapping stage_name -> success (bool)
        """
        results: dict[str, bool] = {}

        def run_single_stage(stage: str) -> tuple[str, bool]:
            """Wrapper to run a single stage and return (name, success)."""
            success = self.run_stage(stage)
            return stage, success

        console.print(
            f"\n[bold]Running parallel group:[/bold] {', '.join(stage_names)}"
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(stage_names)
        ) as executor:
            futures = {
                executor.submit(run_single_stage, stage): stage for stage in stage_names
            }

            for future in concurrent.futures.as_completed(futures):
                stage, success = future.result()
                results[stage] = success

        return results

    def run_all_pending(self) -> bool:
        """Run all pending stages, with parallel execution for specific groups.

        Returns:
            True if all stages completed successfully
        """
        pending = self.metadata.get_pending_stages()

        if not pending:
            console.print("[green]All stages already completed![/green]")
            return True

        console.print(f"[bold]Running {len(pending)} pending stages...[/bold]")

        # Define parallel groups - stages that can run concurrently
        # AST base and head parsing can run in parallel since they're independent.
        # semantic_diff depends on git_analysis output and should run after AST parsing,
        # so it's NOT in the parallel group.
        parallel_group = {
            self.kb_manager.STAGE_AST_PARSING_BASE,
            self.kb_manager.STAGE_AST_PARSING_HEAD,
        }

        # Acquire lock for entire pipeline run
        with LockContext(self.repo_path, self.analysis_id):
            i = 0
            while i < len(pending):
                stage = pending[i]

                # Check if this stage is part of a parallel group
                if stage in parallel_group:
                    # Find all pending stages from this parallel group
                    pending_parallel = [s for s in pending[i:] if s in parallel_group]
                    # Find all completed stages from this group
                    completed_in_group = parallel_group - set(pending_parallel)

                    if len(pending_parallel) == len(parallel_group):
                        # All stages in the group are pending - run them in parallel
                        results = self.run_parallel_group(list(pending_parallel))
                        if not all(results.values()):
                            failed = [s for s, ok in results.items() if not ok]
                            console.print(
                                f"\n[red]Pipeline halted - parallel group failed:[/red] {', '.join(failed)}"
                            )
                            console.print(
                                f"Run 'ggdes resume {self.analysis_id}' to retry"
                            )
                            return False
                        i += len(pending_parallel)
                    else:
                        # Some stages already completed - run remaining sequentially
                        console.print(
                            f"[dim]Parallel group partially completed ({len(completed_in_group)}/{len(parallel_group)}), running remaining sequentially[/dim]"
                        )
                        for parallel_stage in pending_parallel:
                            success = self.run_stage(parallel_stage)
                            if not success:
                                console.print(
                                    f"\n[red]Pipeline halted at stage:[/red] {parallel_stage}"
                                )
                                console.print(
                                    f"Run 'ggdes resume {self.analysis_id}' to retry"
                                )
                                return False
                        i += len(pending_parallel)
                else:
                    # Run non-parallel stage sequentially
                    success = self.run_stage(stage)
                    if not success:
                        console.print(f"\n[red]Pipeline halted at stage:[/red] {stage}")
                        console.print(f"Run 'ggdes resume {self.analysis_id}' to retry")
                        return False
                    i += 1

        console.print("\n[green]✓ All stages completed successfully![/green]")
        return True

    def _run_git_analysis(self) -> bool:
        """Run git analysis agent."""
        from ggdes.validation.validators import InputValidator

        # Validate commit range
        input_validator = InputValidator(self.repo_path)
        range_validation = input_validator.validate_commit_range(
            self.metadata.commit_range
        )
        if not range_validation.passed:
            for error in range_validation.errors:
                console.print(f"  [red]✗ {error}[/red]")
            return False
        for warning in range_validation.warnings:
            console.print(f"  [yellow]⚠ {warning}[/yellow]")

        console.print(
            f"  [dim]Initializing GitAnalyzer for repository: {self.repo_path}[/dim]"
        )

        # Get user context from metadata
        user_context = getattr(self.metadata, "user_context", None)

        analyzer = GitAnalyzer(
            self.repo_path, self.config, self.analysis_id, user_context=user_context
        )

        commit_range = self.metadata.commit_range
        focus_commits = self.metadata.focus_commits

        if focus_commits:
            console.print(
                f"  [dim]Focus commits specified: {len(focus_commits)} commits[/dim]"
            )

        console.print("  [dim]Running git analysis (this may take a moment)...[/dim]")

        # Get storage policy from metadata

        storage_policy = self.metadata.storage_policy

        change_summary = asyncio.run(
            analyzer.analyze(
                commit_range=commit_range,
                focus_commits=focus_commits,
                storage_policy=storage_policy,
            )
        )

        # Save to KB
        output_path = (
            self.kb_manager.get_analysis_path(self.analysis_id)
            / "git_analysis"
            / "summary.json"
        )
        output_path.write_text(json.dumps(change_summary.model_dump(), indent=2))

        console.print(
            f"  [dim]Analyzed {len(change_summary.files_changed)} files in {len(focus_commits) if focus_commits else 'full range'}[/dim]"
        )
        console.print(f"  [dim]Change type: {change_summary.change_type}[/dim]")
        console.print(f"  [dim]Impact: {change_summary.impact}[/dim]")
        console.print(f"  [dim]Results saved to: {output_path}[/dim]")

        return True

    def _run_change_filter(self) -> bool:
        """Filter changes by semantic relevance to the feature.

        Uses the feature description from metadata (derived from --feature flag
        or user context) to classify which changed files are relevant.

        If no feature description is available, this stage is skipped.
        """
        # Get feature description from metadata
        feature_description = getattr(self.metadata, "feature_description", None)

        # Fall back to the analysis name if no explicit feature description
        if not feature_description:
            feature_description = self.metadata.name

        # Check if filtering is explicitly disabled
        if getattr(self.metadata, "no_filter", False):
            console.print(
                "  [dim]Semantic filtering disabled (--no-filter), skipping[/dim]"
            )
            return True

        # Load the change summary from git analysis
        summary_path = (
            self.kb_manager.get_analysis_path(self.analysis_id)
            / "git_analysis"
            / "summary.json"
        )

        if not summary_path.exists():
            console.print(
                "  [yellow]No git analysis found, skipping change filter[/yellow]"
            )
            return True

        try:
            data = json.loads(summary_path.read_text())
            change_summary = ChangeSummary(**data)
        except (json.JSONDecodeError, ValueError) as e:
            console.print(f"  [red]Error loading change summary:[/red] {e}")
            return False

        # If already filtered, skip
        if change_summary.is_filtered:
            console.print("  [dim]Changes already filtered, skipping[/dim]")
            return True

        # Get the git diff for classification
        from ggdes.agents import GitAnalyzer

        user_context = getattr(self.metadata, "user_context", None)
        analyzer = GitAnalyzer(
            self.repo_path, self.config, self.analysis_id, user_context=user_context
        )

        commit_range = self.metadata.commit_range
        focus_commits = self.metadata.focus_commits

        try:
            diff = analyzer.get_diff(commit_range, focus_commits)
        except Exception as e:
            console.print(f"  [red]Error getting git diff:[/red] {e}")
            return False

        # Run the change filter
        from ggdes.agents.change_filter import ChangeFilter

        try:
            change_filter = ChangeFilter(
                config=self.config,
                feature_description=feature_description,
            )

            filtered_summary = change_filter.filter_changes(change_summary, diff)

            # Save the filtered summary to change_filter directory (derived artifact)
            change_filter_dir = (
                self.kb_manager.get_analysis_path(self.analysis_id) / "change_filter"
            )
            change_filter_dir.mkdir(parents=True, exist_ok=True)
            filtered_path = change_filter_dir / "summary.json"
            filtered_path.write_text(
                json.dumps(filtered_summary.model_dump(), indent=2)
            )

            # Keep the original (raw) summary in git_analysis unchanged
            # Downstream stages should read from change_filter/summary.json
            # but git_analysis/summary.json remains the unfiltered reference

            console.print(
                f"  [dim]Filtered: {len(change_summary.files_changed)} → "
                f"{len(filtered_summary.files_changed)} files[/dim]"
            )

        except Exception as e:
            console.print(f"  [red]Change filter failed:[/red] {e}")
            console.print(f"  [dim]{traceback.format_exc()}[/dim]")
            return False

        return True

    def _run_ast_parsing(self, variant: str) -> bool:
        """Parse AST for a worktree (base or head).

        Args:
            variant: Either "base" or "head" to specify which worktree to parse

        Returns:
            True if successful, False otherwise
        """
        if not self.metadata.worktrees:
            console.print("[red]Worktrees not set up[/red]")
            return False

        parser = ASTParser()
        worktree_path = Path(getattr(self.metadata.worktrees, variant))

        console.print(f"  [dim]Scanning {variant} worktree: {worktree_path}[/dim]")
        console.print("  [dim]Parsing source files (this may take a moment)...[/dim]")

        # Check if directory exists
        if not worktree_path.exists():
            console.print(
                f"  [red]Error: {variant.capitalize()} worktree does not exist: {worktree_path}[/red]"
            )
            return False

        if not any(worktree_path.iterdir()):
            console.print(
                f"  [yellow]Warning: {variant.capitalize()} worktree is empty: {worktree_path}[/yellow]"
            )

        # Get list of changed files from git analysis if available
        changed_files = self._get_changed_files_from_analysis()

        console.print("  [dim]Filtering AST parsing to changed files only[/dim]")

        # Determine parsing mode
        parsing_config = self.config.parsing
        if parsing_config.mode == ParsingMode.INCREMENTAL and changed_files:
            console.print(
                f"  [dim]Incremental parsing mode: {len(changed_files)} changed files[/dim]"
            )
            results = parser.parse_incremental(
                directory=worktree_path,
                changed_files=changed_files,
                relative_to=worktree_path,
                include_referenced=parsing_config.include_referenced,
                max_referenced_depth=parsing_config.max_referenced_depth,
                verbose=True,
            )
            console.print(
                f"  [dim]AST parsing only analyzed {len(changed_files)} changed files[/dim]"
            )
        else:
            if parsing_config.mode == ParsingMode.INCREMENTAL and not changed_files:
                console.print(
                    "  [yellow]Incremental mode requested but no changed files found, falling back to full scan[/yellow]"
                )
            # Full scan - parse all supported files
            console.print(
                "  [yellow]Note: Full directory scan (not limited to changed files)[/yellow]"
            )
            results = parser.parse_directory(
                worktree_path, relative_to=worktree_path, verbose=True
            )

        # Save results
        output_dir = (
            self.kb_manager.get_analysis_path(self.analysis_id) / f"ast_{variant}"
        )
        total_elements = 0
        successful_parses = 0

        for result in results:
            if result.success:
                output_file = output_dir / f"{result.file_path.replace('/', '_')}.json"
                output_file.write_text(
                    json.dumps(
                        {
                            "file_path": result.file_path,
                            "language": result.language,
                            "elements": [e.model_dump() for e in result.elements],
                        },
                        indent=2,
                    )
                )
                total_elements += len(result.elements)
                successful_parses += 1

        console.print(
            f"  [dim]Parsed {successful_parses}/{len(results)} files successfully[/dim]"
        )
        console.print(
            f"  [dim]Extracted {total_elements} code elements (functions, classes, etc.)[/dim]"
        )

        return True

    def _run_ast_parsing_base(self) -> bool:
        """Parse AST for base worktree."""
        return self._run_ast_parsing("base")

    def _get_summary_path(self) -> Path:
        """Get the path to the change summary, preferring filtered over raw.

        Delegates to ``ggdes.stages.utils.get_summary_path``.
        """
        from ggdes.stages.utils import get_summary_path

        return get_summary_path(self.kb_manager, self.analysis_id)

    def _get_changed_files_from_analysis(self) -> list[str]:
        """Get list of changed files from git analysis results.

        Delegates to ``ggdes.stages.utils.get_changed_files_from_analysis``.
        """
        from ggdes.stages.utils import get_changed_files_from_analysis

        return get_changed_files_from_analysis(self.kb_manager, self.analysis_id)

    def _run_ast_parsing_head(self) -> bool:
        """Parse AST for head worktree."""
        return self._run_ast_parsing("head")

    def _build_tool_executor(self) -> "ToolExecutor":
        """Build a ToolExecutor for grounded LLM calls.

        Delegates to ``ggdes.stages.utils.build_tool_executor``.
        """
        from ggdes.stages.utils import build_tool_executor

        return build_tool_executor(
            config=self.config,
            kb=self.kb_manager,
            analysis_id=self.analysis_id,
            repo_path=self.repo_path,
            metadata=self.metadata,
        )

    def _get_changed_files_detailed(self) -> list[dict[str, Any]]:
        """Get detailed changed file info from git analysis results.

        Delegates to ``ggdes.stages.utils.get_changed_files_detailed``.
        """
        from ggdes.stages.utils import get_changed_files_detailed

        return get_changed_files_detailed(self.kb_manager, self.analysis_id)

    def _load_ast_elements_for_tools(self) -> dict[str, list[Any]]:
        """Load AST elements from KB for tool executor.

        Delegates to ``ggdes.stages.utils.load_ast_elements``.
        """
        from ggdes.stages.utils import load_ast_elements

        return load_ast_elements(self.kb_manager, self.analysis_id, "head")

    def _run_technical_author(self) -> bool:
        """Run technical author agent."""
        from ggdes.agents import TechnicalAuthor
        from ggdes.agents.skill_utils import (
            detect_primary_language,
            get_expert_skill_for_language,
        )

        console.print("  [dim]Initializing Technical Author...[/dim]")

        # Get user context from metadata
        user_context = getattr(self.metadata, "user_context", None)

        # Get feedback for this stage (from review session)
        feedback = self._get_feedback_for_stage(self.kb_manager.STAGE_TECHNICAL_AUTHOR)
        if feedback:
            console.print(
                f"  [yellow]Applying review feedback: {feedback[:100]}...[/yellow]"
            )

        # Detect language for expert skill
        language_expert_skill = None
        try:
            language = detect_primary_language(self.repo_path)
            if language:
                language_expert_skill = get_expert_skill_for_language(language)
        except Exception:
            pass  # Graceful fallback: continue without expert skill

        # Build tool executor for grounded fact generation
        tool_executor = self._build_tool_executor()

        author = TechnicalAuthor(
            self.repo_path,
            self.config,
            self.analysis_id,
            user_context=user_context,
            language_expert_skill=language_expert_skill,
            tool_executor=tool_executor,
            review_feedback=feedback,
        )

        console.print("  [dim]Synthesizing technical facts from analysis...[/dim]")
        # Get storage policy from metadata
        storage_policy = self.metadata.storage_policy

        try:
            facts = asyncio.run(author.synthesize(storage_policy=storage_policy))
        except Exception as e:
            console.print(f"  [red]Technical author failed:[/red] {e}")
            console.print(f"  [dim]{traceback.format_exc()}[/dim]")
            return False

        console.print(f"  [dim]Synthesized {len(facts)} technical facts[/dim]")

        # After facts are generated, validate them against AST data
        from ggdes.validation.validators import ASTValidator

        # Load AST elements for validation
        head_elements = []
        ast_head_dir = self.kb_manager.get_analysis_path(self.analysis_id) / "ast_head"
        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for elem_data in data.get("elements", []):
                        head_elements.append(CodeElement(**elem_data))
                except (json.JSONDecodeError, ValueError):
                    continue

        if head_elements:
            validator = ASTValidator(head_elements)
            validation_result = validator.validate_facts(facts)
            if validation_result.errors:
                console.print(
                    f"  [yellow]⚠ Validation found {len(validation_result.errors)} errors in technical facts[/yellow]"
                )
                for error in validation_result.errors[:5]:  # Show first 5
                    console.print(f"    [dim]- {error}[/dim]")
            if validation_result.warnings:
                console.print(
                    f"  [yellow]⚠ Validation found {len(validation_result.warnings)} warnings[/yellow]"
                )
                for warning in validation_result.warnings[:5]:
                    console.print(f"    [dim]- {warning}[/dim]")

        # Show sample of facts
        for fact in facts[:3]:
            console.print(
                f"    [dim]- [{fact.category}] {fact.fact_id}: {fact.description[:60]}...[/dim]"
            )

        if len(facts) > 3:
            console.print(f"    [dim]... and {len(facts) - 3} more[/dim]")

        return True

    def _run_coordinator_plan(self) -> bool:
        """Run coordinator planning stage."""
        from ggdes.agents import Coordinator

        console.print("  [dim]Initializing Coordinator for document planning...[/dim]")

        # Get user context from metadata
        user_context = getattr(self.metadata, "user_context", None)

        # Get feedback for this stage (from review session)
        feedback = self._get_feedback_for_stage(self.kb_manager.STAGE_COORDINATOR_PLAN)
        if feedback:
            console.print(
                f"  [yellow]Applying review feedback: {feedback[:100]}...[/yellow]"
            )

        coordinator = Coordinator(
            self.repo_path,
            self.config,
            self.analysis_id,
            user_context=user_context,
            review_feedback=feedback,
        )

        # Get target formats from metadata (CLI-selected formats)
        target_formats = self.metadata.target_formats or ["markdown"]
        console.print(f"  [dim]Target formats: {', '.join(target_formats)}[/dim]")

        # Check if we should run interactively
        # In auto mode, use defaults. Otherwise, ask user (handled in Coordinator)
        auto_mode = not self.interactive

        if auto_mode:
            console.print("  [dim]Running in auto mode (no user prompts)[/dim]")

        # Get storage policy from metadata
        storage_policy = self.metadata.storage_policy

        try:
            plans = asyncio.run(
                coordinator.create_plan(
                    target_formats=target_formats,
                    interactive=not auto_mode,
                    storage_policy=storage_policy,
                )
            )
        except Exception as e:
            console.print(f"  [red]Coordinator planning failed:[/red] {e}")
            console.print(f"  [dim]{traceback.format_exc()}[/dim]")
            return False

        console.print(f"  [dim]Created {len(plans)} document plans:[/dim]")
        for plan in plans:
            console.print(
                f"    [dim]- {plan.format}: {len(plan.sections)} sections, {len(plan.diagrams)} diagrams[/dim]"
            )

        return True

    def _run_semantic_diff(self) -> bool:
        """Run semantic diff analysis stage."""
        from ggdes.semantic_diff import SemanticDiffAnalyzer, save_semantic_diff

        if not self.metadata.worktrees:
            console.print("[red]Worktrees not set up[/red]")
            return False

        console.print("  [dim]Initializing Semantic Diff Analyzer...[/dim]")

        analyzer = SemanticDiffAnalyzer(self.config)

        # Get changed files from git analysis
        changed_files = self._get_changed_files_from_analysis()

        if not changed_files:
            console.print("  [yellow]No changed files to analyze[/yellow]")
            # Skip stage successfully if nothing to analyze
            return True

        # Parse commit range
        commit_range = self.metadata.commit_range
        if ".." in commit_range:
            base_commit, head_commit = commit_range.split("..", 1)
        else:
            base_commit = ""
            head_commit = commit_range

        try:
            console.print(
                f"  [dim]Performing semantic diff on {len(changed_files)} changed files...[/dim]"
            )
            console.print(
                "  [dim]Only analyzing files that changed in the commit range[/dim]"
            )

            result = analyzer.analyze(
                base_path=Path(self.metadata.worktrees.base),
                head_path=Path(self.metadata.worktrees.head),
                base_commit=base_commit or "HEAD",
                head_commit=head_commit or "HEAD",
                changed_files=changed_files,
            )

            # Save results
            output_path = (
                self.kb_manager.get_analysis_path(self.analysis_id)
                / "semantic_diff"
                / "result.json"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            save_semantic_diff(result, output_path)

            # Print summary
            console.print(
                f"  [dim]Semantic diff analyzed {len(changed_files)} changed files:[/dim]"
            )
            console.print(
                f"  [dim]Detected {len(result.semantic_changes)} semantic change(s):[/dim]"
            )
            console.print(f"    - Breaking changes: {len(result.breaking_changes)}")
            console.print(f"    - Behavioral changes: {len(result.behavioral_changes)}")
            console.print(
                f"    - Refactoring changes: {len(result.refactoring_changes)}"
            )
            console.print(
                f"    - Documentation changes: {len(result.documentation_changes)}"
            )
            console.print(
                f"    - Total impact score: {result.total_impact_score:.1f}/10"
            )

            if result.has_breaking_changes:
                console.print("  [yellow]⚠ Breaking changes detected![/yellow]")

            return True

        except Exception as e:
            console.print(f"  [red]Semantic diff analysis failed:[/red] {e}")
            console.print(f"  [dim]{traceback.format_exc()}[/dim]")
            return False

    def _get_output_base(self) -> Path:
        """Get the base output directory, possibly scoped to a revision."""
        from ggdes.config import get_output_path

        base = get_output_path(self.config, self.analysis_id)
        rev = getattr(self.metadata, "current_revision", None)
        if rev:
            base = base / rev
        return base

    def _run_output_generation(self) -> bool:
        """Run document output generation stage."""
        from ggdes.agents.output_agents import (
            DocxAgent,
            MarkdownAgent,
            PdfAgent,
            PptxAgent,
        )

        # Get feedback for this stage
        feedback = self._get_feedback_for_stage("output_generation")

        # Get formats to generate from metadata (CLI-selected formats)
        formats = self.metadata.target_formats or ["markdown"]
        rev = getattr(self.metadata, "current_revision", None)
        if rev:
            console.print(f"  [dim]Revision: {rev}[/dim]")
        console.print(
            f"  [dim]Generating documents in formats: {', '.join(formats)}[/dim]"
        )
        if feedback:
            console.print(
                "  [yellow]Applying review feedback to output generation[/yellow]"
            )

        generated_files = []

        # Generate markdown first (source for other formats)
        if "markdown" in formats:
            console.print("  [dim]Generating markdown source document...[/dim]")
            try:
                storage_policy = self.metadata.storage_policy

                # Check if render_png flag is set in metadata
                render_png = getattr(self.metadata, "render_png", False)

                agent = MarkdownAgent(
                    self.repo_path,
                    self.config,
                    self.analysis_id,
                    review_feedback=feedback,
                )
                path = agent.generate(
                    storage_policy=storage_policy, render_png=render_png
                )
                generated_files.append(("markdown", path))
                console.print(f"    [green]✓[/green] Markdown: {path}")
            except Exception as e:
                logger.exception("Markdown generation failed: %s", e)
                console.print(f"    [red]✗[/red] Markdown generation failed: {e}")
                console.print(f"    [dim]{traceback.format_exc()}[/dim]")

        # Collect other formats to generate in parallel
        other_formats = [fmt for fmt in formats if fmt != "markdown"]

        if other_formats:
            console.print(
                f"  [dim]Generating {len(other_formats)} format(s) in parallel...[/dim]"
            )

            def generate_format(fmt: str) -> tuple[str, Path | None, str | None]:
                """Generate a single format. Returns (format, path_or_None, error_or_None)."""
                try:
                    fmt_path: Path | None = None
                    if fmt == "docx":
                        docx_agent = DocxAgent(
                            self.repo_path,
                            self.config,
                            self.analysis_id,
                            review_feedback=feedback,
                        )
                        fmt_path = docx_agent.generate()
                    elif fmt == "pptx":
                        pptx_agent = PptxAgent(
                            self.repo_path,
                            self.config,
                            self.analysis_id,
                            review_feedback=feedback,
                        )
                        fmt_path = pptx_agent.generate()
                    elif fmt == "pdf":
                        pdf_agent = PdfAgent(
                            self.repo_path,
                            self.config,
                            self.analysis_id,
                            review_feedback=feedback,
                        )
                        fmt_path = pdf_agent.generate()
                    else:
                        return fmt, None, f"Unknown format: {fmt}"

                    return fmt, fmt_path, None
                except Exception as e:
                    logger.exception("%s generation failed: %s", fmt, e)
                    return fmt, None, str(e)

            # Run format generation in parallel
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(other_formats)
            ) as executor:
                futures = {
                    executor.submit(generate_format, fmt): fmt for fmt in other_formats
                }

                for future in concurrent.futures.as_completed(futures):
                    fmt, fmt_path, error = future.result()

                    if error:
                        console.print(
                            f"    [red]✗[/red] {fmt} generation failed: {error}"
                        )
                    elif fmt_path:
                        generated_files.append((fmt, fmt_path))
                        console.print(f"    [green]✓[/green] {fmt}: {fmt_path}")
                    else:
                        console.print(
                            f"    [yellow]⚠[/yellow] {fmt}: No output generated"
                        )

        if generated_files:
            logger.info("Generated %d document(s) successfully", len(generated_files))
            console.print(
                f"\n  [green]Successfully generated {len(generated_files)} document(s)[/green]"
            )
            for fmt, path in generated_files:
                console.print(f"    [dim]{fmt}: {path}[/dim]")
            return True
        else:
            logger.error("No documents were generated successfully")
            console.print("\n  [red]No documents were generated successfully[/red]")
            return False
