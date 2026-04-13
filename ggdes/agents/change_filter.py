"""Semantic change filter that uses LLM to classify diff hunks by relevance to a feature."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from rich.console import Console

from ggdes.config import GGDesConfig
from ggdes.llm import LLMFactory
from ggdes.schemas import ChangeSummary, FileChange

console = Console()


class FileClassification(BaseModel):
    """Classification of a file's relevance to a feature."""

    file_path: str = Field(
        description="Path to the file (must match a file in the diff)"
    )
    is_relevant: bool = Field(
        description="Whether the file contains changes relevant to the feature"
    )
    relevant_line_ranges: list[tuple[int, int]] = Field(
        default_factory=list,
        description="Line ranges relevant to the feature (1-based, inclusive). "
        "Empty list means the entire file is relevant if is_relevant is True.",
    )
    reason: str = Field(
        description="Brief explanation of why this file is relevant or not"
    )


class ChangeFilterResult(BaseModel):
    """Result of semantic change filtering."""

    classifications: list[FileClassification] = Field(
        description="Classification for each changed file"
    )
    feature_description: str = Field(
        description="The feature description used for filtering"
    )


@dataclass
class DiffHunk:
    """A single hunk from a unified diff."""

    file_path: str
    start_line: int  # 1-based line number in the new file
    end_line: int  # 1-based line number in the new file
    content: str
    lines_added: int = 0
    lines_deleted: int = 0


def parse_diff_into_hunks(diff: str) -> list[DiffHunk]:
    """Parse a unified diff into per-file hunks with line numbers.

    Args:
        diff: Raw unified diff string

    Returns:
        List of DiffHunk objects
    """
    hunks: list[DiffHunk] = []
    current_file = ""
    current_hunk_lines: list[str] = []
    hunk_start_line = 0
    hunk_end_line = 0
    lines_added = 0
    lines_deleted = 0

    # Pattern for new file in diff
    file_pattern = re.compile(r"^diff --git a/.+ b/(.+)$")
    # Pattern for hunk header: @@ -old_start,old_count +new_start,new_count @@
    hunk_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    lines = diff.split("\n")

    def save_current_hunk() -> None:
        if current_file and current_hunk_lines and hunk_start_line > 0:
            hunks.append(
                DiffHunk(
                    file_path=current_file,
                    start_line=hunk_start_line,
                    end_line=hunk_end_line,
                    content="\n".join(current_hunk_lines),
                    lines_added=lines_added,
                    lines_deleted=lines_deleted,
                )
            )

    for line in lines:
        # Check for new file
        file_match = file_pattern.match(line)
        if file_match:
            save_current_hunk()
            current_file = file_match.group(1)
            current_hunk_lines = []
            hunk_start_line = 0
            hunk_end_line = 0
            lines_added = 0
            lines_deleted = 0
            continue

        # Check for hunk header
        hunk_match = hunk_pattern.match(line)
        if hunk_match:
            save_current_hunk()
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            hunk_start_line = new_start
            hunk_end_line = new_start + max(new_count - 1, 0)
            current_hunk_lines = [line]
            lines_added = 0
            lines_deleted = 0
            continue

        # Accumulate hunk content
        if hunk_start_line > 0:
            current_hunk_lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_deleted += 1
                # Don't advance end line for deleted lines
            else:
                # Context or added lines advance the end line
                if not line.startswith("\\"):
                    hunk_end_line = max(
                        hunk_end_line,
                        hunk_start_line
                        + len(
                            [
                                l
                                for l in current_hunk_lines
                                if not l.startswith("-")
                                and not l.startswith("\\")
                                and not l.startswith("@@")
                            ]
                        ),
                    )

    save_current_hunk()
    return hunks


def group_hunks_by_file(hunks: list[DiffHunk]) -> dict[str, list[DiffHunk]]:
    """Group hunks by file path.

    Args:
        hunks: List of DiffHunk objects

    Returns:
        Dict mapping file paths to their hunks
    """
    files: dict[str, list[DiffHunk]] = {}
    for hunk in hunks:
        if hunk.file_path not in files:
            files[hunk.file_path] = []
        files[hunk.file_path].append(hunk)
    return files


class ChangeFilter:
    """Filter changes by semantic relevance to a feature using LLM classification."""

    def __init__(
        self,
        config: GGDesConfig,
        feature_description: str,
    ):
        """Initialize the change filter.

        Args:
            config: GGDes configuration
            feature_description: Description of the feature to filter for
        """
        self.config = config
        self.feature_description = feature_description
        self.llm = LLMFactory.from_config(config)

    def filter_changes(
        self,
        change_summary: ChangeSummary,
        diff: str,
    ) -> ChangeSummary:
        """Filter a ChangeSummary to only include changes relevant to the feature.

        Args:
            change_summary: The original change summary with all changes
            diff: The raw git diff string

        Returns:
            A new ChangeSummary with only relevant changes
        """
        logger.info(
            "ChangeFilter: starting | files=%d feature=%s",
            len(change_summary.files_changed),
            self.feature_description,
        )
        if not self.feature_description:
            console.print(
                "  [dim]No feature description provided, skipping semantic filtering[/dim]"
            )
            return change_summary

        if not diff or not diff.strip():
            console.print("  [dim]Empty diff, skipping semantic filtering[/dim]")
            return change_summary

        console.print(
            f"  [dim]Filtering changes for feature: {self.feature_description[:60]}...[/dim]"
        )

        # Parse diff into hunks
        hunks = parse_diff_into_hunks(diff)
        if not hunks:
            console.print(
                "  [dim]No hunks found in diff, skipping semantic filtering[/dim]"
            )
            return change_summary

        hunks_by_file = group_hunks_by_file(hunks)
        console.print(
            f"  [dim]Found {len(hunks)} hunks across {len(hunks_by_file)} files[/dim]"
        )

        # Classify files using LLM
        classifications = self._classify_files(hunks_by_file, change_summary)

        if not classifications:
            console.print(
                "  [yellow]Warning: LLM classification failed, keeping all changes[/yellow]"
            )
            return change_summary

        # Build classification lookup
        classification_map = {c.file_path: c for c in classifications}

        # Filter the change summary
        filtered_files = []
        removed_files = []
        for fc in change_summary.files_changed:
            classification = classification_map.get(fc.path)
            if classification and classification.is_relevant:
                # Update with relevant line ranges
                filtered_files.append(
                    FileChange(
                        path=fc.path,
                        change_type=fc.change_type,
                        lines_added=fc.lines_added,
                        lines_deleted=fc.lines_deleted,
                        summary=fc.summary,
                        relevant_line_ranges=classification.relevant_line_ranges
                        if classification.relevant_line_ranges
                        else None,
                    )
                )
            elif classification and not classification.is_relevant:
                removed_files.append(fc.path)
            else:
                # File not in classification (e.g., binary file), keep it
                filtered_files.append(fc)

        # Log results
        console.print(
            f"  [green]✓ Semantic filtering: {len(filtered_files)} relevant, "
            f"{len(removed_files)} filtered out[/green]"
        )
        if removed_files:
            for path in removed_files[:5]:
                cls = classification_map.get(path)
                reason = cls.reason if cls else "unknown"
                console.print(f"    [dim]- {path}: {reason[:80]}[/dim]")
            if len(removed_files) > 5:
                console.print(f"    [dim]... and {len(removed_files) - 5} more[/dim]")

        # Create filtered change summary
        filtered_summary = ChangeSummary(
            commit_hash=change_summary.commit_hash,
            commit_range=change_summary.commit_range,
            change_type=change_summary.change_type,
            description=change_summary.description,
            intent=change_summary.intent,
            impact=change_summary.impact,
            impact_level=change_summary.impact_level,
            files_changed=filtered_files,
            breaking_changes=change_summary.breaking_changes,
            dependencies_changed=change_summary.dependencies_changed,
            feature_description=self.feature_description,
            is_filtered=True,
        )

        return filtered_summary

    def _classify_files(
        self,
        hunks_by_file: dict[str, list[DiffHunk]],
        change_summary: ChangeSummary,
    ) -> list[FileClassification]:
        """Classify files by relevance to the feature using LLM.

        Args:
            hunks_by_file: Dict mapping file paths to their hunks
            change_summary: The original change summary for context

        Returns:
            List of FileClassification objects
        """
        # Build the prompt with diff hunks
        file_summaries = []
        for fc in change_summary.files_changed[:30]:  # Limit to 30 files
            file_summaries.append(
                f"- {fc.path} (+{fc.lines_added}/-{fc.lines_deleted}): {fc.summary}"
            )

        # Build diff content for each file (truncated for context window)
        diff_parts: list[str] = []
        total_lines = 0
        max_diff_lines = 2000  # Limit diff content to avoid context overflow

        for file_path, file_hunks in hunks_by_file.items():
            if total_lines >= max_diff_lines:
                diff_parts.append(
                    f"\n... (truncated, {len(hunks_by_file) - len(diff_parts)} more files)"
                )
                break

            hunk_contents = []
            for hunk in file_hunks:
                # Truncate individual hunks that are too long
                content_lines = hunk.content.split("\n")
                if len(content_lines) > 50:
                    content_lines = (
                        content_lines[:25] + ["... (truncated)"] + content_lines[-25:]
                    )
                hunk_contents.append(
                    f"Lines {hunk.start_line}-{hunk.end_line}:\n"
                    + "\n".join(content_lines)
                )

            file_diff = f"=== {file_path} ===\n" + "\n\n".join(hunk_contents)
            diff_parts.append(file_diff)
            total_lines += sum(len(h.content.split("\n")) for h in file_hunks)

        diff_content = "\n\n".join(diff_parts)

        prompt = f"""You are analyzing code changes to determine which files are relevant to a specific feature.

FEATURE DESCRIPTION: {self.feature_description}

FILES CHANGED ({len(change_summary.files_changed)} total):
{chr(10).join(file_summaries)}

DIFF CONTENT (relevant portions):
```diff
{diff_content}
```

For each file in the diff, classify whether its changes are relevant to the feature described above.

A file is RELEVANT if:
- It directly implements or modifies the feature
- It contains API changes that are part of the feature
- It modifies data structures or types used by the feature
- It changes configuration or setup required by the feature

A file is NOT RELEVANT if:
- It only contains unrelated changes (e.g., CI/CD, formatting, unrelated bug fixes)
- It changes test infrastructure not specific to this feature
- It modifies documentation for unrelated features
- It contains only dependency version bumps unrelated to the feature

For each relevant file, specify the line ranges that are relevant to the feature.
If the entire file is relevant, leave relevant_line_ranges as an empty list.

Respond with a JSON object matching the ChangeFilterResult schema."""

        try:
            logger.info(
                "ChangeFilter: LLM classification call | files=%d model=%s",
                len(file_hunks),
                self.llm.model_name,
            )
            result = self.llm.generate_structured(
                prompt=prompt,
                response_model=ChangeFilterResult,
                system_prompt="You are a code analysis expert. Classify code changes by their relevance to a specific feature. Be precise and conservative - only mark files as relevant if they directly relate to the feature description.",
                temperature=0.2,
                max_retries=3,
            )
            return result.classifications
        except Exception as e:
            console.print(f"  [red]Error classifying files:[/red] {e}")
            return []
