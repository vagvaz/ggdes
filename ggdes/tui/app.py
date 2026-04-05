"""Terminal UI for GGDes using Textual."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
    ProgressBar,
    RichLog,
)
from textual.binding import Binding

from ggdes.cli import console
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus
from ggdes.worktree import WorktreeManager


class StageStatusWidget(Static):
    """Widget showing stage status with visual indicators."""

    STATUS_COLORS = {
        StageStatus.PENDING: "dim",
        StageStatus.IN_PROGRESS: "yellow",
        StageStatus.COMPLETED: "green",
        StageStatus.FAILED: "red",
        StageStatus.SKIPPED: "blue",
    }

    STATUS_ICONS = {
        StageStatus.PENDING: "○",
        StageStatus.IN_PROGRESS: "◐",
        StageStatus.COMPLETED: "✓",
        StageStatus.FAILED: "✗",
        StageStatus.SKIPPED: "⊘",
    }

    def __init__(self, stage_name: str, stage_info, **kwargs):
        super().__init__(**kwargs)
        self.stage_name = stage_name
        self.stage_info = stage_info

    def compose(self) -> ComposeResult:
        status = self.stage_info.status
        color = self.STATUS_COLORS.get(status, "white")
        icon = self.STATUS_ICONS.get(status, "?")

        yield Label(f"[{color}]{icon}[/{color}] {self.stage_name}")


class AnalysisListItem(ListItem):
    """List item showing analysis summary."""

    def __init__(self, analysis_id: str, name: str, status: str, **kwargs):
        super().__init__(**kwargs)
        self.analysis_id = analysis_id
        self.analysis_name = name
        self.status = status

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(f"[bold]{self.analysis_name}[/bold]", width=30)
            yield Label(f"[{self.status}] {self.analysis_id[:20]}...")


class AnalysisDetailView(VerticalScroll):
    """Detail view for a selected analysis."""

    analysis_id: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)

    def watch_analysis_id(self, analysis_id: str | None) -> None:
        """Update view when analysis changes."""
        if analysis_id:
            self.update_view(analysis_id)

    def update_view(self, analysis_id: str) -> None:
        """Update the view with analysis data."""
        metadata = self.kb_manager.load_metadata(analysis_id)
        if not metadata:
            return

        # Clear existing content
        self.remove_children()

        with self:
            # Header info
            yield Label(f"[bold cyan]Analysis:[/bold cyan] {metadata.name}")
            yield Label(f"[dim]ID:[/dim] {analysis_id}")
            yield Label(f"[dim]Repository:[/dim] {metadata.repo_path}")
            yield Label(f"[dim]Commits:[/dim] {metadata.commit_range}")
            yield Label(
                f"[dim]Created:[/dim] {metadata.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
            yield Label("")

            # Calculate progress
            total_stages = len(metadata.stages)
            completed = sum(
                1 for s in metadata.stages.values() if s.status == StageStatus.COMPLETED
            )
            failed = sum(
                1 for s in metadata.stages.values() if s.status == StageStatus.FAILED
            )

            # Progress bar
            yield Label(
                f"[bold]Progress:[/bold] {completed}/{total_stages} stages complete"
            )
            progress = ProgressBar(total=total_stages, show_eta=False)
            progress.update(completed)
            yield progress
            yield Label("")

            # Stage statuses
            yield Label("[bold]Stages:[/bold]")
            for stage_name, stage in metadata.stages.items():
                widget = StageStatusWidget(stage_name, stage)
                yield widget

            yield Label("")

            # Action buttons
            with Horizontal():
                pending = metadata.get_pending_stages()
                if pending:
                    yield Button(
                        f"▶ Resume ({len(pending)} pending)",
                        id="resume_btn",
                        variant="primary",
                    )
                else:
                    yield Button(
                        "✓ Complete",
                        id="complete_btn",
                        variant="success",
                        disabled=True,
                    )

                yield Button("🗑 Delete", id="delete_btn", variant="error")
                yield Button(
                    "📁 Open Worktree", id="open_worktree_btn", variant="default"
                )

            yield Label("")

            # Worktree info
            if metadata.worktrees:
                yield Label("[bold]Worktrees:[/bold]")
                yield Label(f"  Base: {metadata.worktrees.base}")
                yield Label(f"  Head: {metadata.worktrees.head}")


class WorktreeView(VerticalScroll):
    """View for managing worktrees."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)

    def compose(self) -> ComposeResult:
        yield Label("[bold]Active Worktrees[/bold]")
        yield Label("")

        # Get worktrees from all analyses
        analyses = self.kb_manager.list_analyses()

        for analysis_id, metadata in analyses:
            if metadata.worktrees:
                with Container(classes="worktree-card"):
                    yield Label(f"[bold]{metadata.name}[/bold] ({analysis_id[:20]}...)")
                    yield Label(f"  Base: {metadata.worktrees.base}")
                    yield Label(f"  Head: {metadata.worktrees.head}")
                    with Horizontal():
                        yield Button("Open Base", id=f"open_base_{analysis_id}")
                        yield Button("Open Head", id=f"open_head_{analysis_id}")
                        yield Button(
                            "Cleanup", id=f"cleanup_{analysis_id}", variant="error"
                        )
                yield Label("")


class CommandHelp(Static):
    """Help widget showing useful git/worktree commands."""

    COMMANDS = """
[bold cyan]Git Worktree Commands:[/bold cyan]

  [green]git worktree list[/green]
    List all worktrees

  [green]git worktree add <path> <commit>[/green]
    Create new worktree at commit

  [green]git worktree remove <path>[/green]
    Remove a worktree

  [green]cd <worktree-path> && git log --oneline[/green]
    View commits in worktree

[bold cyan]GGDes CLI Commands:[/bold cyan]

  [yellow]ggdes analyze --feature <name> <commits>[/yellow]
    Start new analysis

  [yellow]ggdes status[/yellow]
    Show all analyses

  [yellow]ggdes resume <analysis-id>[/yellow]
    Continue incomplete analysis

  [yellow]ggdes cleanup <analysis-id>[/yellow]
    Clean up worktrees

[bold cyan]TUI Navigation:[/bold cyan]

  [bold]Tab[/bold] - Switch between tabs
  [bold]↑↓[/bold] - Navigate lists
  [bold]Enter[/bold] - Select item
  [bold]r[/bold] - Refresh
  [bold]q[/bold] - Quit

[bold cyan]Stage Status Icons:[/bold cyan]

  [dim]○[/dim] Pending  [yellow]◐[/yellow] In Progress  
  [green]✓[/green] Completed  [red]✗[/red] Failed  [blue]⊘[/blue] Skipped
"""

    def compose(self) -> ComposeResult:
        yield Label(self.COMMANDS)


class GGDesTUI(App):
    """Main TUI application for GGDes."""

    CSS = """
    Screen {
        align: center middle;
    }
    
    #sidebar {
        width: 30%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    
    #main-content {
        width: 70%;
        height: 100%;
        border: solid $secondary;
        padding: 1;
    }
    
    .worktree-card {
        border: solid $primary-darken-2;
        padding: 1;
        margin: 1;
    }
    
    StageStatusWidget {
        padding: 0 1;
    }
    
    Button {
        margin: 0 1;
    }
    
    ProgressBar {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("a", "new_analysis", "New Analysis", show=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header(show_clock=True)

        with TabbedContent():
            with TabPane("📊 Analyses", id="analyses"):
                with Horizontal():
                    # Left sidebar: Analysis list
                    with Vertical(id="sidebar"):
                        yield Label("[bold]Analyses[/bold]")
                        yield Label("")

                        analyses = self.kb_manager.list_analyses()
                        if analyses:
                            list_items = []
                            for aid, metadata in analyses:
                                completed = len(metadata.get_completed_stages())
                                total = len(metadata.stages)
                                status = f"{completed}/{total}"
                                list_items.append(
                                    AnalysisListItem(aid, metadata.name, status)
                                )

                            list_view = ListView(*list_items, id="analysis-list")
                            yield list_view
                        else:
                            yield Label("[dim]No analyses yet.[/dim]")
                            yield Label("")
                            yield Button(
                                "➕ New Analysis",
                                id="new_analysis_btn",
                                variant="primary",
                            )

                    # Right: Detail view
                    with Vertical(id="main-content"):
                        yield AnalysisDetailView(id="detail-view")

            with TabPane("🌳 Worktrees", id="worktrees"):
                yield WorktreeView()

            with TabPane("❓ Help", id="help"):
                yield CommandHelp()

        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle analysis selection."""
        item = event.item
        if isinstance(item, AnalysisListItem):
            detail_view = self.query_one("#detail-view", AnalysisDetailView)
            detail_view.analysis_id = item.analysis_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "new_analysis_btn":
            self.action_new_analysis()
        elif button_id == "resume_btn":
            # Get current analysis and resume
            detail_view = self.query_one("#detail-view", AnalysisDetailView)
            if detail_view.analysis_id:
                self._resume_analysis(detail_view.analysis_id)
        elif button_id == "delete_btn":
            detail_view = self.query_one("#detail-view", AnalysisDetailView)
            if detail_view.analysis_id:
                self._delete_analysis(detail_view.analysis_id)

    def action_refresh(self) -> None:
        """Refresh the view."""
        self.refresh()

    def action_new_analysis(self) -> None:
        """Start new analysis."""
        # For now, just show a notification
        self.notify(
            "Use CLI: ggdes analyze --feature <name> <commits>", title="New Analysis"
        )

    def _resume_analysis(self, analysis_id: str) -> None:
        """Resume an analysis."""
        self.notify(f"Resuming {analysis_id[:20]}...", title="Resume")

    def _delete_analysis(self, analysis_id: str) -> None:
        """Delete an analysis."""
        self.notify(f"Deleting {analysis_id[:20]}...", title="Delete")


def run_tui() -> None:
    """Run the TUI application."""
    app = GGDesTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
