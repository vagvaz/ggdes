"""Cleanup and conversations commands."""

import json
from pathlib import Path
from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.cli.utils import resolve_analysis
from ggdes.config import load_config
from ggdes.kb import KnowledgeBaseManager
from ggdes.worktree import WorktreeManager


@app.command()
def cleanup(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    remove_kb: Annotated[
        bool, typer.Option(help="Also remove from knowledge base")
    ] = False,
) -> None:
    """Clean up worktrees for an analysis."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id, found_metadata = resolve_analysis(kb_manager, analysis)

    # Clean worktrees
    wt_manager = WorktreeManager(config, Path(found_metadata.repo_path))
    wt_manager.cleanup(found_id)
    console.print(f"[green]Cleaned up worktrees for:[/green] {found_id}")

    # Optionally remove from KB
    if remove_kb and typer.confirm(
        f"Remove analysis '{found_metadata.name}' from knowledge base?"
    ):
        kb_manager.delete_analysis(found_id)
        console.print(f"[green]Removed from knowledge base:[/green] {found_id}")


@app.command()
def conversations(
    analysis: Annotated[str, typer.Argument(help="Analysis ID or name")],
    agent: Annotated[
        str | None,
        typer.Option(
            help="Filter by agent (git_analyzer, technical_author, coordinator, markdown)"
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(help="Show raw conversation with full messages"),
    ] = False,
) -> None:
    """View stored LLM conversations for an analysis."""
    config, _ = load_config()
    kb_manager = KnowledgeBaseManager(config)

    # Find analysis
    found_id, found_metadata = resolve_analysis(kb_manager, analysis)

    analysis_path = kb_manager.get_analysis_path(found_id)
    conversations_path = analysis_path / "conversations"

    if not conversations_path.exists():
        console.print(f"[yellow]No conversations found for:[/yellow] {found_id}")
        console.print("Conversations are saved during analysis execution.")
        return

    # List available conversation files
    conversation_files = []
    for conv_dir in conversations_path.iterdir():
        if conv_dir.is_dir():
            agent_name = conv_dir.name
            if agent and agent != agent_name:
                continue

            raw_file = conv_dir / "conversation_raw.json"
            summary_file = conv_dir / "conversation_summary.json"

            if raw_file.exists():
                conversation_files.append((agent_name, raw_file, "raw"))
            elif summary_file.exists():
                conversation_files.append((agent_name, summary_file, "summary"))

    if not conversation_files:
        console.print("[yellow]No conversation files found[/yellow]")
        return

    console.print(f"[bold]Conversations for:[/bold] {found_metadata.name}")
    console.print(f"Analysis ID: {found_id}\n")

    # Display conversations
    for agent_name, file_path, storage_type in sorted(conversation_files):
        console.print(f"[bold]{agent_name}[/bold] ({storage_type})")

        try:
            data = json.loads(file_path.read_text())

            if storage_type == "raw" and raw:
                # Show full raw conversation
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Messages: {len(data.get('messages', []))}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                console.print("\n  [dim]Messages:[/dim]")
                for i, msg in enumerate(data.get("messages", [])):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    preview = content[:150].replace("\n", " ")
                    if len(content) > 150:
                        preview += "..."
                    console.print(f"    {i + 1}. [{role}] {preview}")
            elif storage_type == "raw":
                # Show raw summary
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Messages: {len(data.get('messages', []))}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                console.print("  [dim]Use --raw to see full messages[/dim]")
            else:
                # Show summary
                summaries = data.get("summaries", [])
                console.print(f"  System: {data.get('system_prompt', 'N/A')[:100]}...")
                console.print(f"  Message count: {data.get('message_count', 0)}")
                console.print(f"  Total tokens: {data.get('total_tokens', 0)}")
                if summaries:
                    console.print(f"  Latest summary: {summaries[-1][:100]}...")

            console.print()

        except Exception as e:
            console.print(f"  [red]Error reading conversation:[/red] {e}")
            console.print()
