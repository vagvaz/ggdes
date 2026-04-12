"""Pipeline orchestrator for running analysis stages."""

import asyncio
import concurrent.futures
import json
import threading
import traceback
from pathlib import Path
from typing import Any

from rich.console import Console

from ggdes.agents import GitAnalyzer
from ggdes.config import GGDesConfig, ParsingMode
from ggdes.kb import KnowledgeBaseManager
from ggdes.parsing import ASTParser
from ggdes.schemas import CodeElement, StoragePolicy
from ggdes.tools import ToolExecutor
from ggdes.utils.lock import LockContext
from ggdes.worktree import WorktreeManager

console = Console()


class AnalysisPipeline:
    """Orchestrate the multi-stage analysis pipeline."""

    def __init__(self, config: GGDesConfig, analysis_id: str):
        """Initialize pipeline.

        Args:
            config: GGDes configuration
            analysis_id: Analysis identifier
        """
        self.config = config
        self.analysis_id = analysis_id
        self.kb_manager = KnowledgeBaseManager(config)
        metadata = self.kb_manager.load_metadata(analysis_id)

        if not metadata:
            raise ValueError(f"Analysis not found: {analysis_id}")

        self.metadata = metadata
        self.repo_path = Path(self.metadata.repo_path)
        self.wt_manager = WorktreeManager(config, self.repo_path)
        self._metadata_lock = threading.Lock()

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

        with self._metadata_lock:
            self.metadata.start_stage(stage_name)
            self.kb_manager.save_metadata(self.analysis_id, self.metadata)

        try:
            if stage_name == self.kb_manager.STAGE_WORKTREE_SETUP:
                success = self._run_worktree_setup()
            elif stage_name == self.kb_manager.STAGE_GIT_ANALYSIS:
                success = self._run_git_analysis()
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
                    return True
                else:
                    self.metadata.fail_stage(stage_name, "Stage returned False")
                    self.kb_manager.save_metadata(self.analysis_id, self.metadata)
                    console.print(f"[red]✗ Stage failed:[/red] {stage_name}")
                    return False

        except Exception as e:
            with self._metadata_lock:
                self.metadata.fail_stage(stage_name, str(e))
                self.kb_manager.save_metadata(self.analysis_id, self.metadata)
            console.print(f"[red]✗ Stage failed:[/red] {stage_name} - {e}")
            return False

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
        PARALLEL_GROUP = {
            self.kb_manager.STAGE_AST_PARSING_BASE,
            self.kb_manager.STAGE_AST_PARSING_HEAD,
            self.kb_manager.STAGE_SEMANTIC_DIFF,
        }

        # Acquire lock for entire pipeline run
        with LockContext(self.repo_path, self.analysis_id):
            i = 0
            while i < len(pending):
                stage = pending[i]

                # Check if this stage is part of a parallel group
                if stage in PARALLEL_GROUP:
                    # Find all pending stages from this parallel group
                    pending_parallel = [s for s in pending[i:] if s in PARALLEL_GROUP]
                    # Find all completed stages from this group
                    completed_in_group = PARALLEL_GROUP - set(pending_parallel)

                    if len(pending_parallel) == len(PARALLEL_GROUP):
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
                            f"[dim]Parallel group partially completed ({len(completed_in_group)}/{len(PARALLEL_GROUP)}), running remaining sequentially[/dim]"
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

    def _run_worktree_setup(self) -> bool:
        """Setup worktrees for base and head commits."""
        # Parse commit range
        commit_range = self.metadata.commit_range
        console.print(f"  [dim]Parsing commit range: {commit_range}[/dim]")

        if ".." not in commit_range:
            console.print(f"[red]Invalid commit range:[/red] {commit_range}")
            return False

        base_commit, head_commit = commit_range.split("..", 1)
        console.print(
            f"  [dim]Setting up worktrees for base: {base_commit or 'HEAD'}, head: {head_commit or 'HEAD'}[/dim]"
        )

        # Create worktrees
        try:
            worktree_pair = self.wt_manager.create_for_analysis(
                self.analysis_id,
                base_commit=base_commit or "HEAD",
                head_commit=head_commit or "HEAD",
            )
        except Exception as e:
            console.print(f"[red]Failed to create worktrees:[/red] {e}")
            return False

        # Verify worktrees were actually created
        if not worktree_pair.base.exists():
            console.print(
                f"[red]Base worktree was not created:[/red] {worktree_pair.base}"
            )
            return False
        if not worktree_pair.head.exists():
            console.print(
                f"[red]Head worktree was not created:[/red] {worktree_pair.head}"
            )
            return False

        # Check if worktrees have content
        try:
            base_contents = list(worktree_pair.base.iterdir())
            head_contents = list(worktree_pair.head.iterdir())

            if not base_contents:
                console.print(
                    f"[yellow]Warning: Base worktree is empty:[/yellow] {worktree_pair.base}"
                )
            if not head_contents:
                console.print(
                    f"[yellow]Warning: Head worktree is empty:[/yellow] {worktree_pair.head}"
                )

            console.print(f"  [dim]Base worktree items: {len(base_contents)}[/dim]")
            console.print(f"  [dim]Head worktree items: {len(head_contents)}[/dim]")
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not read worktree contents:[/yellow] {e}"
            )

        # Update metadata with absolute paths
        from ggdes.kb import WorktreeInfo

        self.metadata.worktrees = WorktreeInfo(
            base=str(worktree_pair.base.resolve()),
            head=str(worktree_pair.head.resolve()),
        )

        console.print(f"  [green]✓ Base worktree:[/green] {worktree_pair.base}")
        console.print(f"  [green]✓ Head worktree:[/green] {worktree_pair.head}")

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

        # Validate code references in the summary
        from ggdes.validation.code_references import CodeReferenceValidator

        changed_file_paths = [f.path for f in change_summary.files_changed]
        code_elements_set = set()
        # Collect element names from AST if available
        ast_head_dir = self.kb_manager.get_analysis_path(self.analysis_id) / "ast_head"
        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for elem_data in data.get("elements", []):
                        code_elements_set.add(elem_data.get("name", ""))
                except Exception:
                    continue

        # Convert set to dict format expected by CodeReferenceValidator
        code_elements_dict: dict[str, dict[str, Any]] = {
            name: {} for name in code_elements_set if name
        }
        validator = CodeReferenceValidator(
            repo_path=self.repo_path,
            changed_files=changed_file_paths,
            code_elements=code_elements_dict,
            diff_content="",  # We don't have the raw diff here
        )

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

        console.print(f"  [dim]Filtering AST parsing to changed files only[/dim]")

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

    def _get_changed_files_from_analysis(self) -> list[str]:
        """Get list of changed files from git analysis results.

        Returns:
            List of file paths that changed (relative to repo root)
        """
        analysis_path = (
            self.kb_manager.get_analysis_path(self.analysis_id)
            / "git_analysis"
            / "summary.json"
        )

        if not analysis_path.exists():
            return []

        try:
            data = json.loads(analysis_path.read_text())
            files_changed = data.get("files_changed", [])
            # Extract just the path from each FileChange object
            return [f["path"] for f in files_changed if "path" in f]
        except Exception:
            return []

    def _run_ast_parsing_head(self) -> bool:
        """Parse AST for head worktree."""
        return self._run_ast_parsing("head")

    def _build_tool_executor(self) -> "ToolExecutor":
        """Build a ToolExecutor for grounded LLM calls.

        Assembles changed files, AST elements, and commit range data
        from the knowledge base to provide tools with real codebase context.

        Returns:
            ToolExecutor instance, or None if required data is unavailable
        """
        from ggdes.tools import ToolExecutor

        # Load changed files from git analysis
        changed_files = self._get_changed_files_detailed()

        # Load AST elements from head worktree
        ast_elements = self._load_ast_elements_for_tools()

        # Get commit range and focus commits from metadata
        commit_range = self.metadata.commit_range
        focus_commits = self.metadata.focus_commits

        return ToolExecutor(
            repo_path=self.repo_path,
            changed_files=changed_files,
            ast_elements=ast_elements,
            commit_range=commit_range,
            focus_commits=focus_commits,
        )

    def _get_changed_files_detailed(self) -> list[dict[str, Any]]:
        """Get detailed changed file info from git analysis results.

        Returns:
            List of dicts with path, change_type, lines_added, lines_deleted, summary
        """
        analysis_path = (
            self.kb_manager.get_analysis_path(self.analysis_id)
            / "git_analysis"
            / "summary.json"
        )

        if not analysis_path.exists():
            return []

        try:
            data = json.loads(analysis_path.read_text())
            files_changed = data.get("files_changed", [])
            result = []
            for f in files_changed:
                if isinstance(f, dict):
                    result.append(
                        {
                            "path": f.get("path", ""),
                            "change_type": f.get("change_type", "modified"),
                            "lines_added": f.get("lines_added", 0),
                            "lines_deleted": f.get("lines_deleted", 0),
                            "summary": f.get("summary", ""),
                        }
                    )
            return result
        except Exception:
            return []

    def _load_ast_elements_for_tools(self) -> dict[str, list[Any]]:
        """Load AST elements from KB for tool executor.

        Returns:
            Dict mapping file paths to lists of code elements
        """
        ast_elements: dict[str, list[Any]] = {}

        # Load head AST elements
        ast_head_dir = self.kb_manager.get_analysis_path(self.analysis_id) / "ast_head"
        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    elements = data.get("elements", [])
                    if elements:
                        # Use the file_path from the data, or derive from filename
                        file_path = data.get("file_path", json_file.stem)
                        ast_elements[file_path] = elements
                except Exception:
                    continue

        return ast_elements

    def _run_technical_author(self) -> bool:
        """Run technical author agent."""
        from ggdes.agents import TechnicalAuthor
        from ggdes.agents.skill_utils import (
            detect_primary_language,
            get_expert_skill_for_language,
        )
        from ggdes.tools import ToolExecutor

        console.print("  [dim]Initializing Technical Author...[/dim]")

        # Get user context from metadata
        user_context = getattr(self.metadata, "user_context", None)

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
                except Exception:
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

        coordinator = Coordinator(
            self.repo_path, self.config, self.analysis_id, user_context=user_context
        )

        # Get target formats from metadata (CLI-selected formats)
        target_formats = self.metadata.target_formats or ["markdown"]
        console.print(f"  [dim]Target formats: {', '.join(target_formats)}[/dim]")

        # Check if we should run interactively
        # In auto mode, use defaults. Otherwise, ask user (handled in Coordinator)
        auto_mode = self.config.features.auto_cleanup  # Use as proxy for auto mode

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
                f"  [dim]Only analyzing files that changed in the commit range[/dim]"
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

    def _run_output_generation(self) -> bool:
        """Run document output generation stage."""
        from ggdes.agents.output_agents import (
            DocxAgent,
            MarkdownAgent,
            PdfAgent,
            PptxAgent,
        )

        # Get formats to generate from metadata (CLI-selected formats)
        formats = self.metadata.target_formats or ["markdown"]
        console.print(
            f"  [dim]Generating documents in formats: {', '.join(formats)}[/dim]"
        )

        generated_files = []

        # Generate markdown first (source for other formats)
        if "markdown" in formats:
            console.print("  [dim]Generating markdown source document...[/dim]")
            try:
                storage_policy = self.metadata.storage_policy

                agent = MarkdownAgent(self.repo_path, self.config, self.analysis_id)
                path = agent.generate(storage_policy=storage_policy)
                generated_files.append(("markdown", path))
                console.print(f"    [green]✓[/green] Markdown: {path}")
            except Exception as e:
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
                            self.repo_path, self.config, self.analysis_id
                        )
                        fmt_path = docx_agent.generate()
                    elif fmt == "pptx":
                        pptx_agent = PptxAgent(
                            self.repo_path, self.config, self.analysis_id
                        )
                        fmt_path = pptx_agent.generate()
                    elif fmt == "pdf":
                        pdf_agent = PdfAgent(
                            self.repo_path, self.config, self.analysis_id
                        )
                        fmt_path = pdf_agent.generate()
                    else:
                        return fmt, None, f"Unknown format: {fmt}"

                    return fmt, fmt_path, None
                except Exception as e:
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
            console.print(
                f"\n  [green]Successfully generated {len(generated_files)} document(s)[/green]"
            )
            for fmt, path in generated_files:
                console.print(f"    [dim]{fmt}: {path}[/dim]")
            return True
        else:
            console.print("\n  [red]No documents were generated successfully[/red]")
            return False
