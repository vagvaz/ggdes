"""Worktree setup stage — creates isolated git worktrees for base and head commits."""

from pathlib import Path

from rich.console import Console

from ggdes.config import GGDesConfig
from ggdes.kb import AnalysisMetadata, KnowledgeBaseManager, WorktreeInfo
from ggdes.stages.base import Stage, StageResult
from ggdes.worktree import WorktreeManager


class WorktreeSetupStage(Stage):
    """Create git worktrees for the base and head commits being analysed."""

    name = "worktree_setup"

    async def run(
        self,
        metadata: AnalysisMetadata,
        config: GGDesConfig,
        kb: KnowledgeBaseManager,
        console: Console,
        feedback: str | None = None,
    ) -> StageResult:
        """Create worktrees for base and head commits.

        Parses the commit range from metadata, creates isolated git worktrees
        for both the base and head commits, and stores the resolved paths
        in ``metadata.worktrees``.
        """
        commit_range = metadata.commit_range
        console.print(f"  [dim]Parsing commit range: {commit_range}[/dim]")

        if ".." not in commit_range:
            console.print(f"[red]Invalid commit range:[/red] {commit_range}")
            return StageResult(
                success=False, error=f"Invalid commit range: {commit_range}"
            )

        base_commit, head_commit = commit_range.split("..", 1)
        repo_path = Path(metadata.repo_path)
        analysis_id = metadata.id

        console.print(
            f"  [dim]Setting up worktrees for base: {base_commit or 'HEAD'}, "
            f"head: {head_commit or 'HEAD'}[/dim]"
        )

        # Create worktrees
        wt_manager = WorktreeManager(config, repo_path)

        try:
            worktree_pair = wt_manager.create_for_analysis(
                analysis_id,
                base_commit=base_commit or "HEAD",
                head_commit=head_commit or "HEAD",
            )
        except (OSError, RuntimeError) as e:
            console.print(f"[red]Failed to create worktrees:[/red] {e}")
            return StageResult(success=False, error=str(e))

        # Verify worktrees were actually created
        if not worktree_pair.base.exists():
            console.print(
                f"[red]Base worktree was not created:[/red] {worktree_pair.base}"
            )
            return StageResult(success=False, error="Base worktree not created")

        if not worktree_pair.head.exists():
            console.print(
                f"[red]Head worktree was not created:[/red] {worktree_pair.head}"
            )
            return StageResult(success=False, error="Head worktree not created")

        # Check if worktrees have content
        try:
            base_contents = list(worktree_pair.base.iterdir())
            head_contents = list(worktree_pair.head.iterdir())

            if not base_contents:
                console.print(
                    f"[yellow]Warning: Base worktree is empty:[/yellow] "
                    f"{worktree_pair.base}"
                )
            if not head_contents:
                console.print(
                    f"[yellow]Warning: Head worktree is empty:[/yellow] "
                    f"{worktree_pair.head}"
                )

            console.print(f"  [dim]Base worktree items: {len(base_contents)}[/dim]")
            console.print(f"  [dim]Head worktree items: {len(head_contents)}[/dim]")
        except OSError as e:
            console.print(
                f"[yellow]Warning: Could not read worktree contents:[/yellow] {e}"
            )

        # Update metadata with absolute paths
        metadata.worktrees = WorktreeInfo(
            base=str(worktree_pair.base.resolve()),
            head=str(worktree_pair.head.resolve()),
        )

        console.print(f"  [green]✓ Base worktree:[/green] {worktree_pair.base}")
        console.print(f"  [green]✓ Head worktree:[/green] {worktree_pair.head}")

        return StageResult(success=True)
