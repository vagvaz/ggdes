"""Pipeline orchestrator for running analysis stages."""

from pathlib import Path
from typing import Optional

from rich.console import Console

from ggdes.agents import GitAnalyzer
from ggdes.config import GGDesConfig
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.parsing import ASTParser
from ggdes.schemas import ChangeSummary
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
        self.metadata = self.kb_manager.load_metadata(analysis_id)

        if not self.metadata:
            raise ValueError(f"Analysis not found: {analysis_id}")

        self.repo_path = Path(self.metadata.repo_path)
        self.wt_manager = WorktreeManager(config, self.repo_path)

    def run_stage(self, stage_name: str) -> bool:
        """Run a specific stage.

        Args:
            stage_name: Name of stage to run

        Returns:
            True if successful, False otherwise
        """
        if self.metadata.is_stage_completed(stage_name):
            console.print(
                f"[dim]Stage '{stage_name}' already completed, skipping[/dim]"
            )
            return True

        console.print(f"\n[bold]Running stage:[/bold] {stage_name}")
        self.metadata.start_stage(stage_name)
        self.kb_manager.save_metadata(self.analysis_id, self.metadata)

        try:
            if stage_name == self.kb_manager.STAGE_WORKTREE_SETUP:
                success = self._run_worktree_setup()
            elif stage_name == self.kb_manager.STAGE_GIT_ANALYSIS:
                success = self._run_git_analysis()
            elif stage_name == self.kb_manager.STAGE_AST_PARSING_BASE:
                success = self._run_ast_parsing_base()
            elif stage_name == self.kb_manager.STAGE_AST_PARSING_HEAD:
                success = self._run_ast_parsing_head()
            elif stage_name == self.kb_manager.STAGE_TECHNICAL_AUTHOR:
                success = self._run_technical_author()
            elif stage_name == self.kb_manager.STAGE_COORDINATOR_PLAN:
                success = self._run_coordinator_plan()
            elif stage_name == self.kb_manager.STAGE_OUTPUT_GENERATION:
                success = self._run_output_generation()
            else:
                console.print(
                    f"[yellow]Stage '{stage_name}' not yet implemented[/yellow]"
                )
                self.metadata.skip_stage(stage_name)
                self.kb_manager.save_metadata(self.analysis_id, self.metadata)
                return True

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
            self.metadata.fail_stage(stage_name, str(e))
            self.kb_manager.save_metadata(self.analysis_id, self.metadata)
            console.print(f"[red]✗ Stage failed:[/red] {stage_name} - {e}")
            return False

    def run_all_pending(self) -> bool:
        """Run all pending stages sequentially.

        Returns:
            True if all stages completed successfully
        """
        pending = self.metadata.get_pending_stages()

        if not pending:
            console.print("[green]All stages already completed![/green]")
            return True

        console.print(f"[bold]Running {len(pending)} pending stages...[/bold]")

        # Acquire lock for entire pipeline run
        with LockContext(self.repo_path, self.analysis_id):
            for stage in pending:
                success = self.run_stage(stage)
                if not success:
                    console.print(f"\n[red]Pipeline halted at stage:[/red] {stage}")
                    console.print(f"Run 'ggdes resume {self.analysis_id}' to retry")
                    return False

        console.print(f"\n[green]✓ All stages completed successfully![/green]")
        return True

    def _run_worktree_setup(self) -> bool:
        """Setup worktrees for base and head commits."""
        # Parse commit range
        commit_range = self.metadata.commit_range
        if ".." not in commit_range:
            console.print(f"[red]Invalid commit range:[/red] {commit_range}")
            return False

        base_commit, head_commit = commit_range.split("..", 1)

        # Create worktrees
        worktree_pair = self.wt_manager.create_for_analysis(
            self.analysis_id,
            base_commit=base_commit or "HEAD",
            head_commit=head_commit or "HEAD",
        )

        # Update metadata
        from ggdes.kb import WorktreeInfo

        self.metadata.worktrees = WorktreeInfo(
            base=str(worktree_pair.base),
            head=str(worktree_pair.head),
        )

        console.print(f"  Base worktree: {worktree_pair.base}")
        console.print(f"  Head worktree: {worktree_pair.head}")

        return True

    def _run_git_analysis(self) -> bool:
        """Run git analysis agent."""
        analyzer = GitAnalyzer(self.repo_path, self.config)

        change_summary = analyzer.analyze(
            commit_range=self.metadata.commit_range,
            focus_commits=self.metadata.focus_commits,
        )

        # Save to KB
        import json

        output_path = (
            self.kb_manager.get_analysis_path(self.analysis_id)
            / "git_analysis"
            / "summary.json"
        )
        output_path.write_text(json.dumps(change_summary.model_dump(), indent=2))

        console.print(f"  Analyzed {len(change_summary.files_changed)} files")
        console.print(f"  Change type: {change_summary.change_type}")
        console.print(f"  Impact: {change_summary.impact}")

        return True

    def _run_ast_parsing_base(self) -> bool:
        """Parse AST for base worktree."""
        if not self.metadata.worktrees:
            console.print("[red]Worktrees not set up[/red]")
            return False

        parser = ASTParser()
        base_path = Path(self.metadata.worktrees.base)

        console.print(f"  Parsing files in {base_path}...")

        # Parse all supported files
        results = parser.parse_directory(base_path, relative_to=base_path)

        # Save results
        import json

        output_dir = self.kb_manager.get_analysis_path(self.analysis_id) / "ast_base"
        total_elements = 0

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

        console.print(
            f"  Parsed {len(results)} files, extracted {total_elements} elements"
        )

        return True

    def _run_ast_parsing_head(self) -> bool:
        """Parse AST for head worktree."""
        if not self.metadata.worktrees:
            console.print("[red]Worktrees not set up[/red]")
            return False

        parser = ASTParser()
        head_path = Path(self.metadata.worktrees.head)

        console.print(f"  Parsing files in {head_path}...")

        results = parser.parse_directory(head_path, relative_to=head_path)

        # Save results
        import json

        output_dir = self.kb_manager.get_analysis_path(self.analysis_id) / "ast_head"
        total_elements = 0

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

        console.print(
            f"  Parsed {len(results)} files, extracted {total_elements} elements"
        )

        return True

    def _run_technical_author(self) -> bool:
        """Run technical author agent."""
        from ggdes.agents import TechnicalAuthor

        author = TechnicalAuthor(self.repo_path, self.config, self.analysis_id)

        import asyncio

        facts = asyncio.run(author.synthesize())

        console.print(f"  Synthesized {len(facts)} technical facts")

        # Show sample of facts
        for fact in facts[:3]:
            console.print(
                f"    - [{fact.category}] {fact.fact_id}: {fact.description[:60]}..."
            )

        if len(facts) > 3:
            console.print(f"    ... and {len(facts) - 3} more")

        return True

    def _run_coordinator_plan(self) -> bool:
        """Run coordinator planning stage."""
        from ggdes.agents import Coordinator

        coordinator = Coordinator(self.repo_path, self.config, self.analysis_id)

        # Get target formats from config
        target_formats = self.config.output.formats

        import asyncio

        # Check if we should run interactively
        # In auto mode, use defaults. Otherwise, ask user (handled in Coordinator)
        auto_mode = self.config.features.auto_cleanup  # Use as proxy for auto mode

        plans = asyncio.run(
            coordinator.create_plan(
                target_formats=target_formats,
                interactive=not auto_mode,
            )
        )

        console.print(f"  Created {len(plans)} document plans:")
        for plan in plans:
            console.print(
                f"    - {plan.format}: {len(plan.sections)} sections, {len(plan.diagrams)} diagrams"
            )

        return True

    def _run_output_generation(self) -> bool:
        """Run document output generation stage."""
        from ggdes.agents.output_agents import (
            MarkdownAgent,
            DocxAgent,
            PptxAgent,
            PdfAgent,
        )

        import asyncio

        # Get formats to generate from config
        formats = self.config.output.formats

        generated_files = []

        # Generate markdown first (source for other formats)
        if "markdown" in formats:
            console.print("  [dim]Generating markdown...[/dim]")
            try:
                agent = MarkdownAgent(self.repo_path, self.config, self.analysis_id)
                path = asyncio.run(agent.generate())
                generated_files.append(("markdown", path))
                console.print(f"    [green]✓[/green] Markdown: {path}")
            except Exception as e:
                console.print(f"    [red]✗[/red] Markdown failed: {e}")

        # Generate other formats
        for fmt in formats:
            if fmt == "markdown":
                continue  # Already done

            console.print(f"  [dim]Generating {fmt}...[/dim]")
            try:
                if fmt == "docx":
                    agent = DocxAgent(self.repo_path, self.config, self.analysis_id)
                elif fmt == "pptx":
                    agent = PptxAgent(self.repo_path, self.config, self.analysis_id)
                elif fmt == "pdf":
                    agent = PdfAgent(self.repo_path, self.config, self.analysis_id)
                else:
                    console.print(f"    [yellow]⚠[/yellow] Unknown format: {fmt}")
                    continue

                path = agent.generate()
                generated_files.append((fmt, path))
                console.print(f"    [green]✓[/green] {fmt}: {path}")
            except Exception as e:
                console.print(f"    [red]✗[/red] {fmt} failed: {e}")

        if generated_files:
            console.print(
                f"\n  [green]Generated {len(generated_files)} documents[/green]"
            )
            return True
        else:
            console.print(f"\n  [red]No documents generated[/red]")
            return False
