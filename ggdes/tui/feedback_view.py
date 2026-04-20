"""Feedback tab for GGDes TUI — section-level feedback and live output viewer."""

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Label,
    RichLog,
    Select,
    TextArea,
    Tree,
)

from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager


class SectionFeedbackPanel(Vertical):
    """Left panel: document section tree with per-section feedback input."""

    analysis_id: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self.poll_timer: Any = None
        self._current_sections: list[dict[str, Any]] = []
        self._feedback_inputs: dict[str, TextArea] = {}

    def compose(self) -> ComposeResult:
        yield Label("[bold]📄 Document Sections[/bold]")
        yield Label("[dim]Select an analysis to view sections[/dim]")
        with VerticalScroll(id="sections-scroll"):
            yield Label("[dim]No sections loaded yet[/dim]", id="sections-placeholder")

    def on_mount(self) -> None:
        self.poll_timer = self.set_interval(3, self.poll_for_plan)

    def on_unmount(self) -> None:
        if self.poll_timer:
            self.poll_timer.stop()

    def watch_analysis_id(self, analysis_id: str | None) -> None:
        """Load sections when analysis changes."""
        if analysis_id:
            self.load_sections(analysis_id)

    def poll_for_plan(self) -> None:
        """Poll for new or updated document plan."""
        if not self.analysis_id:
            return
        plan = self.kb_manager.load_document_plan(self.analysis_id)
        if plan and plan.get("sections"):
            # Check if sections changed
            new_sections = plan["sections"]
            if len(new_sections) != len(self._current_sections):
                self._current_sections = new_sections
                self.load_sections(self.analysis_id)

    def load_sections(self, analysis_id: str) -> None:
        """Load document sections from the plan."""
        self._current_sections = []
        self._feedback_inputs.clear()

        plan = self.kb_manager.load_document_plan(analysis_id)
        if not plan or not plan.get("sections"):
            placeholder = self.query_one("#sections-placeholder", Label)
            placeholder.update(
                "[dim]No document plan yet. Run an analysis first.[/dim]"
            )
            return

        self._current_sections = plan["sections"]
        plan_title = plan.get("title", "Untitled")

        # Load existing feedback
        existing_feedback = self.kb_manager.load_section_feedback(analysis_id)

        # Clear placeholder
        scroll = self.query_one("#sections-scroll", VerticalScroll)
        scroll.remove_children()

        # Plan title
        scroll.mount(Label(f"[bold cyan]{plan_title}[/bold cyan]"))
        scroll.mount(Label(""))

        # Section feedback blocks
        for i, section in enumerate(self._current_sections):
            title = section.get("title", f"Section {i + 1}")
            desc = section.get("description", "")
            prev_feedback = existing_feedback.get(title, "")

            block = Vertical(classes="section-feedback-block")
            block.mount(Label(f"[bold]{i + 1}. {title}[/bold]"))
            if desc:
                block.mount(Label(f"[dim]{desc}[/dim]"))

            feedback_area = TextArea(
                text=prev_feedback,
                placeholder="Feedback for this section...",
                language="markdown",
                id=f"feedback_{i}",
                classes="section-feedback-input",
            )
            self._feedback_inputs[title] = feedback_area
            block.mount(feedback_area)
            block.mount(Label(""))
            scroll.mount(block)

    def save_all_feedback(self) -> int:
        """Save all feedback inputs to KB. Returns count of non-empty feedbacks."""
        if not self.analysis_id:
            return 0
        count = 0
        for title, textarea in self._feedback_inputs.items():
            text = textarea.text.strip()
            if text:
                self.kb_manager.save_section_feedback(self.analysis_id, title, text)
                count += 1
        return count


class LiveOutputViewer(Vertical):
    """Right panel: live output file browser with auto-refresh."""

    analysis_id: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self.file_mtimes: dict[str, float] = {}
        self.poll_timer: Any = None
        self.tree_built = False

    def compose(self) -> ComposeResult:
        yield Label("[bold]📁 Live Output Files[/bold]")
        with Horizontal():
            # File tree
            with Vertical(classes="output-file-tree"):
                yield Tree("Outputs", id="output-file-tree")
            # Content viewer
            with VerticalScroll(classes="output-content"):
                yield RichLog(id="output-content", wrap=True, highlight=True)

    def on_mount(self) -> None:
        self.poll_timer = self.set_interval(3, self.poll_for_new_files)

    def on_unmount(self) -> None:
        if self.poll_timer:
            self.poll_timer.stop()

    def on_tree_node_selected(self, event: Tree.NodeSelected[None]) -> None:
        """Handle file selection in tree."""
        node = event.node
        file_path = node.data
        if file_path and isinstance(file_path, str) and Path(file_path).is_file():
            self._show_file_content(Path(file_path))

    def watch_analysis_id(self, analysis_id: str | None) -> None:
        """Load outputs when analysis changes."""
        if analysis_id:
            self.load_outputs(analysis_id)

    def poll_for_new_files(self) -> None:
        """Poll for new or modified output files."""
        if not self.analysis_id:
            return
        analysis_path = self.kb_manager.get_analysis_path(self.analysis_id)
        if not analysis_path.exists():
            return

        has_changes = False
        for dir_path in analysis_path.rglob("*"):
            if dir_path.is_file() and dir_path.suffix in (
                ".json",
                ".md",
                ".txt",
                ".yaml",
                ".yml",
            ):
                current_mtime = dir_path.stat().st_mtime
                last_mtime = self.file_mtimes.get(str(dir_path), 0)
                if current_mtime > last_mtime:
                    self.file_mtimes[str(dir_path)] = current_mtime
                    has_changes = True

        if has_changes and self.tree_built:
            self.load_outputs(self.analysis_id, force_refresh=True)

    def load_outputs(self, analysis_id: str, force_refresh: bool = False) -> None:
        """Load output file tree for analysis."""
        if not force_refresh and self.analysis_id == analysis_id and self.tree_built:
            return

        self.analysis_id = analysis_id
        analysis_path = self.kb_manager.get_analysis_path(analysis_id)
        tree = self.query_one("#output-file-tree", Tree)
        tree.clear()

        if not analysis_path.exists():
            tree.root.add("[dim]No outputs found[/dim]")
            return

        root = tree.root
        root.set_label("Outputs")

        # Build tree from directory structure
        self._build_tree(analysis_path, root, analysis_path)

        tree.root.expand_all()
        self.tree_built = True

    def _build_tree(self, path: Path, parent: Any, base_path: Path) -> None:
        """Recursively build file tree."""
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                node = parent.add(f"📁 {entry.name}", data=str(entry))
                self._build_tree(entry, node, base_path)
            elif entry.suffix in (".json", ".md", ".txt", ".yaml", ".yml"):
                parent.add(f"📄 {entry.name}", data=str(entry))

    def _show_file_content(self, file_path: Path) -> None:
        """Display file content in the RichLog viewer."""
        content_log = self.query_one("#output-content", RichLog)
        content_log.clear()

        content_log.write(f"[bold]{file_path.name}[/bold]\n")
        content_log.write("[dim]" + "─" * 60 + "[/dim]\n")

        try:
            text = file_path.read_text()
            if file_path.suffix == ".json":
                try:
                    parsed = json.loads(text)
                    text = json.dumps(parsed, indent=2)
                except json.JSONDecodeError:
                    pass
            content_log.write(text)
        except Exception as e:
            content_log.write(f"[red]Error reading file: {e}[/red]")


class FeedbackView(Vertical):
    """Main Feedback tab widget combining section feedback and live output viewer."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self._analyses: list[tuple[str, Any]] = []  # (id, metadata)

    def compose(self) -> ComposeResult:
        yield Label("[bold]📝 Section Feedback & Live Output[/bold]")
        yield Label("")

        # Analysis selector
        with Horizontal(classes="feedback-selector"):
            yield Label("[bold]Analysis:[/bold]")
            yield Select([], id="analysis-select", allow_blank=True)

        with Horizontal():
            # Left: Section feedback (40%)
            with Vertical(classes="feedback-left-panel"):
                yield SectionFeedbackPanel(id="section-feedback-panel")
                with Horizontal(classes="feedback-actions"):
                    yield Button(
                        "💾 Save All Feedback", id="save-feedback", variant="primary"
                    )
                    yield Label("", id="save-status")

            # Right: Live output viewer (60%)
            yield LiveOutputViewer(id="live-output-viewer")

    def on_mount(self) -> None:
        self._populate_analysis_selector()

    def on_select_selected(self, event: Select.Changed) -> None:
        """Handle analysis selection."""
        if event.select.id == "analysis-select":
            value = event.value
            if value and value != Select.BLANK:
                analysis_id = str(value)
                section_panel = self.query_one(
                    "#section-feedback-panel", SectionFeedbackPanel
                )
                section_panel.analysis_id = analysis_id
                output_viewer = self.query_one("#live-output-viewer", LiveOutputViewer)
                output_viewer.analysis_id = analysis_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle save button."""
        if event.button.id == "save-feedback":
            section_panel = self.query_one(
                "#section-feedback-panel", SectionFeedbackPanel
            )
            count = section_panel.save_all_feedback()
            status = self.query_one("#save-status", Label)
            status.update(f"[green]✓ Saved {count} feedback entries[/green]")
            self.app.notify(
                f"Saved {count} feedback entries",
                title="Feedback Saved",
                severity="information",
            )

    def _populate_analysis_selector(self) -> None:
        """Load available analyses into the selector."""
        self._analyses = self.kb_manager.list_analyses()
        select = self.query_one("#analysis-select", Select)
        options = [(str(name), str(aid)) for aid, name in self._analyses]
        select.set_options(options)
