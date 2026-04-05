"""Docx output agent for generating Word documents."""

import subprocess
from pathlib import Path
from typing import Optional

from ggdes.agents.output_agents.base import OutputAgent


class DocxAgent(OutputAgent):
    """Generate Word document from document plan.

    For now, this generates markdown and converts to docx using pandoc.
    Future: Direct docx generation using docx-js or python-docx.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize docx agent."""
        super().__init__(repo_path, config, analysis_id)

    def _load_plan(self) -> Optional[dict]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path
        import json

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_docx.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def generate(self) -> Path:
        """Generate Word document.

        Returns:
            Path to generated docx file
        """
        # For now, use markdown as base and convert
        # First, check if markdown exists
        markdown_path = self.repo_path / "docs" / f"{self.analysis_id}-*.md"

        # Find the markdown file
        import glob

        md_files = glob.glob(str(markdown_path))

        if not md_files:
            raise FileNotFoundError(
                f"No markdown file found for {self.analysis_id}. "
                "Generate markdown first."
            )

        md_file = Path(md_files[0])

        # Generate output path
        output_file = md_file.with_suffix(".docx")

        # Convert using pandoc
        try:
            subprocess.run(
                [
                    "pandoc",
                    str(md_file),
                    "-o",
                    str(output_file),
                    "--reference-doc",  # Could add template later
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to convert to docx: {e}")
        except FileNotFoundError:
            # Pandoc not installed, create placeholder
            output_file.write_text(
                f"DOCX generation requires pandoc.\n\n"
                f"Source: {md_file}\n"
                f"Install pandoc: https://pandoc.org/installing.html"
            )

        return output_file
