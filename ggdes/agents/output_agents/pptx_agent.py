"""PPTX output agent for generating PowerPoint presentations using the pptx skill."""

import json
import subprocess
from pathlib import Path

from ggdes.agents.output_agents.base import OutputAgent


class PptxAgent(OutputAgent):
    """Generate PowerPoint presentation using the pptx skill.

    Uses pptxgenjs for creating professional presentations following
    the patterns documented in the pptx skill.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize pptx agent."""
        super().__init__(repo_path, config, analysis_id)
        self.format_name = "pptx"
        self.skill_content = self._load_skill("pptx")

        # Load user context from document plan
        self._load_user_context()

    def _load_plan(self) -> dict | None:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_pptx.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def _get_content_for_pptx(self) -> str:
        """Extract content from markdown or plan for PPTX generation."""
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
        """Generate PowerPoint presentation using pptx skill patterns with integrated diagrams.

        Args:
            auto_generate_diagrams: Whether to auto-generate diagrams from facts

        Returns:
            Path to generated pptx file
        """
        from rich.console import Console

        console = Console()

        # Setup output path
        output_dir = self.repo_path / "docs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.analysis_id}-presentation.pptx"

        console.print("\n[bold blue]Generating PowerPoint Presentation...[/bold blue]")

        # Get content
        content = self._get_content_for_pptx()

        # Parse content into slides
        slides = self._parse_content_to_slides(content)

        # Generate diagrams
        diagrams_dir = output_dir / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)

        # Load facts for diagram generation
        all_facts = []
        plan = self._load_plan()

        if auto_generate_diagrams and plan:
            console.print("  [dim]Generating diagrams...[/dim]")

            # Try to load technical facts from KB
            try:
                import json

                from ggdes.config import get_kb_path
                from ggdes.schemas import TechnicalFact

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

        # Generate pptx using pptxgenjs via Node.js
        pptx_js_script = self._generate_pptx_script(slides, output_file, diagrams_dir)

        # Write temporary JS file
        js_file = output_dir / f"{self.analysis_id}_generate_pptx.js"
        js_file.write_text(pptx_js_script)

        try:
            # Run pptxgenjs script
            subprocess.run(
                ["node", str(js_file)],
                check=True,
                capture_output=True,
                text=True,
            )
            console.print(f"  [green]✓ Presentation saved:[/green] {output_file}")

        except subprocess.CalledProcessError:
            console.print("  [yellow]⚠ Falling back to pandoc[/yellow]")
            self._fallback_to_pandoc(content, output_file)
        except FileNotFoundError:
            console.print("  [yellow]⚠ Node.js not available, using pandoc[/yellow]")
            self._fallback_to_pandoc(content, output_file)
        finally:
            # Cleanup temp file
            if js_file.exists():
                js_file.unlink()

        return output_file

    def _parse_content_to_slides(self, content: str) -> list[dict]:
        """Parse markdown content into slide structure."""
        lines = content.split("\n")
        slides = []
        current_slide = None

        for line in lines:
            stripped = line.strip()

            if not stripped:
                continue

            # Title slide (H1)
            if stripped.startswith("# ") and not stripped.startswith("## "):
                # Save previous slide
                if current_slide:
                    slides.append(current_slide)

                title = stripped[2:]
                current_slide = {
                    "type": "title",
                    "title": title,
                    "bullets": [],
                    "content": [],
                }

            # Content slide (H2)
            elif stripped.startswith("## ") and not stripped.startswith("### "):
                # Save previous slide
                if current_slide:
                    slides.append(current_slide)

                title = stripped[3:]
                current_slide = {
                    "type": "content",
                    "title": title,
                    "bullets": [],
                    "content": [],
                }

            # Subheading
            elif stripped.startswith("### "):
                if current_slide:
                    current_slide["content"].append(
                        {"type": "subheading", "text": stripped[4:]}
                    )

            # Bullet list
            elif stripped.startswith("- ") or stripped.startswith("* "):
                if current_slide:
                    current_slide["bullets"].append(stripped[2:])

            # Numbered list
            elif stripped[0].isdigit() and ". " in stripped[:4]:
                if current_slide:
                    text = stripped[stripped.find(" ") + 1 :]
                    current_slide["bullets"].append(text)

            # Regular paragraph (add as content note)
            else:
                if current_slide:
                    current_slide["content"].append({"type": "text", "text": stripped})

        # Add last slide
        if current_slide:
            slides.append(current_slide)

        return slides

    def _generate_pptx_script(
        self, slides: list[dict], output_file: Path, diagrams_dir: Path
    ) -> str:
        """Generate Node.js script for pptxgenjs presentation creation with diagrams.

        Following the patterns from the pptx skill documentation.
        """
        # Build slide definitions
        slide_defs = []

        for i, slide in enumerate(slides):
            if slide["type"] == "title":
                # Title slide
                slide_def = f"""
    // Title Slide {i + 1}
    let slide{i} = pres.addSlide();
    slide{i}.background = {{ color: "1E2761" }};  // Midnight Executive palette
    slide{i}.addText("{self._escape_js_string(slide["title"])}", {{
        x: 0.5, y: 2.5, w: 9, h: 1.5,
        fontSize: 44, bold: true, color: "FFFFFF", align: "center",
        fontFace: "Arial Black"
    }});
"""
                slide_defs.append(slide_def)

            else:
                # Content slide
                bullets_js = ""
                if slide["bullets"]:
                    # Limit to 6 bullets per slide (as per skill guidelines)
                    limited_bullets = slide["bullets"][:6]
                    bullets_text = "\\n".join(
                        f"• {self._escape_js_string(b)[:50]}"
                        for b in limited_bullets  # Limit to 6 words per bullet
                    )
                    bullets_js = f"""
    slide{i}.addText("{bullets_text}", {{
        x: 0.5, y: 1.8, w: 5.5, h: 4,
        fontSize: 18, color: "36454F",
        bullet: true,
        fontFace: "Calibri"
    }});
"""

                slide_def = f"""
    // Content Slide {i + 1}
    let slide{i} = pres.addSlide();
    slide{i}.addText("{self._escape_js_string(slide["title"])}", {{
        x: 0.5, y: 0.5, w: 9, h: 1,
        fontSize: 36, bold: true, color: "1E2761",
        fontFace: "Arial Black"
    }});
    {bullets_js}
"""
                slide_defs.append(slide_def)

        # Add diagram slides
        diagram_slides = ""
        if diagrams_dir.exists():
            diagram_files = list(diagrams_dir.glob("*.png"))
            if diagram_files:
                diagram_slides = """
    // Diagram Overview Slide
    let diagramSlide = pres.addSlide();
    diagramSlide.addText("System Architecture", {{
        x: 0.5, y: 0.5, w: 9, h: 1,
        fontSize: 36, bold: true, color: "1E2761",
        fontFace: "Arial Black"
    }});
"""
                for i, diag_file in enumerate(
                    diagram_files[:3]
                ):  # Max 3 diagram slides
                    diagram_slides += f"""
    // Add diagram image
    diagramSlide.addImage({{
        path: "{str(diag_file)}",
        x: 0.5, y: 1.8, w: 9, h: 4.5,
        sizing: {{ type: 'contain', w: 9, h: 4.5 }}
    }});
"""

        script = f'''const PptxGenJS = require('pptxgenjs');
const fs = require('fs');

// Create presentation
const pres = new PptxGenJS();

// Set metadata
pres.author = 'GGDes';
pres.company = 'Generated by GGDes';
pres.subject = 'Technical Design Changes';
pres.title = 'Design Documentation';

// Set layout (16:9)
pres.layout = 'LAYOUT_16x9';

// Define slides
{"".join(slide_defs)}
{diagram_slides}

// Save presentation
pres.writeFile({{ fileName: "{output_file}" }})
    .then(() => {{
        console.log("Presentation generated successfully");
    }})
    .catch(err => {{
        console.error("Error:", err);
        process.exit(1);
    }});
'''
        return script

    def _escape_js_string(self, s: str) -> str:
        """Escape string for JavaScript."""
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    def _fallback_to_pandoc(self, content: str, output_file: Path) -> None:
        """Fallback to pandoc for pptx generation."""
        # Create slide-friendly markdown
        slides_md = self._create_slide_markdown(content)
        temp_md = output_file.with_suffix(".temp.md")
        temp_md.write_text(slides_md)

        try:
            subprocess.run(
                ["pandoc", str(temp_md), "-o", str(output_file)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to convert to pptx: {e}")
        finally:
            if temp_md.exists():
                temp_md.unlink()

    def _create_slide_markdown(self, content: str) -> str:
        """Create slide-friendly markdown from full document."""
        lines = content.split("\n")
        slides = []

        for line in lines:
            if line.startswith("# "):
                slides.append(f"# {line[2:]}")
            elif line.startswith("## "):
                slides.append(f"## {line[3:]}")
            elif line.startswith("- ") and len(slides) > 0:
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
