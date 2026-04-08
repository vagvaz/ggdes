"""PDF output agent for generating PDF documents using the pdf skill."""

import json
import subprocess
from pathlib import Path
from typing import Optional

from ggdes.agents.output_agents.base import OutputAgent


class PdfAgent(OutputAgent):
    """Generate PDF document using the pdf skill.

    Uses reportlab for creating professional PDF documents following
    the patterns documented in the pdf skill.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize pdf agent."""
        super().__init__(repo_path, config, analysis_id)
        self.format_name = "pdf"
        self.skill_content = self._load_skill("pdf")

        # Load user context from document plan
        self._load_user_context()

    def _load_plan(self) -> Optional[dict]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_pdf.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def _get_content_for_pdf(self) -> str:
        """Extract content from markdown or plan for PDF generation."""
        import glob

        # Try to find markdown file
        md_path = self.repo_path / "docs" / f"{self.analysis_id}-*.md"
        md_files = glob.glob(str(md_path))

        if md_files:
            return Path(md_files[0]).read_text()

        # Fallback: use plan content
        plan = self._load_plan()
        if plan:
            return plan.get("content", "")

        return ""

    def generate(self, auto_generate_diagrams: bool = True) -> Path:
        """Generate PDF document using pdf skill patterns with integrated diagrams.

        Args:
            auto_generate_diagrams: Whether to auto-generate diagrams from facts

        Returns:
            Path to generated pdf file
        """
        from rich.console import Console

        console = Console()

        # Setup output path
        output_dir = self.repo_path / "docs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.analysis_id}-document.pdf"

        console.print(f"\n[bold blue]Generating PDF Document...[/bold blue]")

        # Get content
        content = self._get_content_for_pdf()

        # Generate diagrams
        diagrams_dir = output_dir / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)

        # Load facts for diagram generation
        if auto_generate_diagrams:
            console.print("  [dim]Generating diagrams...[/dim]")
            all_facts = []
            plan = self._load_plan()

            if plan:
                # Try to load technical facts from KB
                try:
                    from ggdes.config import get_kb_path
                    from ggdes.schemas import TechnicalFact
                    import json

                    facts_dir = (
                        get_kb_path(self.config, self.analysis_id) / "technical_facts"
                    )
                    if facts_dir.exists():
                        for fact_file in facts_dir.glob("*.json"):
                            data = json.loads(fact_file.read_text())
                            all_facts.append(TechnicalFact(**data))
                except Exception as e:
                    console.print(f"  [dim]Could not load facts: {e}[/dim]")

                # Generate diagrams
                if all_facts:
                    diagram_list = self._generate_diagrams_for_facts(
                        all_facts, diagrams_dir, ["architecture", "flow", "class"]
                    )
                    console.print(
                        f"  [green]✓ Generated {len(diagram_list)} diagrams[/green]"
                    )

        try:
            # Try reportlab first with diagram integration
            self._generate_with_reportlab(content, output_file, diagrams_dir)
            console.print(f"  [green]✓ Document saved:[/green] {output_file}")
        except ImportError:
            # Fallback to pandoc
            console.print("  [yellow]⚠ Using pandoc fallback[/yellow]")
            self._fallback_to_pandoc(content, output_file)
        except Exception as e:
            # Any other error, try pandoc
            console.print(f"  [yellow]⚠ Reportlab failed ({e}), using pandoc[/yellow]")
            self._fallback_to_pandoc(content, output_file)

        return output_file

    def _generate_with_reportlab(
        self, content: str, output_file: Path, diagrams_dir: Path
    ) -> None:
        """Generate PDF using reportlab following skill patterns with diagrams."""
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            PageBreak,
            Image,
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER

        # Create document
        doc = SimpleDocTemplate(
            str(output_file),
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )

        # Styles
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="CustomTitle",
                parent=styles["Heading1"],
                fontSize=24,
                spaceAfter=30,
                alignment=TA_CENTER,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CustomHeading2",
                parent=styles["Heading2"],
                fontSize=16,
                spaceAfter=12,
                spaceBefore=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CustomHeading3",
                parent=styles["Heading3"],
                fontSize=14,
                spaceAfter=10,
                spaceBefore=10,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CustomBody",
                parent=styles["Normal"],
                fontSize=11,
                leading=14,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Bullet",
                parent=styles["Normal"],
                fontSize=11,
                leading=14,
                leftIndent=20,
                bulletIndent=10,
            )
        )
        styles.add(
            ParagraphStyle(
                name="DiagramCaption",
                parent=styles["Normal"],
                fontSize=10,
                alignment=TA_CENTER,
                textColor="gray",
                spaceBefore=6,
                spaceAfter=12,
            )
        )

        # Parse and build content
        story = []
        lines = content.split("\n")

        for line in lines:
            stripped = line.strip()

            if not stripped:
                story.append(Spacer(1, 6))
                continue

            # Title (H1)
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped[2:]
                story.append(Paragraph(self._escape_xml(title), styles["CustomTitle"]))
                story.append(Spacer(1, 12))

            # Heading 2
            elif stripped.startswith("## ") and not stripped.startswith("### "):
                title = stripped[3:]
                story.append(
                    Paragraph(self._escape_xml(title), styles["CustomHeading2"])
                )

            # Heading 3
            elif stripped.startswith("### "):
                title = stripped[4:]
                story.append(
                    Paragraph(self._escape_xml(title), styles["CustomHeading3"])
                )

            # Bullet list
            elif stripped.startswith("- ") or stripped.startswith("* "):
                text = stripped[2:]
                story.append(
                    Paragraph(
                        f"• {self._escape_xml(text)}",
                        styles["Bullet"],
                    )
                )

            # Numbered list
            elif stripped[0].isdigit() and ". " in stripped[:4]:
                text = stripped[stripped.find(" ") + 1 :]
                story.append(
                    Paragraph(
                        f"{stripped[0]}. {self._escape_xml(text)}",
                        styles["Bullet"],
                    )
                )

            # Regular paragraph
            else:
                story.append(
                    Paragraph(self._escape_xml(stripped), styles["CustomBody"])
                )

        # Add diagrams section if diagrams exist
        if diagrams_dir.exists():
            diagram_files = list(diagrams_dir.glob("*.png"))
            if diagram_files:
                story.append(PageBreak())
                story.append(Paragraph("Diagrams", styles["CustomHeading2"]))
                story.append(Spacer(1, 12))
                story.append(
                    Paragraph(
                        "Visual representations of the system architecture and component relationships.",
                        styles["CustomBody"],
                    )
                )
                story.append(Spacer(1, 12))

                # Add each diagram
                for diagram_file in diagram_files[:3]:  # Limit to 3 diagrams
                    try:
                        # Add image with max width of 6 inches
                        img = Image(str(diagram_file), width=6 * inch, height=4 * inch)
                        story.append(img)
                        story.append(
                            Paragraph(
                                f"Figure: {diagram_file.stem.replace('_', ' ').title()}",
                                styles["DiagramCaption"],
                            )
                        )
                        story.append(Spacer(1, 12))
                    except Exception as e:
                        story.append(
                            Paragraph(
                                f"[Could not embed diagram: {e}]", styles["CustomBody"]
                            )
                        )

        # Build PDF
        doc.build(story)

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters for reportlab."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _fallback_to_pandoc(self, content: str, output_file: Path) -> None:
        """Fallback to pandoc for PDF generation."""
        temp_md = output_file.with_suffix(".temp.md")
        temp_md.write_text(content)

        try:
            subprocess.run(
                [
                    "pandoc",
                    str(temp_md),
                    "-o",
                    str(output_file),
                    "--pdf-engine=xelatex",
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Try without xelatex
            try:
                subprocess.run(
                    ["pandoc", str(temp_md), "-o", str(output_file)],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to convert to PDF: {e}")
        finally:
            if temp_md.exists():
                temp_md.unlink()
