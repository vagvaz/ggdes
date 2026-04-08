"""Debug TUI view for browsing agent conversations and outputs with live monitoring."""

import json
from pathlib import Path
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.message import Message
from textual.widget import Widget

from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager, StageStatus


class AnalysisSelected(Message):
    """Message sent when an analysis is selected."""

    def __init__(self, analysis_id: str) -> None:
        super().__init__()
        self.analysis_id = analysis_id


class LiveIndicator(Static):
    """Indicator showing if analysis is running."""

    is_live: reactive[bool] = reactive(False)
    current_stage: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("● [dim]Idle[/dim]", id="live-status")

    def watch_is_live(self, is_live: bool) -> None:
        """Update indicator when live status changes."""
        status = self.query_one("#live-status", Label)
        if is_live:
            stage_info = f" - {self.current_stage}" if self.current_stage else ""
            status.update(f"[blink bold green]● LIVE{stage_info}[/blink bold green]")
        else:
            status.update("● [dim]Idle[/dim]")

    def watch_current_stage(self, stage: str) -> None:
        """Update when stage changes."""
        if self.is_live:
            status = self.query_one("#live-status", Label)
            status.update(f"[blink bold green]● LIVE - {stage}[/blink bold green]")


class ConversationMessage(Static):
    """Widget displaying a single conversation message."""

    def __init__(self, role: str, content: str, index: int, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.content = content
        self.index = index

    def compose(self) -> ComposeResult:
        # Role badge
        role_colors = {
            "system": "blue",
            "user": "green",
            "assistant": "magenta",
        }
        color = role_colors.get(self.role, "white")

        with Container(classes="message-container"):
            yield Label(
                f"[{color} bold]{self.role.upper()}[/{color} bold]",
                classes="message-role",
            )
            # Truncate content for preview
            preview = self.content[:500] if len(self.content) > 500 else self.content
            if len(self.content) > 500:
                preview += "..."
            yield Label(preview, classes="message-content")


class ConversationBrowser(Vertical):
    """Browser for agent conversations with live monitoring."""

    analysis_id: reactive[str | None] = reactive(None)
    selected_agent: reactive[str | None] = reactive(None)
    selected_message: reactive[int | None] = reactive(None)
    follow_mode: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self.conversation_data = None
        self.agents = []
        self.file_mtimes = {}  # Track file modification times
        self.current_agent_file = None
        self.poll_timer = None
        self.last_message_count = 0

    def compose(self) -> ComposeResult:
        with Horizontal(classes="browser-container"):
            # Left sidebar: Agent list
            with Vertical(classes="agent-list-panel"):
                yield Label("[bold]Agents[/bold]")
                yield ListView(
                    ListItem(Label("[dim]Loading...[/dim]")), id="agent-list"
                )

            # Middle: Message list with controls
            with Vertical(classes="message-list-panel"):
                yield Label("[bold]Messages[/bold]")
                with Horizontal(classes="message-controls"):
                    yield Checkbox("Follow", id="follow-checkbox", value=False)
                yield Label("[dim]Select an agent[/dim]", id="agent-info")
                yield ListView(
                    ListItem(Label("[dim]No messages[/dim]")), id="message-list"
                )

            # Right: Message detail
            with Vertical(classes="message-detail-panel"):
                yield Label("[bold]Message Detail[/bold]")
                with VerticalScroll(id="message-detail"):
                    yield Label("[dim]Select a message to view[/dim]")

    def on_mount(self) -> None:
        """Start polling when mounted."""
        self.poll_timer = self.set_interval(2, self.poll_for_updates)
        # If analysis_id is already set, load conversations
        if self.analysis_id:
            self.load_conversations(self.analysis_id)

    def on_unmount(self) -> None:
        """Stop polling when unmounted."""
        if self.poll_timer:
            self.poll_timer.stop()

    def watch_analysis_id(self, analysis_id: str | None) -> None:
        """Load conversations when analysis changes."""
        if analysis_id:
            self.app.notify(
                f"ConversationBrowser: Loading {analysis_id[:8]}...", title="Debug Flow"
            )
            self.load_conversations(analysis_id)

    def watch_follow_mode(self, follow: bool) -> None:
        """Handle follow mode toggle."""
        self.follow_mode = follow

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle follow checkbox."""
        if event.checkbox.id == "follow-checkbox":
            self.follow_mode = event.value

    def poll_for_updates(self) -> None:
        """Poll for conversation updates."""
        if not self.analysis_id or not self.selected_agent:
            return

        # Find the file for the currently selected agent
        agent_file = None
        for name, file_path, storage_type in self.agents:
            if name == self.selected_agent:
                agent_file = file_path
                break

        if not agent_file or not agent_file.exists():
            return

        # Check if file has been modified
        current_mtime = agent_file.stat().st_mtime
        last_mtime = self.file_mtimes.get(str(agent_file), 0)

        if current_mtime > last_mtime:
            self.file_mtimes[str(agent_file)] = current_mtime
            self.refresh_agent_conversation()

    def refresh_agent_conversation(self) -> None:
        """Refresh the current agent's conversation."""
        if not self.selected_agent:
            return

        # Reload conversation data
        for name, file_path, storage_type in self.agents:
            if name == self.selected_agent:
                try:
                    new_data = json.loads(file_path.read_text())
                    new_count = len(new_data.get("messages", []))

                    # Only update if there are new messages
                    if new_count > self.last_message_count:
                        self.conversation_data = new_data
                        self.update_message_list(new_count)
                        self.last_message_count = new_count

                        # If in follow mode, scroll to latest message
                        if self.follow_mode and new_count > 0:
                            self.show_message_detail(new_count - 1)
                            # Select the last message in the list
                            message_list = self.query_one("#message-list", ListView)
                            message_list.index = new_count - 1
                except Exception:
                    pass
                break

    def update_message_list(self, total_messages: int) -> None:
        """Update the message list with new messages."""
        message_list = self.query_one("#message-list", ListView)
        current_count = len(message_list.children)

        messages = self.conversation_data.get("messages", [])

        # Add only new messages
        for i in range(current_count, total_messages):
            msg = messages[i]
            role = msg.get("role", "unknown")
            content_preview = msg.get("content", "")[:60].replace("\n", " ")
            if len(msg.get("content", "")) > 60:
                content_preview += "..."

            label = f"{i + 1}. [{role}] {content_preview}"
            list_item = ListItem(Label(label))
            list_item.index = i
            message_list.append(list_item)

        # Update info label
        info_label = self.query_one("#agent-info", Label)
        total_tokens = self.conversation_data.get("total_tokens", 0)
        info_label.update(
            f"[dim]{total_messages} messages, {total_tokens} tokens[/dim]"
        )

    def load_conversations(self, analysis_id: str) -> None:
        """Load conversation data for analysis."""
        self.analysis_id = analysis_id
        self.agents = []
        self.file_mtimes = {}

        # Find conversation files
        analysis_path = self.kb_manager.get_analysis_path(analysis_id)
        conversations_path = analysis_path / "conversations"

        # Debug: Show the path being checked
        self.app.notify(
            f"Checking: {conversations_path}", title="Debug Path", timeout=3
        )

        if not conversations_path.exists():
            # Show a message in the agent list
            list_view = self.query_one("#agent-list", ListView)
            list_view.clear()
            list_view.append(
                ListItem(
                    Label(f"[dim]No conversations at:[/dim]\n{conversations_path}")
                )
            )
            return

        # Scan for agents and track file times
        agent_count = 0
        for conv_dir in conversations_path.iterdir():
            if conv_dir.is_dir():
                agent_name = conv_dir.name
                raw_file = conv_dir / "conversation_raw.json"
                summary_file = conv_dir / "conversation_summary.json"

                try:
                    if raw_file.exists():
                        self.agents.append((agent_name, raw_file, "raw"))
                        self.file_mtimes[str(raw_file)] = raw_file.stat().st_mtime
                        agent_count += 1
                    elif summary_file.exists():
                        self.agents.append((agent_name, summary_file, "summary"))
                        self.file_mtimes[str(summary_file)] = (
                            summary_file.stat().st_mtime
                        )
                        agent_count += 1
                except Exception as e:
                    self.app.notify(
                        f"Error loading {agent_name}: {e}",
                        severity="error",
                        title="Debug",
                    )

        self.update_agent_list()

        # Refresh the widget to ensure content is displayed
        self.refresh(layout=True)

        # Notify user
        if agent_count > 0:
            self.app.notify(
                f"Loaded {agent_count} agent conversation(s)", title="Debug"
            )
        else:
            self.app.notify("No conversations found for this analysis", title="Debug")

    def update_agent_list(self) -> None:
        """Update the agent list view."""
        list_view = self.query_one("#agent-list", ListView)
        list_view.clear()

        if not self.agents:
            list_view.append(ListItem(Label("[dim]No conversations found[/dim]")))
            list_view.refresh(layout=True)
            return

        for agent_name, _, storage_type in self.agents:
            label = f"{agent_name} [dim]({storage_type})[/dim]"
            list_view.append(ListItem(Label(label), name=agent_name))

        # Ensure ListView is refreshed to show new items
        list_view.refresh(layout=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle agent selection."""
        list_view = event.list_view

        if list_view.id == "agent-list":
            item = event.item
            if hasattr(item, "name"):
                self.load_agent_conversation(item.name)
        elif list_view.id == "message-list":
            # Use the list view's index property to get the selected index
            selected_index = list_view.index
            if selected_index is not None and selected_index >= 0:
                self.show_message_detail(selected_index)
                # Disable follow mode when manually selecting
                if self.follow_mode:
                    self.follow_mode = False
                    checkbox = self.query_one("#follow-checkbox", Checkbox)
                    checkbox.value = False

    def load_agent_conversation(self, agent_name: str) -> None:
        """Load conversation for selected agent."""
        self.selected_agent = agent_name
        self.last_message_count = 0

        # Find agent data
        agent_data = None
        agent_file = None
        for name, file_path, storage_type in self.agents:
            if name == agent_name:
                try:
                    agent_data = json.loads(file_path.read_text())
                    agent_file = file_path
                    break
                except Exception:
                    pass

        if not agent_data:
            return

        self.conversation_data = agent_data
        self.current_agent_file = agent_file

        # Update agent info
        info_label = self.query_one("#agent-info", Label)
        message_count = len(agent_data.get("messages", []))
        total_tokens = agent_data.get("total_tokens", 0)
        self.last_message_count = message_count
        info_label.update(f"[dim]{message_count} messages, {total_tokens} tokens[/dim]")

        # Update message list
        message_list = self.query_one("#message-list", ListView)
        message_list.clear()

        messages = agent_data.get("messages", [])
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content_preview = msg.get("content", "")[:60].replace("\n", " ")
            if len(msg.get("content", "")) > 60:
                content_preview += "..."

            label = f"{i + 1}. [{role}] {content_preview}"
            list_item = ListItem(Label(label))
            list_item.index = i
            message_list.append(list_item)

        if not messages:
            message_list.append(ListItem(Label("[dim]No messages[/dim]")))

    def show_message_detail(self, message_index: int) -> None:
        """Show full message content."""
        if not self.conversation_data:
            return

        messages = self.conversation_data.get("messages", [])
        if message_index >= len(messages):
            return

        msg = messages[message_index]
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Update detail view
        detail = self.query_one("#message-detail", VerticalScroll)
        detail.remove_children()

        # Mount widgets directly instead of using yield
        role_colors = {
            "system": "blue",
            "user": "green",
            "assistant": "magenta",
        }
        color = role_colors.get(role, "white")
        detail.mount(
            Label(
                f"[{color} bold]{role.upper()} - Message {message_index + 1}[/{color} bold]"
            )
        )
        detail.mount(Label(""))

        # Show content with scroll
        content_widget = RichLog(wrap=True, highlight=True)
        content_widget.write(content)
        detail.mount(content_widget)


class OutputsBrowser(Vertical):
    """Browser for analysis outputs (AST, git analysis, etc.) with live updates."""

    analysis_id: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self.file_mtimes = {}
        self.poll_timer = None
        self.tree_built = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="browser-container"):
            # Left: File tree
            with Vertical(classes="file-tree-panel"):
                with Horizontal(classes="outputs-header"):
                    yield Label("[bold]Output Files[/bold]")
                    yield Button("🔄 Refresh", id="refresh-outputs", variant="default")
                yield Tree("Analysis Outputs", id="file-tree")

            # Right: Content viewer
            with Vertical(classes="content-viewer-panel"):
                yield Label("[bold]Content[/bold]")
                with VerticalScroll(id="content-viewer"):
                    yield Label("[dim]Select a file to view[/dim]")

    def on_mount(self) -> None:
        """Start polling when mounted."""
        self.poll_timer = self.set_interval(3, self.poll_for_new_files)
        # If analysis_id is already set, load outputs
        if self.analysis_id:
            self.load_outputs(self.analysis_id)

    def on_unmount(self) -> None:
        """Stop polling when unmounted."""
        if self.poll_timer:
            self.poll_timer.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-outputs":
            if self.analysis_id:
                self.load_outputs(self.analysis_id, force_refresh=True)

    def watch_analysis_id(self, analysis_id: str | None) -> None:
        """Load outputs when analysis changes."""
        if analysis_id:
            self.load_outputs(analysis_id)

    def poll_for_new_files(self) -> None:
        """Poll for new or modified files."""
        if not self.analysis_id:
            return

        analysis_path = self.kb_manager.get_analysis_path(self.analysis_id)
        if not analysis_path.exists():
            return

        has_changes = False

        # Check for new or modified files
        for dir_path in analysis_path.rglob("*"):
            if dir_path.is_file() and dir_path.suffix in [".json", ".md", ".txt"]:
                current_mtime = dir_path.stat().st_mtime
                last_mtime = self.file_mtimes.get(str(dir_path), 0)

                if current_mtime > last_mtime:
                    self.file_mtimes[str(dir_path)] = current_mtime
                    has_changes = True

        # If we detect changes and tree was already built, refresh it
        if has_changes and self.tree_built:
            self.load_outputs(self.analysis_id, force_refresh=True)

    def load_outputs(self, analysis_id: str, force_refresh: bool = False) -> None:
        """Load output files for analysis."""
        if not force_refresh and self.analysis_id == analysis_id and self.tree_built:
            return

        self.analysis_id = analysis_id
        analysis_path = self.kb_manager.get_analysis_path(analysis_id)

        file_tree = self.query_one("#file-tree", Tree)

        if not force_refresh:
            file_tree.clear()

        if not analysis_path.exists():
            if not force_refresh:
                file_tree.root.add("[dim]No outputs found[/dim]")
            return

        # Build tree
        self._build_tree(file_tree, analysis_path, force_refresh)
        self.tree_built = True

        if not force_refresh:
            file_tree.root.expand()

    def _build_tree(self, file_tree, analysis_path: Path, force_refresh: bool) -> None:
        """Build the file tree."""
        # Define output directories with their display names
        output_dirs = {
            "git_analysis": "📊 Git Analysis",
            "ast_base": "🔍 AST (Base)",
            "ast_head": "🔍 AST (Head)",
            "conversations": "💬 Conversations",
            "facts": "📚 Facts",
            "plans": "📋 Plans",
            "output": "📄 Output",
        }

        if not force_refresh:
            # Initial build
            for dir_name, display_name in output_dirs.items():
                dir_path = analysis_path / dir_name
                if dir_path.exists():
                    node = file_tree.root.add(display_name)
                    self._add_files_to_tree(node, dir_path, dir_path)
        else:
            # Refresh - rebuild from scratch for simplicity
            file_tree.clear()
            for dir_name, display_name in output_dirs.items():
                dir_path = analysis_path / dir_name
                if dir_path.exists():
                    node = file_tree.root.add(display_name)
                    self._add_files_to_tree(node, dir_path, dir_path)
            file_tree.root.expand_all()

    def _add_files_to_tree(self, node, dir_path: Path, base_path: Path) -> None:
        """Recursively add files to tree."""
        try:
            items = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name))

            for item in items:
                rel_path = item.relative_to(base_path)

                if item.is_dir():
                    child_node = node.add(f"📁 {item.name}")
                    self._add_files_to_tree(child_node, item, base_path)
                elif item.suffix == ".json":
                    file_node = node.add_leaf(f"📄 {item.name}")
                    file_node.data = {"path": str(item), "type": "json"}
                elif item.suffix in [".md", ".txt"]:
                    file_node = node.add_leaf(f"📝 {item.name}")
                    file_node.data = {"path": str(item), "type": "text"}
                else:
                    file_node = node.add_leaf(f"📎 {item.name}")
                    file_node.data = {"path": str(item), "type": "other"}
        except PermissionError:
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle file selection."""
        node = event.node

        if hasattr(node, "data") and node.data:
            self.show_file_content(node.data["path"], node.data["type"])

    def show_file_content(self, file_path: str, file_type: str) -> None:
        """Show file content in viewer."""
        viewer = self.query_one("#content-viewer", VerticalScroll)
        viewer.remove_children()

        try:
            path = Path(file_path)
            content = path.read_text()

            if file_type == "json":
                # Pretty print JSON
                try:
                    data = json.loads(content)
                    content = json.dumps(data, indent=2)
                except json.JSONDecodeError:
                    pass

            # Show in RichLog for better formatting
            with viewer:
                yield Label(f"[dim]{file_path}[/dim]")
                yield Label("")
                log_widget = RichLog(wrap=True, highlight=True, max_lines=1000)
                log_widget.write(content[:50000])  # Limit size
                yield log_widget

        except Exception as e:
            with viewer:
                yield Label(f"[red]Error reading file: {e}[/red]")


class AnalysisSelector(Vertical):
    """Widget to select an analysis for debugging with live status."""

    selected_analysis: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config, _ = load_config()
        self.kb_manager = KnowledgeBaseManager(self.config)
        self.poll_timer = None
        self.live_indicator = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="analysis-selector-header"):
            yield Label("[bold cyan]Select Analysis to Debug[/bold cyan]")
            self.live_indicator = LiveIndicator()
            yield self.live_indicator

        yield Label("")

        analyses = self.kb_manager.list_analyses()

        if not analyses:
            yield Label("[dim]No analyses found. Create one first.[/dim]")
            return

        items = []
        for aid, metadata in analyses:
            # Get status indicator
            status = self._get_analysis_status(metadata)
            label = f"{metadata.name} {status} [dim]({aid[:20]}...)[/dim]"
            items.append((label, aid))

        yield Select(items, id="analysis-select", prompt="Select analysis...")

    def _get_analysis_status(self, metadata) -> str:
        """Get status emoji for analysis."""
        # Check if any stage is in progress
        has_in_progress = any(
            stage.status == StageStatus.IN_PROGRESS
            for stage in metadata.stages.values()
        )

        if has_in_progress:
            return "[yellow]◐[/yellow]"

        # Check completion
        completed = sum(
            1 for s in metadata.stages.values() if s.status == StageStatus.COMPLETED
        )
        total = len(metadata.stages)

        if completed == total and total > 0:
            return "[green]✓[/green]"
        elif completed > 0:
            return f"[blue]{completed}/{total}[/blue]"
        return "[dim]○[/dim]"

    def on_mount(self) -> None:
        """Start polling for live status."""
        self.poll_timer = self.set_interval(3, self.update_live_status)

    def on_unmount(self) -> None:
        """Stop polling."""
        if self.poll_timer:
            self.poll_timer.stop()

    def update_live_status(self) -> None:
        """Update the live indicator based on current analysis status."""
        if not self.selected_analysis or not self.live_indicator:
            self.live_indicator.is_live = False
            return

        metadata = self.kb_manager.load_metadata(self.selected_analysis)
        if not metadata:
            self.live_indicator.is_live = False
            return

        # Check if any stage is in progress
        in_progress_stage = None
        for stage_name, stage in metadata.stages.items():
            if stage.status == StageStatus.IN_PROGRESS:
                in_progress_stage = stage_name
                break

        if in_progress_stage:
            self.live_indicator.is_live = True
            self.live_indicator.current_stage = in_progress_stage
        else:
            self.live_indicator.is_live = False
            self.live_indicator.current_stage = ""

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle analysis selection."""
        if event.value:
            self.selected_analysis = event.value
            # Immediately update live status
            self.update_live_status()
            # Post message to parent
            self.post_message(AnalysisSelected(event.value))


class DebugView(Vertical):
    """Main debug view with tabs for conversations and outputs."""

    analysis_id: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(classes="debug-view-container"):
            # Analysis selector at top (fixed height, doesn't expand)
            with Container(classes="analysis-selector-container"):
                yield AnalysisSelector(id="analysis-selector")

            # Tabbed content for conversations and outputs (fills remaining space)
            with TabbedContent(classes="debug-tabs", id="debug-tabs"):
                with TabPane("💬 Conversations", id="conversations"):
                    yield ConversationBrowser(id="conversation-browser")

                with TabPane("📁 Outputs", id="outputs"):
                    yield OutputsBrowser(id="outputs-browser")

    def on_mount(self) -> None:
        """Connect selector to browsers using reactive watcher."""
        # Watch is now handled via message passing from AnalysisSelector
        # Activate first tab and refresh content
        tabs = self.query_one("#debug-tabs", TabbedContent)
        tabs.active = "conversations"
        self.refresh(layout=True)

    def on_analysis_selected(self, event: AnalysisSelected) -> None:
        """Handle analysis selection from selector."""
        self.app.notify(
            f"DebugView: Analysis selected {event.analysis_id[:8]}...",
            title="Debug Flow",
        )
        self._handle_analysis_change(event.analysis_id)

    def _handle_analysis_change(self, analysis_id: str | None) -> None:
        """Propagate analysis selection to browsers."""
        if analysis_id:
            self.app.notify(
                f"DebugView: Propagating {analysis_id[:8]} to browsers",
                title="Debug Flow",
            )
            self.analysis_id = analysis_id

            conv_browser = self.query_one("#conversation-browser", ConversationBrowser)
            conv_browser.analysis_id = analysis_id
            self.app.notify(
                f"DebugView: Set conv_browser.analysis_id", title="Debug Flow"
            )

            outputs_browser = self.query_one("#outputs-browser", OutputsBrowser)
            outputs_browser.analysis_id = analysis_id
            self.app.notify(
                f"DebugView: Set outputs_browser.analysis_id", title="Debug Flow"
            )
