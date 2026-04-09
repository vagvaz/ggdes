"""Terminal UI for GGDes using Textual."""

import subprocess
from collections.abc import Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)

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
            yield Label(f"[bold]{self.analysis_name}[/bold]")
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


class GitLogView(VerticalScroll):
    """View for browsing git commits and selecting commit ranges."""

    commits: reactive[list[dict]] = reactive([])
    start_commit: reactive[str | None] = reactive(None)
    end_commit: reactive[str | None] = reactive(None)
    focus_commits: reactive[set[str]] = reactive(set())

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, self.repo_path = load_config()

    def compose(self) -> ComposeResult:
        """Compose the git log view."""
        yield Label("[bold cyan]Git Commit Log[/bold cyan]")
        yield Label("")

        with Container(id="commit-range-panel"):
            yield Label("[bold]Selected Range:[/bold]")
            with Horizontal():
                yield Label("Start: ", id="start-label", classes="commit-label")
                yield Label(
                    "[dim]None[/dim]", id="start-commit", classes="commit-value"
                )
            with Horizontal():
                yield Label("End:   ", id="end-label", classes="commit-label")
                yield Label("[dim]None[/dim]", id="end-commit", classes="commit-value")
            with Horizontal():
                yield Label("Focus: ", id="focus-label", classes="commit-label")
                yield Label(
                    "[dim]None[/dim]", id="focus-commits", classes="commit-value"
                )

        yield Label("")

        with Horizontal(id="commit-actions"):
            yield Button("⛳ Set Start", id="set_start_btn", variant="primary")
            yield Button("🎯 Set End", id="set_end_btn", variant="primary")
            yield Button("🔍 Toggle Focus", id="toggle_focus_btn", variant="default")
            yield Button("🔄 Refresh", id="refresh_log_btn", variant="default")
            yield Button("🗑 Clear Selection", id="clear_btn", variant="error")

        yield Label("")
        yield Label("[bold]Commits:[/bold] (Use ↑↓ to navigate, Enter to select)")

        table = DataTable(id="commit-table", cursor_type="row")
        table.add_columns("Hash", "Date", "Author", "Message", "Type")
        yield table

        yield Label(
            "[dim]Navigation: ↑↓ to move, s=Start, e=End, f=Toggle Focus, Enter=Select[/dim]"
        )

    def on_mount(self) -> None:
        """Load commits when mounted."""
        self.load_commits()

    def load_commits(self, limit: int = 100) -> None:
        """Load git commits into the table."""
        try:
            cmd = [
                "git",
                "-C",
                str(self.repo_path),
                "log",
                "--format=%H|%ad|%an|%s|%D",
                "--date=short",
                f"-n{limit}",
                "--decorate",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            commits = []
            table = self.query_one("#commit-table", DataTable)
            table.clear()

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("|", 4)
                if len(parts) >= 4:
                    commit_hash = parts[0][:8]
                    date = parts[1]
                    author = parts[2][:20]
                    message = parts[3][:50]
                    refs = parts[4] if len(parts) > 4 else ""

                    msg_lower = parts[3].lower()
                    if any(x in msg_lower for x in ["fix", "bugfix", "hotfix"]):
                        commit_type = "[red]fix[/red]"
                    elif any(x in msg_lower for x in ["feat", "feature", "add"]):
                        commit_type = "[green]feat[/green]"
                    elif any(
                        x in msg_lower for x in ["refactor", "clean", "restructure"]
                    ):
                        commit_type = "[blue]ref[/blue]"
                    elif any(x in msg_lower for x in ["doc", "docs", "readme"]):
                        commit_type = "[cyan]doc[/cyan]"
                    elif any(x in msg_lower for x in ["test", "tests", "spec"]):
                        commit_type = "[yellow]test[/yellow]"
                    elif any(x in msg_lower for x in ["chore", "build", "ci"]):
                        commit_type = "[dim]chore[/dim]"
                    else:
                        commit_type = "[dim]—[/dim]"

                    ref_indicator = ""
                    if "HEAD" in refs:
                        ref_indicator = " [bold magenta]HEAD[/bold magenta]"
                    elif refs:
                        ref_indicator = " [dim]●[/dim]"

                    commits.append(
                        {
                            "hash": parts[0],
                            "short_hash": commit_hash,
                            "date": date,
                            "author": parts[2],
                            "message": parts[3],
                        }
                    )

                    table.add_row(
                        commit_hash + ref_indicator,
                        date,
                        author,
                        message,
                        commit_type,
                        key=parts[0],
                    )

            self.commits = commits
            self.update_selection_display()

        except subprocess.CalledProcessError as e:
            self.app.notify(
                f"Failed to load commits: {e.stderr}", title="Error", severity="error"
            )
        except Exception as e:
            self.app.notify(
                f"Error loading commits: {str(e)}", title="Error", severity="error"
            )

    def update_selection_display(self) -> None:
        """Update the selection status labels."""
        start_label = self.query_one("#start-commit", Label)
        end_label = self.query_one("#end-commit", Label)
        focus_label = self.query_one("#focus-commits", Label)

        if self.start_commit:
            short = self.start_commit[:8]
            start_label.update(f"[bold green]{short}[/bold green]")
        else:
            start_label.update("[dim]None[/dim]")

        if self.end_commit:
            short = self.end_commit[:8]
            end_label.update(f"[bold red]{short}[/bold red]")
        else:
            end_label.update("[dim]None[/dim]")

        if self.focus_commits:
            shorts = [c[:8] for c in sorted(self.focus_commits)]
            focus_text = ", ".join(f"[bold yellow]{s}[/bold yellow]" for s in shorts)
            focus_label.update(focus_text)
        else:
            focus_label.update("[dim]None[/dim]")

    def get_selected_commit(self) -> str | None:
        """Get the currently selected commit hash from the table."""
        table = self.query_one("#commit-table", DataTable)
        if table.cursor_row is not None:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key:
                return str(row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "refresh_log_btn":
            self.load_commits()
            self.app.notify("Commit log refreshed", title="Git Log")

        elif button_id == "clear_btn":
            self.start_commit = None
            self.end_commit = None
            self.focus_commits = set()
            self.update_selection_display()
            self.refresh_table_styles()
            self.app.notify("Selection cleared", title="Git Log")

        elif button_id == "set_start_btn":
            commit = self.get_selected_commit()
            if commit:
                self.start_commit = commit
                if not self.end_commit or self._commit_is_before(
                    self.end_commit, commit
                ):
                    self.end_commit = commit
                self.update_selection_display()
                self.refresh_table_styles()
                self.app.notify(f"Start commit set to {commit[:8]}", title="Git Log")
            else:
                self.app.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )

        elif button_id == "set_end_btn":
            commit = self.get_selected_commit()
            if commit:
                self.end_commit = commit
                if not self.start_commit or self._commit_is_before(
                    commit, self.start_commit
                ):
                    self.start_commit = commit
                self.update_selection_display()
                self.refresh_table_styles()
                self.app.notify(f"End commit set to {commit[:8]}", title="Git Log")
            else:
                self.app.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )

        elif button_id == "toggle_focus_btn":
            commit = self.get_selected_commit()
            if commit:
                if commit in self.focus_commits:
                    self.focus_commits.discard(commit)
                    self.app.notify(
                        f"Removed {commit[:8]} from focus commits", title="Git Log"
                    )
                else:
                    self.focus_commits.add(commit)
                    self.app.notify(
                        f"Added {commit[:8]} to focus commits", title="Git Log"
                    )
                self.update_selection_display()
                self.refresh_table_styles()
            else:
                self.app.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the table."""
        commit_hash = str(event.row_key.value)
        self._show_commit_details(commit_hash)

    def _show_commit_details(self, commit_hash: str) -> None:
        """Show details for a commit."""
        try:
            cmd = [
                "git",
                "-C",
                str(self.repo_path),
                "show",
                "-s",
                "--format=%H|%an|%ae|%ad|%s|%b",
                "--date=short",
                commit_hash,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            parts = result.stdout.strip().split("|", 5)
            if len(parts) >= 4:
                short_hash = parts[0][:8]
                message = f"[bold]{short_hash}[/bold]: {parts[3]}"
                self.app.notify(message, title="Commit Selected", timeout=3)

        except Exception:
            pass

    def _commit_is_before(self, commit1: str, commit2: str) -> bool:
        """Check if commit1 is an ancestor of commit2 (comes before it)."""
        try:
            cmd = [
                "git",
                "-C",
                str(self.repo_path),
                "merge-base",
                "--is-ancestor",
                commit1,
                commit2,
            ]
            result = subprocess.run(cmd, capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def refresh_table_styles(self) -> None:
        """Refresh the table row styles based on current selection."""
        table = self.query_one("#commit-table", DataTable)

        for row_key in table.rows:
            commit_hash = str(row_key.value)
            table.remove_row_style(row_key)

            if commit_hash == self.start_commit:
                table.add_row_style(row_key, "green")
            elif commit_hash == self.end_commit:
                table.add_row_style(row_key, "red")
            elif commit_hash in self.focus_commits:
                table.add_row_style(row_key, "yellow")

    def get_commit_range(self) -> str | None:
        """Get the selected commit range in git format (start..end)."""
        if self.start_commit and self.end_commit:
            return f"{self.start_commit}..{self.end_commit}"
        return None

    def get_focus_commits_list(self) -> list[str]:
        """Get the list of focus commits."""
        return list(self.focus_commits)


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

[bold cyan]Git Log Pane:[/bold cyan]

  [bold]s[/bold] - Set selected commit as START
  [bold]e[/bold] - Set selected commit as END
  [bold]f[/bold] - Toggle FOCUS on selected commit
  [bold]c[/bold] - Clear all selections

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


class ConfirmDialog(Screen):
    """Simple confirmation dialog."""

    def __init__(
        self,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        on_cancel: Callable[[], None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.message = message
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Label(f"[bold]{self.title}[/bold]", id="dialog-title")
            yield Label(self.message, id="dialog-message")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Confirm", id="confirm-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-btn":
            self.dismiss()
            self.on_confirm()
        else:
            self.dismiss()
            self.on_cancel()

    CSS = """
    #dialog-container {
        width: 60;
        height: auto;
        border: solid $primary;
        padding: 1 2;
        background: $surface;
    }
    #dialog-title {
        text-align: center;
        margin-bottom: 1;
    }
    #dialog-message {
        margin-bottom: 1;
    }
    #dialog-buttons {
        align: center middle;
        height: auto;
    }
    """


class NewAnalysisDialog(Screen):
    """Dialog for creating a new analysis."""

    def __init__(
        self,
        on_create: Callable[[str, str, list[str] | None, list[str]], None],
        commit_range: str = "",
        focus_commits: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.on_create = on_create
        self.commit_range = commit_range
        self.focus_commits = focus_commits or []

    def compose(self) -> ComposeResult:
        with Container(id="new-analysis-dialog"):
            yield Label("[bold]Create New Analysis[/bold]", id="dialog-title")

            yield Label("Name:", classes="field-label")
            yield Input(placeholder="e.g., Feature X Implementation", id="name-input")

            yield Label("Commit Range:", classes="field-label")
            yield Input(
                value=self.commit_range,
                placeholder="abc123..def456",
                id="range-input",
            )

            yield Label("Focus Commits (optional):", classes="field-label")
            focus_text = ",".join(c[:8] for c in self.focus_commits)
            yield Input(
                value=focus_text,
                placeholder="comma-separated commit hashes",
                id="focus-input",
            )

            yield Label("Output Formats:", classes="field-label")
            with Horizontal(id="formats-row"):
                yield Checkbox("Markdown", id="fmt-markdown", value=True)
                yield Checkbox("DOCX", id="fmt-docx")
                yield Checkbox("PDF", id="fmt-pdf")
                yield Checkbox("PPTX", id="fmt-pptx")

            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel-btn", variant="default")
                yield Button("Create", id="create-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "cancel-btn":
            self.dismiss()
            return

        # Get values from inputs
        name = self.query_one("#name-input", Input).value.strip()
        commit_range = self.query_one("#range-input", Input).value.strip()
        focus_text = self.query_one("#focus-input", Input).value.strip()

        # Validate
        if not name:
            self.notify("Please enter a name", severity="error")
            return
        if not commit_range:
            self.notify("Please enter a commit range", severity="error")
            return

        # Parse focus commits
        focus_commits = None
        if focus_text:
            focus_commits = [c.strip() for c in focus_text.split(",") if c.strip()]

        # Get selected formats
        formats = []
        if self.query_one("#fmt-markdown", Checkbox).value:
            formats.append("markdown")
        if self.query_one("#fmt-docx", Checkbox).value:
            formats.append("docx")
        if self.query_one("#fmt-pdf", Checkbox).value:
            formats.append("pdf")
        if self.query_one("#fmt-pptx", Checkbox).value:
            formats.append("pptx")

        if not formats:
            formats = ["markdown"]  # Default

        self.dismiss()
        self.on_create(name, commit_range, focus_commits, formats)

    CSS = """
    #new-analysis-dialog {
        width: 80;
        height: auto;
        border: solid $primary;
        padding: 1 2;
        background: $surface;
    }
    #dialog-title {
        text-align: center;
        margin-bottom: 1;
    }
    .field-label {
        margin-top: 1;
    }
    #formats-row {
        height: auto;
        margin-top: 1;
    }
    #dialog-buttons {
        align: center middle;
        height: auto;
        margin-top: 2;
    }
    """


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
    
    /* Git Log View Styles */
    #commit-range-panel {
        border: solid $primary;
        padding: 1;
        margin: 0 0 1 0;
    }
    
    .commit-label {
        width: 8;
    }
    
    .commit-value {
        width: auto;
    }
    
    #commit-actions {
        margin: 1 0;
    }
    
    #commit-table {
        height: 1fr;
        border: solid $primary-darken-2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("a", "new_analysis", "New Analysis", show=True),
        Binding("s", "gitlog_set_start", "Set Start Commit", show=True),
        Binding("e", "gitlog_set_end", "Set End Commit", show=True),
        Binding("f", "gitlog_toggle_focus", "Toggle Focus", show=True),
        Binding("c", "gitlog_clear", "Clear Selection", show=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header(show_clock=True)

        with TabbedContent():
            with TabPane("📊 Analyses", id="analyses"), Horizontal():
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

            with TabPane("📜 Git Log", id="gitlog"):
                yield GitLogView(id="git-log-view")

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
        """Start new analysis from TUI."""
        # Get the GitLog view to use its commit selection
        gitlog = self._get_gitlog_view()

        if gitlog and gitlog.start_commit and gitlog.end_commit:
            # Use selected commits from Git Log
            commit_range = f"{gitlog.start_commit}..{gitlog.end_commit}"
            focus_commits = list(gitlog.focus_commits) if gitlog.focus_commits else None

            # Show create analysis dialog
            self.push_screen(
                NewAnalysisDialog(
                    commit_range=commit_range,
                    focus_commits=focus_commits,
                    on_create=self._on_create_analysis,
                )
            )
        else:
            # Show dialog without pre-filled commits
            self.push_screen(
                NewAnalysisDialog(
                    on_create=self._on_create_analysis,
                )
            )

    def _on_create_analysis(
        self,
        name: str,
        commit_range: str,
        focus_commits: list[str] | None,
        formats: list[str],
    ) -> None:
        """Handle new analysis creation from dialog."""
        analysis_id = self._create_analysis(
            name=name,
            commit_range=commit_range,
            focus_commits=focus_commits,
            formats=formats,
        )

        if analysis_id:
            # Ask if user wants to run it now
            self.push_screen(
                ConfirmDialog(
                    title="Run Analysis?",
                    message=f"Run '{name}' now?\n\nCommit range: {commit_range[:50]}...",
                    on_confirm=lambda: self._resume_analysis(analysis_id),
                    on_cancel=lambda: None,
                )
            )

    def _get_gitlog_view(self) -> GitLogView | None:
        """Get the git log view if it exists."""
        try:
            return self.query_one("#git-log-view", GitLogView)
        except Exception:
            return None

    def action_gitlog_set_start(self) -> None:
        """Set the current commit as start (keyboard shortcut)."""
        gitlog = self._get_gitlog_view()
        if gitlog:
            commit = gitlog.get_selected_commit()
            if commit:
                gitlog.start_commit = commit
                if not gitlog.end_commit or gitlog._commit_is_before(
                    gitlog.end_commit, commit
                ):
                    gitlog.end_commit = commit
                gitlog.update_selection_display()
                gitlog.refresh_table_styles()
                self.notify(f"Start commit set to {commit[:8]}", title="Git Log")
            else:
                self.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )
        else:
            self.notify(
                "Switch to Git Log tab to use this command",
                title="Git Log",
                severity="warning",
            )

    def action_gitlog_set_end(self) -> None:
        """Set the current commit as end (keyboard shortcut)."""
        gitlog = self._get_gitlog_view()
        if gitlog:
            commit = gitlog.get_selected_commit()
            if commit:
                gitlog.end_commit = commit
                if not gitlog.start_commit or gitlog._commit_is_before(
                    commit, gitlog.start_commit
                ):
                    gitlog.start_commit = commit
                gitlog.update_selection_display()
                gitlog.refresh_table_styles()
                self.notify(f"End commit set to {commit[:8]}", title="Git Log")
            else:
                self.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )
        else:
            self.notify(
                "Switch to Git Log tab to use this command",
                title="Git Log",
                severity="warning",
            )

    def action_gitlog_toggle_focus(self) -> None:
        """Toggle focus for current commit (keyboard shortcut)."""
        gitlog = self._get_gitlog_view()
        if gitlog:
            commit = gitlog.get_selected_commit()
            if commit:
                if commit in gitlog.focus_commits:
                    gitlog.focus_commits.discard(commit)
                    self.notify(
                        f"Removed {commit[:8]} from focus commits", title="Git Log"
                    )
                else:
                    gitlog.focus_commits.add(commit)
                    self.notify(f"Added {commit[:8]} to focus commits", title="Git Log")
                gitlog.update_selection_display()
                gitlog.refresh_table_styles()
            else:
                self.notify(
                    "Please select a commit first", title="Git Log", severity="warning"
                )
        else:
            self.notify(
                "Switch to Git Log tab to use this command",
                title="Git Log",
                severity="warning",
            )

    def action_gitlog_clear(self) -> None:
        """Clear all git log selections."""
        gitlog = self._get_gitlog_view()
        if gitlog:
            gitlog.start_commit = None
            gitlog.end_commit = None
            gitlog.focus_commits = set()
            gitlog.update_selection_display()
            gitlog.refresh_table_styles()
            self.notify("Selection cleared", title="Git Log")
        else:
            self.notify(
                "Switch to Git Log tab to use this command",
                title="Git Log",
                severity="warning",
            )

    def _resume_analysis(self, analysis_id: str) -> None:
        """Resume an analysis by running the pipeline."""
        from ggdes.pipeline import AnalysisPipeline

        self.notify(f"Resuming analysis {analysis_id[:20]}...", title="Resume")

        try:
            pipeline = AnalysisPipeline(self.config, analysis_id)
            success = pipeline.run_all_pending()

            if success:
                self.notify(
                    f"Analysis {analysis_id[:20]}... completed successfully!",
                    title="Resume",
                    severity="information",
                )
            else:
                self.notify(
                    f"Analysis {analysis_id[:20]}... incomplete. Check CLI for details.",
                    title="Resume",
                    severity="warning",
                )

            # Refresh the UI
            self.refresh()

        except Exception as e:
            self.notify(
                f"Failed to resume: {str(e)[:100]}",
                title="Resume Error",
                severity="error",
            )

    def _delete_analysis(self, analysis_id: str) -> None:
        """Delete an analysis after confirmation."""

        # Get analysis metadata for the name
        metadata = self.kb_manager.load_metadata(analysis_id)
        if not metadata:
            self.notify("Analysis not found", title="Delete", severity="error")
            return

        analysis_name = metadata.name

        # Show confirmation dialog
        def confirm_delete(confirmed: bool) -> None:
            if not confirmed:
                self.notify("Delete cancelled", title="Delete")
                return

            try:
                # Clean up worktrees first
                wt_manager = WorktreeManager(self.config, Path(metadata.repo_path))
                wt_manager.cleanup(analysis_id)

                # Delete from knowledge base
                deleted = self.kb_manager.delete_analysis(analysis_id)

                if deleted:
                    self.notify(
                        f"Analysis '{analysis_name}' deleted",
                        title="Delete",
                        severity="information",
                    )
                    # Clear the detail view and refresh
                    detail_view = self.query_one("#detail-view", AnalysisDetailView)
                    detail_view.analysis_id = None
                    self.refresh()
                else:
                    self.notify(
                        "Analysis not found in knowledge base",
                        title="Delete",
                        severity="warning",
                    )

            except Exception as e:
                self.notify(
                    f"Failed to delete: {str(e)[:100]}",
                    title="Delete Error",
                    severity="error",
                )

        # Use a simple notification with action buttons pattern
        self.app.push_screen(
            ConfirmDialog(
                title="Delete Analysis",
                message=f"Delete '{analysis_name}'?\n\nThis will remove:\n- Analysis data\n- Generated documents\n- Worktrees",
                on_confirm=lambda: confirm_delete(True),
                on_cancel=lambda: confirm_delete(False),
            )
        )

    def _create_analysis(
        self,
        name: str,
        commit_range: str,
        focus_commits: list[str] | None = None,
        formats: list[str] | None = None,
    ) -> str | None:
        """Create a new analysis.

        Args:
            name: Analysis name
            commit_range: Git commit range (e.g., "abc123..def456")
            focus_commits: Optional list of focus commits
            formats: Optional list of target formats

        Returns:
            Analysis ID if created successfully, None otherwise
        """
        import uuid

        try:
            # Generate analysis ID
            analysis_id = str(uuid.uuid4())

            # Default formats
            target_formats = formats or ["markdown"]

            # Create analysis in KB
            metadata = self.kb_manager.create_analysis(
                analysis_id=analysis_id,
                name=name,
                repo_path=self.config.repo_path or Path.cwd(),
                commit_range=commit_range,
                focus_commits=focus_commits,
                target_formats=target_formats,
            )

            self.notify(
                f"Analysis '{name}' created",
                title="New Analysis",
                severity="information",
            )

            return analysis_id

        except Exception as e:
            self.notify(
                f"Failed to create analysis: {str(e)[:100]}",
                title="New Analysis Error",
                severity="error",
            )
            return None


def run_tui() -> None:
    """Run the TUI application."""
    app = GGDesTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
