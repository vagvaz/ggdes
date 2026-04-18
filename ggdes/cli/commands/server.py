"""Web, TUI, and debug commands."""

from typing import Annotated, Any

import typer

from ggdes.cli import app, console
from ggdes.cli.utils import resolve_analysis
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager


@app.command()
def tui() -> None:
    """Launch the interactive TUI."""
    from ggdes.tui import run_tui

    run_tui()


@app.command()
def debug(
    analysis: Annotated[
        str | None,
        typer.Argument(
            help="Analysis ID or name (optional - will show selector if not provided)"
        ),
    ] = None,
) -> None:
    """Launch the debug TUI to browse agent conversations and outputs."""
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header

    from ggdes.tui.debug_view import DebugView

    class DebugTUI(App[None]):
        """Standalone debug TUI application."""

        CSS = """
        Screen {
            align: center middle;
        }

        #debug-view {
            height: 1fr;
            width: 100%;
        }

        .debug-view-container {
            height: 100%;
            width: 100%;
        }

        .analysis-selector-container {
            height: auto;
            max-height: 8;
            padding: 1;
            border: solid $primary-darken-2;
        }

        AnalysisSelector {
            height: auto;
        }

        .analysis-selector-header {
            height: auto;
        }



        .debug-tabs {
            height: 1fr;
        }

        .browser-container {
            height: 100%;
        }

        .agent-list-panel {
            width: 20%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .message-list-panel {
            width: 40%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .message-header {
            height: auto;
            margin-bottom: 0;
            padding: 0;
        }

        .header-label {
            width: 1fr;
        }

        .follow-checkbox {
            width: auto;
            margin-left: 1;
        }

        .agent-info {
            height: auto;
            margin-top: 0;
            margin-bottom: 1;
        }

        .message-detail-panel {
            width: 40%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .file-tree-panel {
            width: 25%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        .outputs-header {
            height: auto;
            margin-bottom: 1;
            padding: 0;
        }

        .refresh-btn {
            width: auto;
            margin-left: 1;
        }

        .content-viewer-panel {
            width: 75%;
            border: solid $primary-darken-2;
            padding: 0 1;
        }

        #message-detail {
            height: 1fr;
        }

        #content-viewer {
            height: 1fr;
        }

        #file-tree {
            height: 1fr;
        }

        #agent-list {
            height: 1fr;
        }

        #message-list {
            height: 1fr;
        }
        """

        def __init__(self, analysis_id: str | None = None, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.analysis_id = analysis_id

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield DebugView(id="debug-view")
            yield Footer()

        def on_mount(self) -> None:
            """Set initial analysis if provided."""
            if self.analysis_id:
                debug_view = self.query_one("#debug-view", DebugView)
                # Set the analysis selector's value
                selector = debug_view.query_one("#analysis-selector")
                from textual.widgets import Select

                select_widget = selector.query_one("#analysis-select", Select)
                if select_widget:
                    select_widget.value = self.analysis_id

    # If analysis provided, try to find it
    if analysis:
        config, _ = load_config()
        kb_manager = KnowledgeBaseManager(config)

        found_id, _ = resolve_analysis(kb_manager, analysis)
        analysis = found_id

    # Run the debug TUI
    app = DebugTUI(analysis_id=analysis)
    app.run()


@app.command()
def web(
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8000,
    reload: Annotated[bool, typer.Option(help="Enable auto-reload (dev mode)")] = False,
) -> None:
    """Start the web interface."""
    try:
        import uvicorn

        console.print("[bold]Starting GGDes Web Interface[/bold]")
        console.print(f"[dim]Host:[/dim] {host}")
        console.print(f"[dim]Port:[/dim] {port}")
        console.print(f"[dim]URL:[/dim] http://{host}:{port}")
        console.print()
        console.print("[green]Press Ctrl+C to stop the server[/green]")
        console.print()

        uvicorn.run(
            "ggdes.web:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )

    except ImportError:
        console.print("[red]Error:[/red] Web dependencies not installed.")
        console.print(
            "[dim]Install with: uv pip install fastapi uvicorn websockets[/dim]"
        )
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Failed to start web server:[/red] {e}")
        raise typer.Exit(1) from e
