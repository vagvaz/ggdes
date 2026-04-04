"""Terminal UI for GGDes using Textual."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
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
    TextArea,
)

from ggdes.cli import console
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager
from ggdes.utils.lock import AnalysisLock
from ggdes.worktree import WorktreeManager


class AnalysisListView(ListView):
    """List view for analyses."""

    def __init__(self, analyses: list[tuple[str, str]], **kwargs):
        items = [ListItem(Label(f"{name} ({aid[:20]}...)")) for aid, name in analyses]
        super().__init__(*items, **kwargs)
        self.analyses = analyses


class WorktreeBrowser(Static):
    """Widget for browsing worktrees."""

    def __init__(self, worktree_pair=None, **kwargs):
        super().__init__(**kwargs)
        self.worktree_pair = worktree_pair

    def compose(self) -> ComposeResult:
        if self.worktree_pair:
            yield Label(f"[bold]Base:[/bold] {self.worktree_pair.base}")
            yield Label(f"[bold]Head:[/bold] {self.worktree_pair.head}")
            yield Button("Explore Base", id="explore_base")
            yield Button("Explore Head", id="explore_head")
        else:
            yield Label("[dim]No worktrees for this analysis[/dim]")


class CommandHelp(Static):
    """Help widget showing useful git/worktree commands."""

    COMMANDS = """
[bold]Git Worktree Commands:[/bold]

  [green]git worktree list[/green]
    List all worktrees

  [green]git worktree add <path> <commit>[/green]
    Create new worktree at commit

  [green]git worktree remove <path>[/green]
    Remove a worktree

  [green]cd <worktree-path> && git log --oneline[/green]
    View commits in worktree

  [green]cd <worktree-path> && git diff <commit>[/green]
    Show diff in worktree

[bold]GGDes Commands:[/bold]

  [cyan]ggdes status[/cyan]
    Show all analyses

  [cyan]ggdes status <analysis-id>[/cyan]
    Show specific analysis details

  [cyan]ggdes cleanup <analysis-id>[/cyan]
    Remove worktrees

[bold]File Navigation:[/bold]

  [yellow]Tab[/yellow] - Switch between tabs
  [yellow]↑↓[/yellow] - Navigate lists
  [yellow]Enter[/yellow] - Select item
  [yellow]q[/yellow] - Quit
    """

    def compose(self) -> ComposeResult:
        yield Label(self.COMMANDS)


class AnalysisDetailView(Vertical):
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

        # Clear and rebuild
        self.remove_children()

        with self:
            yield Label(f"[bold]Analysis:[/bold] {metadata.name}")
            yield Label(f"ID: {analysis_id}")
            yield Label(f"Repo: {metadata.repo_path}")
            yield Label(f"Commits: {metadata.commit_range}")

            # Stages table
            table = DataTable()
            table.add_columns("Stage", "Status", "Duration")
            for stage_name, stage in metadata.stages.items():
                status = stage.status.value
                duration = ""
                if stage.started_at and stage.completed_at:
                    duration = str(stage.completed_at - stage.started_at)
                table.add_row(stage_name, status, duration)
            yield table

            # Worktree browser
            wt_manager = WorktreeManager(self.config, Path(metadata.repo_path))
            worktree_pair = wt_manager.get_existing(analysis_id)
            yield WorktreeBrowser(worktree_pair)


class GGDesTUI(App):
    """Main TUI application for GGDes."""

    CSS = """
    Screen {
        align: center middle;
    }

    #analysis-list {
        width: 30%;
        height: 100%;
        border: solid green;
    }

    #detail-view {
        width: 70%;
        height: 100%;
        border: solid blue;
    }

    #worktree-browser {
        border: solid yellow;
        padding: 1;
    }

    #command-help {
        border: solid cyan;
        padding: 1;
    }

    DataTable {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "help", "Help"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header()

        with TabbedContent():
            with TabPane("Analyses", id="analyses"):
                with Horizontal():
                    # Left: List of analyses
                    analyses = self.kb_manager.list_analyses()
                    analysis_list = [(aid, m.name) for aid, m in analyses]
                    list_view = AnalysisListView(analysis_list, id="analysis-list")
                    yield list_view

                    # Right: Detail view
                    yield AnalysisDetailView(id="detail-view")

            with TabPane("Worktrees", id="worktrees"):
                yield self._create_worktree_view()

            with TabPane("Help", id="help"):
                yield CommandHelp(id="command-help")

        yield Footer()

    def _create_worktree_view(self) -> Container:
        """Create the worktree management view."""
        wt_base = Path(self.config.paths.worktrees).expanduser()

        if not wt_base.exists():
            return Container(Label("[dim]No worktrees found[/dim]"))

        table = DataTable()
        table.add_columns("Analysis", "Base Path", "Head Path", "Actions")

        for analysis_dir in wt_base.iterdir():
            if analysis_dir.is_dir():
                base_path = analysis_dir / "base"
                head_path = analysis_dir / "head"
                if base_path.exists() and head_path.exists():
                    table.add_row(
                        analysis_dir.name,
                        str(base_path),
                        str(head_path),
                        "[View] [Delete]",
                    )

        return Container(
            Label("[bold]Active Worktrees[/bold]"),
            table,
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle analysis selection."""
        list_view = self.query_one("#analysis-list", AnalysisListView)
        if event.item_index < len(list_view.analyses):
            analysis_id = list_view.analyses[event.item_index][0]
            detail_view = self.query_one("#detail-view", AnalysisDetailView)
            detail_view.analysis_id = analysis_id

    def action_refresh(self) -> None:
        """Refresh the view."""
        self.refresh()

    def action_help(self) -> None:
        """Show help."""
        self.switch_mode("help")


def run_tui() -> None:
    """Run the TUI application."""
    app = GGDesTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
