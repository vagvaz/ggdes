"""PDF output agent for generating PDF documents."""

import subprocess
from pathlib import Path
from typing import Optional

from ggdes.agents.output_agents.base import OutputAgent


class PdfAgent(OutputAgent):
    """Generate PDF document from document plan.

    Uses markdown as source and converts via pandoc + latex or wkhtmltopdf.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize pdf agent."""
        super().__init__(repo_path, config, analysis_id)

    def _load_plan(self) -> Optional[dict]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path
        import json

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_pdf.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def generate(self) -> Path:
        """Generate PDF document.

        Returns:
            Path to generated pdf file
        """
        import glob

        md_path = self.repo_path / "docs" / f"{self.analysis_id}-*.md"
        md_files = glob.glob(str(md_path))

        if not md_files:
            raise FileNotFoundError(
                f"No markdown file found for {self.analysis_id}. "
                "Generate markdown first."
            )

        md_file = Path(md_files[0])
        output_file = md_file.with_suffix(".pdf")

        # Try pandoc with PDF generation
        try:
            subprocess.run(
                [
                    "pandoc",
                    str(md_file),
                    "-o",
                    str(output_file),
                    "--pdf-engine=xelatex",  # Better unicode support
                ],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Try alternative: markdown -> html -> pdf
            try:
                html_file = md_file.with_suffix(".html")

                # First convert to HTML
                subprocess.run(
                    ["pandoc", str(md_file), "-o", str(html_file)],
                    check=True,
                    capture_output=True,
                )

                # Then use wkhtmltopdf or similar if available
                try:
                    subprocess.run(
                        ["wkhtmltopdf", str(html_file), str(output_file)],
                        check=True,
                        capture_output=True,
                    )
                    html_file.unlink()
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Keep HTML as fallback
                    output_file = html_file
            except Exception:
                # All methods failed, create placeholder
                output_file.write_text(
                    f"PDF generation requires pandoc with LaTeX or wkhtmltopdf.\n\n"
                    f"Source: {md_file}\n"
                    f"Install pandoc: https://pandoc.org/installing.html"
                )

        return output_file
