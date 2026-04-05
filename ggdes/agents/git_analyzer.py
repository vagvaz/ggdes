"""Git Analysis Agent for analyzing code changes with multi-turn support."""

import json
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from ggdes.llm import LLMFactory
from ggdes.llm.conversation import ConversationContext, estimate_tokens
from ggdes.prompts import get_prompt
from ggdes.schemas import ChangeSummary, StoragePolicy

console = Console()


class GitAnalyzer:
    """Analyze git changes with multi-turn conversation and chunking."""

    def __init__(self, repo_path: Path, config, analysis_id: Optional[str] = None):
        """Initialize git analyzer.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for saving conversations
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.llm = LLMFactory.from_config(config)
        self.conversation: Optional[ConversationContext] = None
        self.chunk_token_threshold = 25000  # Chunk diffs larger than this
        self.max_diff_tokens = 50000  # Absolute max before chunking

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context."""
        self.conversation = ConversationContext(
            system_prompt=get_prompt("git_analyzer", "system"),
            storage_policy=storage_policy,
            max_tokens=self.max_diff_tokens,
        )

    def get_diff(
        self, commit_range: str, focus_commits: Optional[list[str]] = None
    ) -> str:
        """Get git diff for a commit range or specific focus commits.

        Args:
            commit_range: Git commit range (used as boundary if focus_commits provided)
            focus_commits: Optional list of specific commits to analyze.
                          If provided, only these commits are analyzed.

        Returns:
            Git diff as string
        """
        if focus_commits:
            # When focus commits are specified, get diff only for those commits
            # For multiple focus commits, we get diff from parent of first to last
            if len(focus_commits) == 1:
                # Single commit: diff against its parent
                cmd = [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "diff",
                    f"{focus_commits[0]}~1..{focus_commits[0]}",
                ]
            else:
                # Multiple commits: diff from parent of first to last
                cmd = [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "diff",
                    f"{focus_commits[0]}~1..{focus_commits[-1]}",
                ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            diff = result.stdout
            # Prefix with context about which commits are being analyzed
            diff = f"# Analyzing focus commits: {', '.join(focus_commits)}\n# Full range context: {commit_range}\n\n{diff}"
        else:
            # No focus commits - analyze the full range
            cmd = ["git", "-C", str(self.repo_path), "diff", commit_range]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            diff = result.stdout

        return diff

    def get_commit_log(
        self, commit_range: str, focus_commits: Optional[list[str]] = None
    ) -> list[dict]:
        """Get commit log with messages.

        Args:
            commit_range: Git commit range (used as boundary if focus_commits provided)
            focus_commits: Optional list of specific commits to include.
                          If provided, only these commits are returned.

        Returns:
            List of commit dictionaries
        """
        format_str = "%H|%an|%ad|%s"

        if focus_commits:
            # When focus commits are specified, only get those commits
            # Use git show instead of git log for specific commits
            commits = []
            for commit_hash in focus_commits:
                cmd = [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "show",
                    "-s",  # Skip the diff output
                    f"--format={format_str}",
                    "--date=short",
                    commit_hash,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )

                line = result.stdout.strip()
                if line:
                    parts = line.split("|", 3)
                    if len(parts) >= 4:
                        commits.append(
                            {
                                "hash": parts[0],
                                "author": parts[1],
                                "date": parts[2],
                                "message": parts[3],
                            }
                        )

            return commits
        else:
            # No focus commits - get full range
            cmd = [
                "git",
                "-C",
                str(self.repo_path),
                "log",
                f"--format={format_str}",
                "--date=short",
                commit_range,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            commits = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("|", 3)
                    if len(parts) >= 4:
                        commits.append(
                            {
                                "hash": parts[0],
                                "author": parts[1],
                                "date": parts[2],
                                "message": parts[3],
                            }
                        )

            return commits

    def get_changed_files(
        self, commit_range: str, focus_commits: Optional[list[str]] = None
    ) -> list[dict]:
        """Get list of changed files with stats.

        Args:
            commit_range: Git commit range (used as boundary if focus_commits provided)
            focus_commits: Optional list of specific commits to include.
                          If provided, only files changed in these commits are returned.

        Returns:
            List of file dictionaries with change stats
        """
        if focus_commits:
            # When focus commits are specified, aggregate changes from those commits
            file_stats = {}

            for commit_hash in focus_commits:
                cmd = [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "diff-tree",
                    "--numstat",
                    "-r",
                    f"{commit_hash}~1",
                    commit_hash,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )

                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) == 3:
                        added = parts[0]
                        deleted = parts[1]
                        path = parts[2]

                        if path not in file_stats:
                            file_stats[path] = {
                                "lines_added": 0,
                                "lines_deleted": 0,
                                "is_binary": False,
                            }

                        if added == "-" or deleted == "-":
                            file_stats[path]["is_binary"] = True
                        else:
                            file_stats[path]["lines_added"] += (
                                int(added) if added.isdigit() else 0
                            )
                            file_stats[path]["lines_deleted"] += (
                                int(deleted) if deleted.isdigit() else 0
                            )

            # Convert to list format
            files = []
            for path, stats in file_stats.items():
                files.append(
                    {
                        "path": path,
                        "lines_added": stats["lines_added"],
                        "lines_deleted": stats["lines_deleted"],
                        "is_binary": stats["is_binary"],
                    }
                )

            return files
        else:
            # No focus commits - get full range
            cmd = [
                "git",
                "-C",
                str(self.repo_path),
                "diff",
                "--numstat",
                commit_range,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            files = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) == 3:
                    added = parts[0]
                    deleted = parts[1]
                    path = parts[2]

                    if added == "-" or deleted == "-":
                        files.append(
                            {
                                "path": path,
                                "lines_added": 0,
                                "lines_deleted": 0,
                                "is_binary": True,
                            }
                        )
                    else:
                        files.append(
                            {
                                "path": path,
                                "lines_added": int(added) if added.isdigit() else 0,
                                "lines_deleted": int(deleted)
                                if deleted.isdigit()
                                else 0,
                                "is_binary": False,
                            }
                        )

            return files

    async def analyze(
        self,
        commit_range: str,
        focus_commits: Optional[list[str]] = None,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
    ) -> ChangeSummary:
        """Analyze git changes with multi-turn conversation and chunking.

        Args:
            commit_range: Git commit range
            focus_commits: Optional list of focus commits
            storage_policy: How to persist conversation

        Returns:
            ChangeSummary with analysis results
        """
        # Store original commit range for output
        self.original_commit_range = commit_range

        # Initialize conversation
        self._init_conversation(storage_policy)

        # Gather git data
        if focus_commits:
            console.print(
                f"  [dim]Analyzing {len(focus_commits)} focus commits from range: {commit_range}[/dim]"
            )
        else:
            console.print(f"  [dim]Analyzing full commit range: {commit_range}[/dim]")

        diff = self.get_diff(commit_range, focus_commits)
        commits = self.get_commit_log(commit_range, focus_commits)
        files = self.get_changed_files(commit_range, focus_commits)

        console.print(
            f"  [dim]Found {len(commits)} commits, {len(files)} files changed[/dim]"
        )

        # Check if diff needs chunking
        diff_tokens = estimate_tokens(diff)

        if diff_tokens > self.max_diff_tokens:
            # Multi-chunk analysis
            change_summary = await self._analyze_chunked(diff, files, commits)
        else:
            # Single-pass analysis
            change_summary = await self._analyze_single(diff, files, commits)

        # Save conversation to KB
        if self.analysis_id:
            from ggdes.config import get_kb_path

            kb_path = (
                get_kb_path(self.config, self.analysis_id)
                / "conversations"
                / "git_analyzer"
            )
            self.conversation.save(kb_path)

        return change_summary

    async def _analyze_single(
        self, diff: str, files: list[dict], commits: list[dict]
    ) -> ChangeSummary:
        """Single-pass analysis for diffs that fit in context."""
        # Turn 1: Initial analysis
        self.conversation.add_user_message(
            f"Analyze this git diff and identify key changes:\n\n{diff[:40000]}"
        )

        context = self.conversation.get_context_for_llm()
        response1 = await self._chat_with_context(context)
        self.conversation.add_assistant_message(response1)

        # Turn 2: Deep dive on breaking changes
        self.conversation.add_user_message(
            "Based on your analysis, identify any breaking changes, API modifications, "
            "or significant behavioral changes. Be specific about what changed and why."
        )

        context = self.conversation.get_context_for_llm()
        response2 = await self._chat_with_context(context)
        self.conversation.add_assistant_message(response2)

        # Turn 3: Impact assessment
        self.conversation.add_user_message(
            "Assess the impact of these changes on the system. "
            "What are the risks? Who is affected? What needs to be tested?"
        )

        context = self.conversation.get_context_for_llm()
        response3 = await self._chat_with_context(context)
        self.conversation.add_assistant_message(response3)

        # Turn 4: Structured output
        self.conversation.add_user_message(
            "Now provide a structured summary. Output a JSON object matching the ChangeSummary schema "
            "with fields: change_type, description, intent, impact, impact_level, breaking_changes, dependencies_changed"
        )

        context = self.conversation.get_context_for_llm()
        change_summary = await self._generate_structured(context)

        # Add file info from git stats
        from ggdes.schemas import FileChange

        change_summary.files_changed = [
            FileChange(
                path=f["path"],
                change_type="modified",
                lines_added=f["lines_added"],
                lines_deleted=f["lines_deleted"],
                summary=f"Changed in {len(commits)} commits",
            )
            for f in files
        ]

        # Set commit range info - use original range passed by user
        change_summary.commit_range = getattr(self, "original_commit_range", "unknown")
        if commits:
            change_summary.commit_hash = commits[0]["hash"]

        return change_summary

    async def _analyze_chunked(
        self, diff: str, files: list[dict], commits: list[dict]
    ) -> ChangeSummary:
        """Multi-chunk analysis for large diffs."""
        # Split diff into chunks by file or size
        chunks = self._chunk_diff(diff, max_tokens=self.chunk_token_threshold)

        chunk_summaries = []

        # Process each chunk
        for i, chunk in enumerate(chunks):
            chunk_context = f"""
This is chunk {i + 1} of {len(chunks)} of a large diff.
Files in this chunk: {chunk["files"]}

{chunk["content"]}

Provide a brief analysis of these specific changes.
"""
            self.conversation.add_user_message(chunk_context)

            context = self.conversation.get_context_for_llm()
            response = await self._chat_with_context(context)
            self.conversation.add_assistant_message(response)

            chunk_summaries.append(
                {
                    "chunk_num": i + 1,
                    "files": chunk["files"],
                    "analysis": response,
                }
            )

        # Synthesis turn: Combine all chunk analyses
        synthesis_prompt = f"""
You have analyzed {len(chunks)} chunks of a large diff. Here are the summaries:

"""
        for summary in chunk_summaries:
            synthesis_prompt += f"\nChunk {summary['chunk_num']} ({', '.join(summary['files'])}):\n{summary['analysis']}\n"

        synthesis_prompt += """
Now synthesize these into a cohesive overall analysis. Identify:
1. The primary purpose/intent of the changes
2. Any breaking changes across all chunks
3. System-wide impact
4. Overall change type (feature, bugfix, refactor, etc.)

Then provide a structured ChangeSummary.
"""

        self.conversation.add_user_message(synthesis_prompt)
        context = self.conversation.get_context_for_llm()
        change_summary = await self._generate_structured(context)

        # Add file info
        from ggdes.schemas import FileChange

        change_summary.files_changed = [
            FileChange(
                path=f["path"],
                change_type="modified",
                lines_added=f["lines_added"],
                lines_deleted=f["lines_deleted"],
                summary=f"Changed in {len(commits)} commits",
            )
            for f in files
        ]

        # Use original commit range passed by user
        change_summary.commit_range = getattr(self, "original_commit_range", "unknown")
        if commits:
            change_summary.commit_hash = commits[0]["hash"]

        return change_summary

    def _chunk_diff(self, diff: str, max_tokens: int = 25000) -> list[dict]:
        """Split diff into chunks by file or token size."""
        chunks = []
        current_chunk_content = []
        current_chunk_files = []
        current_chunk_tokens = 0

        lines = diff.split("\n")
        current_file = None

        for line in lines:
            # Detect file changes in diff
            if line.startswith("diff --git"):
                # New file section
                if current_chunk_content and current_chunk_tokens > max_tokens:
                    # Save current chunk
                    chunks.append(
                        {
                            "files": current_chunk_files.copy(),
                            "content": "\n".join(current_chunk_content),
                            "tokens": current_chunk_tokens,
                        }
                    )
                    # Start new chunk with overlap context
                    current_chunk_content = current_chunk_content[
                        -50:
                    ]  # Keep last 50 lines for context
                    current_chunk_files = current_chunk_files[
                        -3:
                    ]  # Keep last 3 files mentioned
                    current_chunk_tokens = estimate_tokens(
                        "\n".join(current_chunk_content)
                    )

                # Extract filename
                parts = line.split()
                if len(parts) >= 3:
                    current_file = parts[2].replace("b/", "")
                    if current_file not in current_chunk_files:
                        current_chunk_files.append(current_file)

            current_chunk_content.append(line)
            current_chunk_tokens += estimate_tokens(line) + 1

        # Don't forget the last chunk
        if current_chunk_content:
            chunks.append(
                {
                    "files": current_chunk_files,
                    "content": "\n".join(current_chunk_content),
                    "tokens": current_chunk_tokens,
                }
            )

        # If only one chunk, return it
        if len(chunks) == 0 and diff:
            chunks.append(
                {
                    "files": current_chunk_files
                    if current_chunk_files
                    else ["unknown"],
                    "content": diff,
                    "tokens": estimate_tokens(diff),
                }
            )

        return chunks

    async def _chat_with_context(self, context: list[dict]) -> str:
        """Send chat request with full conversation context."""
        return self.llm.chat(
            messages=context,
            temperature=0.3,
            max_tokens=4096,
        )

    async def _generate_structured(self, context: list[dict]) -> ChangeSummary:
        """Generate structured output from conversation context."""
        # Extract system and messages
        system = None
        messages = []

        for msg in context:
            if msg["role"] == "system":
                if system is None:
                    system = msg["content"]
                else:
                    system += "\n\n" + msg["content"]
            else:
                messages.append(msg)

        # Add schema instruction to system
        system += (
            "\n\nYou must respond with a JSON object matching the ChangeSummary schema. "
            "Include fields: change_type, description, intent, impact, impact_level, "
            "breaking_changes (array), dependencies_changed (array)."
        )

        return self.llm.generate_structured(
            prompt=messages[-1]["content"]
            if messages
            else "Provide structured summary",
            response_model=ChangeSummary,
            system_prompt=system,
            temperature=0.2,
            max_retries=3,
        )

    @classmethod
    def load_conversation(
        cls,
        kb_path: Path,
        storage_policy: Optional[StoragePolicy] = None,
    ) -> ConversationContext:
        """Load existing conversation from KB."""
        return ConversationContext.load(kb_path, storage_policy)
