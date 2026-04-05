"""Git Analysis Agent for analyzing code changes."""

import subprocess
from pathlib import Path
from typing import Optional

from ggdes.llm import LLMFactory
from ggdes.prompts import get_prompt
from ggdes.schemas import ChangeSummary


class GitAnalyzer:
    """Analyze git changes and extract structured information."""

    def __init__(self, repo_path: Path, config):
        """Initialize git analyzer.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
        """
        self.repo_path = repo_path
        self.config = config
        self.llm = LLMFactory.from_config(config)

    def get_diff(
        self, commit_range: str, focus_commits: Optional[list[str]] = None
    ) -> str:
        """Get git diff for a commit range.

        Args:
            commit_range: Git commit range (e.g., "HEAD~5..HEAD")
            focus_commits: Optional list of specific commits to focus on

        Returns:
            Git diff content
        """
        cmd = ["git", "-C", str(self.repo_path), "diff", commit_range]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        diff = result.stdout

        # If focus commits specified, we might want to filter or annotate
        if focus_commits:
            # For now, just note in the output
            # In future: could filter to only show changes from focus commits
            diff = f"# Focus commits: {', '.join(focus_commits)}\n\n{diff}"

        return diff

    def get_commit_log(self, commit_range: str) -> list[dict]:
        """Get commit log with messages.

        Args:
            commit_range: Git commit range

        Returns:
            List of commit info dicts
        """
        # Format: hash|author|date|message
        format_str = "%H|%an|%ad|%s"

        cmd = [
            "git",
            "-C",
            str(self.repo_path),
            "log",
            "--format",
            format_str,
            "--date",
            "short",
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

    def get_changed_files(self, commit_range: str) -> list[dict]:
        """Get list of changed files with stats.

        Args:
            commit_range: Git commit range

        Returns:
            List of file change info dicts
        """
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

                # Handle binary files (marked as -)
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
                            "lines_deleted": int(deleted) if deleted.isdigit() else 0,
                            "is_binary": False,
                        }
                    )

        return files

    def analyze(
        self, commit_range: str, focus_commits: Optional[list[str]] = None
    ) -> ChangeSummary:
        """Analyze git changes and return structured summary.

        Args:
            commit_range: Git commit range
            focus_commits: Optional list of focus commits

        Returns:
            ChangeSummary with analysis results
        """
        # Gather git data
        diff = self.get_diff(commit_range, focus_commits)
        commits = self.get_commit_log(commit_range)
        files = self.get_changed_files(commit_range)

        # Prepare context for LLM
        commit_messages = "\n".join(
            [f"- {c['hash'][:8]}: {c['message']} ({c['date']})" for c in commits]
        )

        files_info = "\n".join(
            [f"- {f['path']}: +{f['lines_added']} -{f['lines_deleted']}" for f in files]
        )

        # Build prompt
        system_prompt = get_prompt("git_analyzer", "system")
        prompt = get_prompt(
            "git_analyzer",
            "analyze_diff",
            commit_range=commit_range,
            focus_commits=", ".join(focus_commits)
            if focus_commits
            else "All commits in range",
            diff_content=diff[:50000],  # Limit diff size
        )

        # Generate structured output using Instructor
        # This guarantees the output matches ChangeSummary schema
        change_summary = self.llm.generate_structured(
            prompt=prompt,
            response_model=ChangeSummary,
            system_prompt=system_prompt,
            temperature=0.3,  # Low temp for consistent analysis
            max_retries=3,  # Retry on validation failure
        )

        # Add file info from git stats (override what LLM provided)
        from ggdes.schemas import FileChange

        change_summary.files_changed = [
            FileChange(
                path=f["path"],
                change_type="modified",  # TODO: detect add/delete/rename
                lines_added=f["lines_added"],
                lines_deleted=f["lines_deleted"],
                summary=f"Changed in {len(commits)} commits",
            )
            for f in files
        ]

        # Set commit range info
        change_summary.commit_range = commit_range
        if commits:
            change_summary.commit_hash = commits[0]["hash"]

        return change_summary
