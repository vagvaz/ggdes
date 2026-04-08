"""Analysis comparison for GGDes.

Provides functionality to compare two analyses side-by-side.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ggdes.config import GGDesConfig
from ggdes.kb import KnowledgeBaseManager
from ggdes.schemas import ChangeSummary, TechnicalFact, DocumentPlan

console = Console()


@dataclass
class AnalysisDiff:
    """Difference between two analyses."""

    field: str
    analysis1_value: str
    analysis2_value: str
    change_type: str  # "added", "removed", "modified", "same"


@dataclass
class ComparisonResult:
    """Result of comparing two analyses."""

    analysis1_id: str
    analysis2_id: str
    analysis1_name: str
    analysis2_name: str
    commit_diff: list[AnalysisDiff]
    file_changes_diff: list[AnalysisDiff]
    facts_diff: list[AnalysisDiff]
    breaking_changes_diff: list[AnalysisDiff]
    similarity_score: float  # 0-1 score of how similar the analyses are


class AnalysisComparator:
    """Compare two analyses side-by-side."""

    def __init__(self, config: GGDesConfig):
        """Initialize comparator.

        Args:
            config: GGDes configuration
        """
        self.config = config
        self.kb_manager = KnowledgeBaseManager(config)

    def compare(
        self,
        analysis1_id: str,
        analysis2_id: str,
    ) -> ComparisonResult:
        """Compare two analyses.

        Args:
            analysis1_id: First analysis ID
            analysis2_id: Second analysis ID

        Returns:
            ComparisonResult with all differences
        """
        # Load metadata for both analyses
        metadata1 = self.kb_manager.load_metadata(analysis1_id)
        metadata2 = self.kb_manager.load_metadata(analysis2_id)

        if not metadata1:
            raise ValueError(f"Analysis not found: {analysis1_id}")
        if not metadata2:
            raise ValueError(f"Analysis not found: {analysis2_id}")

        # Load git analysis summaries
        summary1 = self._load_git_summary(analysis1_id)
        summary2 = self._load_git_summary(analysis2_id)

        # Load technical facts
        facts1 = self._load_technical_facts(analysis1_id)
        facts2 = self._load_technical_facts(analysis2_id)

        # Compute differences
        commit_diff = self._compare_commits(metadata1, metadata2)
        file_changes_diff = self._compare_file_changes(summary1, summary2)
        facts_diff = self._compare_facts(facts1, facts2)
        breaking_changes_diff = self._compare_breaking_changes(summary1, summary2)

        # Compute similarity score
        similarity = self._compute_similarity(
            commit_diff, file_changes_diff, facts_diff, breaking_changes_diff
        )

        return ComparisonResult(
            analysis1_id=analysis1_id,
            analysis2_id=analysis2_id,
            analysis1_name=metadata1.name,
            analysis2_name=metadata2.name,
            commit_diff=commit_diff,
            file_changes_diff=file_changes_diff,
            facts_diff=facts_diff,
            breaking_changes_diff=breaking_changes_diff,
            similarity_score=similarity,
        )

    def _load_git_summary(self, analysis_id: str) -> Optional[ChangeSummary]:
        """Load git analysis summary."""
        analysis_path = (
            self.kb_manager.get_analysis_path(analysis_id)
            / "git_analysis"
            / "summary.json"
        )

        if not analysis_path.exists():
            return None

        try:
            data = json.loads(analysis_path.read_text())
            return ChangeSummary(**data)
        except Exception:
            return None

    def _load_technical_facts(self, analysis_id: str) -> list[TechnicalFact]:
        """Load technical facts for an analysis."""
        facts_dir = self.kb_manager.get_analysis_path(analysis_id) / "technical_facts"
        facts = []

        if not facts_dir.exists():
            return facts

        for fact_file in facts_dir.glob("*.json"):
            try:
                data = json.loads(fact_file.read_text())
                facts.append(TechnicalFact(**data))
            except Exception:
                continue

        return facts

    def _compare_commits(self, metadata1, metadata2) -> list[AnalysisDiff]:
        """Compare commit ranges."""
        diffs = []

        range1 = metadata1.commit_range or "unknown"
        range2 = metadata2.commit_range or "unknown"

        if range1 != range2:
            diffs.append(
                AnalysisDiff(
                    field="commit_range",
                    analysis1_value=range1,
                    analysis2_value=range2,
                    change_type="modified" if range1 and range2 else "added",
                )
            )

        # Compare focus commits
        focus1 = set(metadata1.focus_commits or [])
        focus2 = set(metadata2.focus_commits or [])

        added = focus2 - focus1
        removed = focus1 - focus2

        for commit in added:
            diffs.append(
                AnalysisDiff(
                    field="focus_commit",
                    analysis1_value="",
                    analysis2_value=commit,
                    change_type="added",
                )
            )

        for commit in removed:
            diffs.append(
                AnalysisDiff(
                    field="focus_commit",
                    analysis1_value=commit,
                    analysis2_value="",
                    change_type="removed",
                )
            )

        return diffs

    def _compare_file_changes(
        self, summary1: Optional[ChangeSummary], summary2: Optional[ChangeSummary]
    ) -> list[AnalysisDiff]:
        """Compare file changes."""
        diffs = []

        files1 = {f.path: f for f in (summary1.files_changed if summary1 else [])}
        files2 = {f.path: f for f in (summary2.files_changed if summary2 else [])}

        all_files = set(files1.keys()) | set(files2.keys())

        for file_path in all_files:
            if file_path in files1 and file_path not in files2:
                diffs.append(
                    AnalysisDiff(
                        field=f"file:{file_path}",
                        analysis1_value=f"changed (+{files1[file_path].lines_added}/-{files1[file_path].lines_deleted})",
                        analysis2_value="not present",
                        change_type="removed",
                    )
                )
            elif file_path not in files1 and file_path in files2:
                diffs.append(
                    AnalysisDiff(
                        field=f"file:{file_path}",
                        analysis1_value="not present",
                        analysis2_value=f"changed (+{files2[file_path].lines_added}/-{files2[file_path].lines_deleted})",
                        change_type="added",
                    )
                )
            else:
                # File in both, check if change metrics differ
                f1, f2 = files1[file_path], files2[file_path]
                if (
                    f1.lines_added != f2.lines_added
                    or f1.lines_deleted != f2.lines_deleted
                ):
                    diffs.append(
                        AnalysisDiff(
                            field=f"file:{file_path}",
                            analysis1_value=f"+{f1.lines_added}/-{f1.lines_deleted}",
                            analysis2_value=f"+{f2.lines_added}/-{f2.lines_deleted}",
                            change_type="modified",
                        )
                    )

        return diffs

    def _compare_facts(
        self, facts1: list[TechnicalFact], facts2: list[TechnicalFact]
    ) -> list[AnalysisDiff]:
        """Compare technical facts."""
        diffs = []

        facts1_by_id = {f.fact_id: f for f in facts1}
        facts2_by_id = {f.fact_id: f for f in facts2}

        all_ids = set(facts1_by_id.keys()) | set(facts2_by_id.keys())

        for fact_id in all_ids:
            if fact_id in facts1_by_id and fact_id not in facts2_by_id:
                diffs.append(
                    AnalysisDiff(
                        field=f"fact:{fact_id}",
                        analysis1_value=facts1_by_id[fact_id].description[:60],
                        analysis2_value="",
                        change_type="removed",
                    )
                )
            elif fact_id not in facts1_by_id and fact_id in facts2_by_id:
                diffs.append(
                    AnalysisDiff(
                        field=f"fact:{fact_id}",
                        analysis1_value="",
                        analysis2_value=facts2_by_id[fact_id].description[:60],
                        change_type="added",
                    )
                )
            else:
                # Fact in both, check if content differs
                f1, f2 = facts1_by_id[fact_id], facts2_by_id[fact_id]
                if f1.description != f2.description or f1.category != f2.category:
                    diffs.append(
                        AnalysisDiff(
                            field=f"fact:{fact_id}",
                            analysis1_value=f"[{f1.category}] {f1.description[:50]}",
                            analysis2_value=f"[{f2.category}] {f2.description[:50]}",
                            change_type="modified",
                        )
                    )

        return diffs

    def _compare_breaking_changes(
        self, summary1: Optional[ChangeSummary], summary2: Optional[ChangeSummary]
    ) -> list[AnalysisDiff]:
        """Compare breaking changes."""
        diffs = []

        bc1 = set(summary1.breaking_changes if summary1 else [])
        bc2 = set(summary2.breaking_changes if summary2 else [])

        added = bc2 - bc1
        removed = bc1 - bc2

        for change in added:
            diffs.append(
                AnalysisDiff(
                    field="breaking_change",
                    analysis1_value="",
                    analysis2_value=change[:60],
                    change_type="added",
                )
            )

        for change in removed:
            diffs.append(
                AnalysisDiff(
                    field="breaking_change",
                    analysis1_value=change[:60],
                    analysis2_value="",
                    change_type="removed",
                )
            )

        return diffs

    def _compute_similarity(
        self,
        commit_diff: list[AnalysisDiff],
        file_diff: list[AnalysisDiff],
        facts_diff: list[AnalysisDiff],
        bc_diff: list[AnalysisDiff],
    ) -> float:
        """Compute similarity score between analyses.

        Returns:
            Similarity score from 0.0 (completely different) to 1.0 (identical)
        """
        all_diffs = commit_diff + file_diff + facts_diff + bc_diff

        if not all_diffs:
            return 1.0  # Identical

        same_count = sum(1 for d in all_diffs if d.change_type == "same")
        total = len(all_diffs)

        if total == 0:
            return 1.0

        return same_count / total


def print_comparison(result: ComparisonResult) -> None:
    """Print comparison result in a formatted table.

    Args:
        result: ComparisonResult to display
    """
    console.print(f"\n[bold]Analysis Comparison[/bold]")
    console.print(f"  {result.analysis1_name} vs {result.analysis2_name}")
    console.print(f"  Similarity Score: {result.similarity_score:.1%}")
    console.print()

    # Commit differences
    if result.commit_diff:
        table = Table(title="Commit Differences")
        table.add_column("Field", style="cyan")
        table.add_column(result.analysis1_name[:30], style="green")
        table.add_column(result.analysis2_name[:30], style="blue")
        table.add_column("Change", style="yellow")

        for diff in result.commit_diff:
            table.add_row(
                diff.field,
                diff.analysis1_value[:50] if diff.analysis1_value else "-",
                diff.analysis2_value[:50] if diff.analysis2_value else "-",
                diff.change_type,
            )

        console.print(table)
        console.print()

    # File changes
    if result.file_changes_diff:
        table = Table(title="File Change Differences")
        table.add_column("File", style="cyan")
        table.add_column(result.analysis1_name[:30], style="green")
        table.add_column(result.analysis2_name[:30], style="blue")
        table.add_column("Change", style="yellow")

        for diff in result.file_changes_diff[:20]:  # Limit to 20
            table.add_row(
                diff.field.replace("file:", ""),
                diff.analysis1_value[:40] if diff.analysis1_value else "-",
                diff.analysis2_value[:40] if diff.analysis2_value else "-",
                diff.change_type,
            )

        if len(result.file_changes_diff) > 20:
            table.add_row(
                "...",
                f"{len(result.file_changes_diff) - 20} more files",
                "",
                "",
            )

        console.print(table)
        console.print()

    # Facts differences
    if result.facts_diff:
        table = Table(title="Technical Facts Differences")
        table.add_column("Fact", style="cyan")
        table.add_column(result.analysis1_name[:30], style="green")
        table.add_column(result.analysis2_name[:30], style="blue")
        table.add_column("Change", style="yellow")

        for diff in result.facts_diff[:15]:  # Limit to 15
            table.add_row(
                diff.field.replace("fact:", ""),
                diff.analysis1_value[:40] if diff.analysis1_value else "-",
                diff.analysis2_value[:40] if diff.analysis2_value else "-",
                diff.change_type,
            )

        if len(result.facts_diff) > 15:
            table.add_row(
                "...",
                f"{len(result.facts_diff) - 15} more facts",
                "",
                "",
            )

        console.print(table)
        console.print()

    # Breaking changes
    if result.breaking_changes_diff:
        table = Table(title="Breaking Changes Differences")
        table.add_column("Change", style="cyan")
        table.add_column(result.analysis1_name[:30], style="green")
        table.add_column(result.analysis2_name[:30], style="blue")
        table.add_column("Status", style="yellow")

        for diff in result.breaking_changes_diff:
            table.add_row(
                diff.field,
                diff.analysis1_value[:50] if diff.analysis1_value else "-",
                diff.analysis2_value[:50] if diff.analysis2_value else "-",
                diff.change_type,
            )

        console.print(table)


def export_comparison(result: ComparisonResult, output_path: Path) -> None:
    """Export comparison result to JSON.

    Args:
        result: ComparisonResult to export
        output_path: Path to save JSON file
    """
    data = {
        "analysis1": {
            "id": result.analysis1_id,
            "name": result.analysis1_name,
        },
        "analysis2": {
            "id": result.analysis2_id,
            "name": result.analysis2_name,
        },
        "similarity_score": result.similarity_score,
        "commit_differences": [
            {
                "field": d.field,
                "analysis1": d.analysis1_value,
                "analysis2": d.analysis2_value,
                "change_type": d.change_type,
            }
            for d in result.commit_diff
        ],
        "file_changes": [
            {
                "field": d.field,
                "analysis1": d.analysis1_value,
                "analysis2": d.analysis2_value,
                "change_type": d.change_type,
            }
            for d in result.file_changes_diff
        ],
        "facts_differences": [
            {
                "field": d.field,
                "analysis1": d.analysis1_value,
                "analysis2": d.analysis2_value,
                "change_type": d.change_type,
            }
            for d in result.facts_diff
        ],
        "breaking_changes": [
            {
                "field": d.field,
                "analysis1": d.analysis1_value,
                "analysis2": d.analysis2_value,
                "change_type": d.change_type,
            }
            for d in result.breaking_changes_diff
        ],
        "exported_at": datetime.now().isoformat(),
    }

    output_path.write_text(json.dumps(data, indent=2))
