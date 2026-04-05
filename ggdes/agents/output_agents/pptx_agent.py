"""PPTX output agent for generating PowerPoint presentations."""

import subprocess
from pathlib import Path
from typing import Optional

from ggdes.agents.output_agents.base import OutputAgent


class PptxAgent(OutputAgent):
    """Generate PowerPoint presentation from document plan.

    For now, this generates markdown and converts to pptx using pandoc.
    Future: Direct pptx generation.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize pptx agent."""
        super().__init__(repo_path, config, analysis_id)

    def _load_plan(self) -> Optional[dict]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path
        import json

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_pptx.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def generate(self) -> Path:
        """Generate PowerPoint presentation.

        Returns:
            Path to generated pptx file
        """
        # For now, convert from markdown
        import glob

        md_path = self.repo_path / "docs" / f"{self.analysis_id}-*.md"
        md_files = glob.glob(str(md_path))

        if not md_files:
            raise FileNotFoundError(
                f"No markdown file found for {self.analysis_id}. "
                "Generate markdown first."
            )

        md_file = Path(md_files[0])
        output_file = md_file.with_suffix(".pptx")

        # Convert using pandoc (may not work well for pptx)
        # Better approach: use markdown as source and create summary slides
        try:
            # Create a simplified version for slides
            summary_md = self._create_slide_markdown(md_file)
            summary_file = md_file.with_suffix(".slides.md")
            summary_file.write_text(summary_md)

            subprocess.run(
                ["pandoc", str(summary_file), "-o", str(output_file)],
                check=True,
                capture_output=True,
            )

            # Clean up temp file
            summary_file.unlink()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Pandoc not available or failed
            output_file.write_text(
                f"PPTX generation requires pandoc.\n\n"
                f"Source: {md_file}\n"
                f"Install pandoc: https://pandoc.org/installing.html"
            )

        return output_file

    def _create_slide_markdown(self, md_file: Path) -> str:
        """Create slide-friendly markdown from full document."""
        content = md_file.read_text()

        # Extract headers and key points
        lines = content.split("\n")
        slides = []

        for line in lines:
            if line.startswith("# "):
                slides.append(f"# {line[2:]}")
            elif line.startswith("## "):
                slides.append(f"## {line[3:]}")
            elif line.startswith("- ") and len(slides) > 0:
                # Add as bullet point
                slides.append(line)

        # Add slide breaks
        slide_content = "\n\n---\n\n".join(
            ["\n".join(group) for group in self._group_into_slides(slides)]
        )

        return slide_content

    def _group_into_slides(self, items: list[str]) -> list[list[str]]:
        """Group content items into slides."""
        slides = []
        current_slide = []

        for item in items:
            if item.startswith("# "):
                # New title slide
                if current_slide:
                    slides.append(current_slide)
                current_slide = [item]
            elif item.startswith("## "):
                # New content slide
                if current_slide and len(current_slide) > 5:
                    slides.append(current_slide)
                    current_slide = [item]
                else:
                    current_slide.append(item)
            else:
                current_slide.append(item)

        if current_slide:
            slides.append(current_slide)

        return slides
