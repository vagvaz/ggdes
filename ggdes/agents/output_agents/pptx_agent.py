"""PPTX output agent for generating PowerPoint presentations using the pptx skill."""

import json
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from ggdes.agents.output_agents.base import OutputAgent
from ggdes.config import GGDesConfig, get_kb_path


class PptxAgent(OutputAgent):
    """Generate PowerPoint presentation using the pptx skill.

    Uses pptxgenjs for creating professional presentations following
    the patterns documented in the pptx skill.
    """

    # Color palettes from the pptx skill
    COLOR_PALETTES = {
        "midnight": {"primary": "1E2761", "secondary": "CADCFC", "accent": "FFFFFF", "text": "36454F", "light_bg": "F0F4FF"},
        "forest": {"primary": "2C5F2D", "secondary": "97BC62", "accent": "F5F5F5", "text": "2D3436", "light_bg": "F0F7F0"},
        "coral": {"primary": "F96167", "secondary": "F9E795", "accent": "2F3C7E", "text": "2D3436", "light_bg": "FFF5F5"},
        "terracotta": {"primary": "B85042", "secondary": "E7E8D1", "accent": "A7BEAE", "text": "2D3436", "light_bg": "FDF8F6"},
        "ocean": {"primary": "065A82", "secondary": "1C7293", "accent": "21295C", "text": "2D3436", "light_bg": "E8F4F8"},
        "charcoal": {"primary": "36454F", "secondary": "F2F2F2", "accent": "212121", "text": "2D3436", "light_bg": "F5F5F5"},
        "teal": {"primary": "028090", "secondary": "00A896", "accent": "02C39A", "text": "2D3436", "light_bg": "E8F8F8"},
        "berry": {"primary": "6D2E46", "secondary": "A26769", "accent": "ECE2D0", "text": "2D3436", "light_bg": "F8F0F0"},
    }

    def __init__(
        self,
        repo_path: Path,
        config: GGDesConfig,
        analysis_id: str,
        review_feedback: str | None = None,
    ) -> None:
        """Initialize pptx agent."""
        super().__init__(
            repo_path, config, analysis_id, review_feedback=review_feedback
        )
        self.format_name = "pptx"
        self.skill_content = self._load_skill("pptx")

        # Load user context from document plan
        self._load_user_context()

    def _load_plan(self) -> dict[str, Any] | None:
        """Load document plan from KB."""

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_pptx.json"
        )

        if not plan_file.exists():
            return None

        result: dict[str, Any] = json.loads(plan_file.read_text())
        return result

    def _get_content_for_pptx(self) -> str:
        """Extract content from markdown or plan for PPTX generation."""
        import glob

        # Try to find markdown file in output directory (like PDF/DOCX agents do)
        md_path = self.output_dir / f"{self.analysis_id}-*.md"
        md_files = glob.glob(str(md_path))

        if md_files:
            content: str = Path(md_files[0]).read_text()
            # Log info for debugging
            logger.info(f"Found markdown file for PPTX content: {md_files[0]}")
            return content

        # Fallback: build markdown from plan sections (plan has no "content" field)
        plan = self._load_plan()
        if plan:
            logger.info("No markdown file found, building PPTX content from plan sections")
            return self._build_content_from_plan(plan)

        return ""

    def _select_palette(self, content: str) -> dict[str, str]:
        """Select a color palette based on content keywords."""
        content_lower = content.lower()
        if any(kw in content_lower for kw in ["security", "auth", "encrypt", "privacy"]):
            return self.COLOR_PALETTES["ocean"]
        if any(kw in content_lower for kw in ["performance", "optimization", "speed"]):
            return self.COLOR_PALETTES["coral"]
        if any(kw in content_lower for kw in ["refactor", "cleanup", "maintain"]):
            return self.COLOR_PALETTES["forest"]
        if any(kw in content_lower for kw in ["ui", "frontend", "design", "ux"]):
            return self.COLOR_PALETTES["berry"]
        if any(kw in content_lower for kw in ["data", "database", "storage"]):
            return self.COLOR_PALETTES["teal"]
        # Default: midnight executive
        return self.COLOR_PALETTES["midnight"]

    def generate(self, **kwargs: Any) -> Path:
        """Generate PowerPoint presentation.

        Args:
            **kwargs: Additional arguments including auto_generate_diagrams

        Returns:
            Path to generated pptx file
        """
        from rich.console import Console

        console = Console()

        # Setup output path
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.analysis_id}-presentation.pptx"

        console.print("\n[bold blue]Generating PowerPoint Presentation...[/bold blue]")

        # Get content
        content = self._get_content_for_pptx()

        # Select color palette based on content
        palette = self._select_palette(content)
        console.print(f"  [dim]Using {palette['primary']} color palette[/dim]")

        # Inject review feedback if available
        section_fb = self._build_section_feedback_block()
        if self.review_feedback or section_fb:
            feedback_parts = []
            if section_fb:
                feedback_parts.append(section_fb)
            if self.review_feedback:
                feedback_parts.append(
                    "╔══════════════════════════════════════════════════════════════════╗\n"
                    "║         ⚠️  REVIEW FEEDBACK (MUST INCORPORATE)  ⚠️             ║\n"
                    "╚══════════════════════════════════════════════════════════════════╝\n\n"
                    f"{self.review_feedback}"
                )
            feedback_block = (
                "\n\n## User Feedback (MUST INCORPORATE)\n\n"
                + "\n\n".join(feedback_parts)
                + "\n\nThe presentation above must be updated to incorporate this feedback.\n"
            )
            content += feedback_block

        # Parse content into slides
        slides = self._parse_content_to_slides(content)

        if not slides:
            console.print("  [yellow]⚠ No slides generated from content - presentation will be empty[/yellow]")
            logger.warning(f"Empty slides list for PPTX (content length: {len(content)} chars)")

        # Generate diagrams
        diagrams_dir = self.output_dir / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)

        # Load facts for diagram generation
        all_facts = []
        plan = self._load_plan()

        if kwargs.get("auto_generate_diagrams", True) and plan:
            console.print("  [dim]Generating diagrams...[/dim]")

            # Try to load technical facts from KB
            try:
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

        # Collect diagram file paths for integration
        diagram_files = list(diagrams_dir.glob("*.png")) if diagrams_dir.exists() else []

        # Generate pptx using pptxgenjs via Node.js
        pptx_js_script = self._generate_pptx_script(
            slides, output_file, diagrams_dir, diagram_files, palette
        )

        # Write temporary JS file
        js_file = output_dir / f"{self.analysis_id}_generate_pptx.js"
        js_file.write_text(pptx_js_script)

        try:
            # Run pptxgenjs script
            result = subprocess.run(
                ["node", str(js_file)],
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                logger.debug(f"Node.js stdout: {result.stdout.strip()}")
            console.print(f"  [green]✓ Presentation saved:[/green] {output_file}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Node.js script failed (exit {e.returncode}): stderr={e.stderr[:500]}")
            console.print(f"  [yellow]⚠ Node.js error: {e.stderr[:200]}[/yellow]")
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

    def _parse_content_to_slides(self, content: str) -> list[dict[str, Any]]:
        """Parse markdown content into slide structure with layout classification."""
        lines = content.split("\n")
        slides: list[dict[str, Any]] = []
        current_slide: dict[str, Any] | None = None

        for line in lines:
            stripped = line.strip()

            if not stripped:
                continue

            # Title slide (H1)
            if stripped.startswith("# ") and not stripped.startswith("## "):
                if current_slide:
                    slides.append(current_slide)

                title = stripped[2:]
                current_slide = {
                    "type": "title",
                    "title": title,
                    "bullets": [],
                    "content": [],
                    "subheadings": [],
                }

            # Content slide (H2)
            elif stripped.startswith("## ") and not stripped.startswith("### "):
                if current_slide:
                    slides.append(current_slide)

                title = stripped[3:]
                current_slide = {
                    "type": "content",
                    "title": title,
                    "bullets": [],
                    "content": [],
                    "subheadings": [],
                }

            # Subheading
            elif stripped.startswith("### "):
                if current_slide:
                    current_slide["subheadings"].append(stripped[4:])

            # Bullet list
            elif stripped.startswith("- ") or stripped.startswith("* "):
                if current_slide:
                    current_slide["bullets"].append(stripped[2:])

            # Numbered list
            elif stripped[0].isdigit() and ". " in stripped[:4]:
                if current_slide:
                    text = stripped[stripped.find(" ") + 1 :]
                    current_slide["bullets"].append(text)

            # Regular paragraph
            else:
                if current_slide:
                    current_slide["content"].append({"type": "text", "text": stripped})

        if current_slide:
            slides.append(current_slide)

        # Classify slides into rich layouts
        return self._classify_slide_layouts(slides)

    def _classify_slide_layouts(self, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Classify slides into rich layout types based on content."""
        for i, slide in enumerate(slides):
            if slide["type"] == "title":
                slide["layout"] = "title_dark"
                continue

            bullet_count = len(slide.get("bullets", []))
            content_count = len(slide.get("content", []))
            subheading_count = len(slide.get("subheadings", []))

            # Determine layout based on content
            if bullet_count >= 4:
                # Many bullets → icon+text rows layout
                slide["layout"] = "icon_text_rows"
            elif bullet_count >= 2 and content_count >= 1:
                # Mix of bullets and text → two-column layout
                slide["layout"] = "two_column"
            elif subheading_count >= 2:
                # Multiple subheadings → grid cards layout
                slide["layout"] = "grid_cards"
            elif bullet_count >= 2:
                # Few bullets → stat callouts if short, otherwise bullets with accent
                if all(len(b) < 40 for b in slide["bullets"][:3]):
                    slide["layout"] = "stat_callouts"
                else:
                    slide["layout"] = "bullets_with_accent"
            elif content_count >= 1:
                slide["layout"] = "two_column"
            else:
                slide["layout"] = "bullets_with_accent"

            # Assign diagram if available (every 3rd content slide gets a diagram)
            slide["_slide_index"] = i

        return slides

    def _generate_pptx_script(
        self,
        slides: list[dict[str, Any]],
        output_file: Path,
        diagrams_dir: Path,
        diagram_files: list[Path],
        palette: dict[str, str],
    ) -> str:
        """Generate Node.js script for pptxgenjs presentation creation with rich layouts."""
        p = palette
        slide_defs = []
        diagram_idx = 0

        for i, slide in enumerate(slides):
            layout = slide.get("layout", "bullets_with_accent")

            if layout == "title_dark":
                slide_defs.append(self._title_slide(i, slide, p))
            elif layout == "icon_text_rows":
                slide_defs.append(self._icon_text_rows_slide(i, slide, p))
            elif layout == "two_column":
                slide_defs.append(self._two_column_slide(i, slide, p))
            elif layout == "grid_cards":
                slide_defs.append(self._grid_cards_slide(i, slide, p))
            elif layout == "stat_callouts":
                slide_defs.append(self._stat_callouts_slide(i, slide, p))
            elif layout == "bullets_with_accent":
                slide_defs.append(self._bullets_with_accent_slide(i, slide, p))

            # Add diagram to slide if available (rotate through diagrams)
            if diagram_files and i > 0 and i % 3 == 0 and diagram_idx < len(diagram_files):
                slide_defs.append(self._diagram_overlay_slide(i, diagram_files[diagram_idx], p))
                diagram_idx += 1

        # Add remaining diagrams as dedicated slides
        remaining_diagrams = diagram_files[diagram_idx:]
        for diag_file in remaining_diagrams[:3]:
            slide_defs.append(self._full_diagram_slide(diag_file, p))

        # Build the complete script
        palettes_js = f"""
const COLORS = {{
    primary: "{p['primary']}",
    secondary: "{p['secondary']}",
    accent: "{p['accent']}",
    text: "{p['text']}",
    lightBg: "{p['light_bg']}",
}};
"""

        script = f'''const PptxGenJS = require('pptxgenjs');

// Create presentation
const pres = new PptxGenJS();

// Set metadata
pres.author = 'GGDes';
pres.company = 'Generated by GGDes';
pres.subject = 'Technical Design Changes';
pres.title = 'Design Documentation';

// Set layout (16:9)
pres.layout = 'LAYOUT_16x9';

{palettes_js}

// Define slides
{"".join(slide_defs)}

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

    # ── Slide Layout Generators ──────────────────────────────────────────

    def _title_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """Dark title slide with subtitle and accent line."""
        title = self._esc(slide["title"])
        # Extract subtitle from first content item if available
        subtitle = ""
        if slide.get("content"):
            subtitle = self._esc(slide["content"][0].get("text", "")[:80])

        subtitle_js = ""
        if subtitle:
            subtitle_js = (
                f'slide{idx}.addText("{subtitle}", {{\n'
                f'    x: 1.5, y: 3.8, w: 7, h: 0.8,\n'
                f'    fontSize: 18, color: COLORS.secondary, align: "center",\n'
                f'    fontFace: "Calibri", margin: 0\n'
                f'}});'
            )

        return f"""
    // Title Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: COLORS.primary }};

    // Accent bar at top
    slide{idx}.addShape("rect", {{
        x: 0, y: 0, w: 10, h: 0.08,
        fill: {{ color: COLORS.secondary }}
    }});

    // Title
    slide{idx}.addText("{title}", {{
        x: 1, y: 2.2, w: 8, h: 1.5,
        fontSize: 44, bold: true, color: COLORS.accent, align: "center",
        fontFace: "Georgia", margin: 0
    }});

    // Subtitle
    {subtitle_js}

    // Bottom accent line
    slide{idx}.addShape("rect", {{
        x: 3.5, y: 5.0, w: 3, h: 0.06,
        fill: {{ color: COLORS.secondary }}
    }});
"""

    def _icon_text_rows_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """Icon + text rows layout — colored circle with icon, bold header, description."""
        title = self._esc(slide["title"])
        bullets = slide.get("bullets", [])[:6]

        bullet_rows = ""
        for j, bullet in enumerate(bullets):
            y_pos = 1.5 + j * 0.85
            text = self._esc(bullet[:60])
            bullet_rows += f'''
    // Row {j + 1}
    slide{idx}.addShape("oval", {{
        x: 0.6, y: {y_pos}, w: 0.45, h: 0.45,
        fill: {{ color: COLORS.primary }},
        line: {{ color: COLORS.secondary, width: 1 }}
    }});
    slide{idx}.addText("{text}", {{
        x: 1.2, y: {y_pos - 0.05}, w: 8, h: 0.55,
        fontSize: 16, color: COLORS.text,
        fontFace: "Calibri", margin: 0, valign: "middle"
    }});
'''

        return f'''
    // Icon + Text Rows Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: COLORS.lightBg }};

    // Header bar
    slide{idx}.addShape("rect", {{
        x: 0, y: 0, w: 10, h: 1.1,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{title}", {{
        x: 0.6, y: 0.15, w: 8.5, h: 0.8,
        fontSize: 28, bold: true, color: COLORS.accent,
        fontFace: "Georgia", margin: 0
    }});

    // Accent line under header
    slide{idx}.addShape("rect", {{
        x: 0, y: 1.1, w: 10, h: 0.06,
        fill: {{ color: COLORS.secondary }}
    }});

    {bullet_rows}
'''

    def _two_column_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """Two-column layout — text left, visual accent right."""
        title = self._esc(slide["title"])
        bullets = slide.get("bullets", [])[:5]
        content_items = slide.get("content", [])

        left_content = ""
        y_pos = 1.5
        for bullet in bullets:
            text = self._esc(bullet[:70])
            left_content += f'''
    slide{idx}.addText("▸ {text}", {{
        x: 0.6, y: {y_pos}, w: 4.5, h: 0.5,
        fontSize: 15, color: COLORS.text,
        fontFace: "Calibri", margin: 0
    }});
'''
            y_pos += 0.55

        # Add text content on right side
        right_content = ""
        if content_items:
            right_text = self._esc(content_items[0].get("text", "")[:120])
            right_content = f'''
    // Right column content
    slide{idx}.addShape("rect", {{
        x: 5.5, y: 1.5, w: 4, h: 2.5,
        fill: {{ color: COLORS.lightBg }},
        rectRadius: 0.15
    }});
    slide{idx}.addShape("rect", {{
        x: 5.5, y: 1.5, w: 0.08, h: 2.5,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{right_text}", {{
        x: 5.8, y: 1.6, w: 3.5, h: 2.3,
        fontSize: 14, color: COLORS.text,
        fontFace: "Calibri", margin: 0
    }});
'''

        return f'''
    // Two Column Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: "FFFFFF" }};

    // Title with left accent bar
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 0.3, w: 0.08, h: 0.7,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{title}", {{
        x: 0.6, y: 0.3, w: 8.5, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.primary,
        fontFace: "Georgia", margin: 0
    }});

    // Divider line
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 1.15, w: 9.2, h: 0.04,
        fill: {{ color: COLORS.secondary }}
    }});

    // Left column - bullets
    {left_content}

    // Right column
    {right_content}
'''

    def _grid_cards_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """2x2 or 2x3 grid of content cards."""
        title = self._esc(slide["title"])
        subheadings = slide.get("subheadings", [])[:6]
        bullets = slide.get("bullets", [])

        # Build cards from subheadings + bullets
        cards = []
        for j in range(max(len(subheadings), len(bullets))):
            heading = subheadings[j] if j < len(subheadings) else ""
            body = bullets[j] if j < len(bullets) else ""
            if heading or body:
                cards.append({"heading": heading, "body": body})

        if not cards:
            # Fallback to bullets with accent
            return self._bullets_with_accent_slide(idx, slide, p)

        card_js = ""
        # 2-column grid layout
        for j, card in enumerate(cards[:6]):
            col = j % 2
            row = j // 2
            x_pos = 0.5 + col * 4.7
            y_pos = 1.5 + row * 1.7

            heading = self._esc(card["heading"][:40])
            body = self._esc(card["body"][:80])

            heading_js = ""
            if heading:
                heading_js = (
                    f'slide{idx}.addText("{heading}", {{\n'
                    f'    x: {x_pos + 0.25}, y: {y_pos + 0.1}, w: 4, h: 0.4,\n'
                    f'    fontSize: 16, bold: true, color: COLORS.primary,\n'
                    f'    fontFace: "Georgia", margin: 0\n'
                    f'}});'
                )
            body_js = ""
            if body:
                body_js = (
                    f'slide{idx}.addText("{body}", {{\n'
                    f'    x: {x_pos + 0.25}, y: {y_pos + 0.55}, w: 4, h: 0.7,\n'
                    f'    fontSize: 13, color: COLORS.text,\n'
                    f'    fontFace: "Calibri", margin: 0\n'
                    f'}});'
                )

            card_js += f"""
    // Card {j + 1}
    slide{idx}.addShape("rect", {{
        x: {x_pos}, y: {y_pos}, w: 4.4, h: 1.4,
        fill: {{ color: COLORS.lightBg }},
        rectRadius: 0.1,
        line: {{ color: COLORS.secondary, width: 0.5 }}
    }});
    slide{idx}.addShape("rect", {{
        x: {x_pos}, y: {y_pos}, w: 0.06, h: 1.4,
        fill: {{ color: COLORS.primary }}
    }});
    {heading_js}
    {body_js}
"""

        return f'''
    // Grid Cards Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: "FFFFFF" }};

    // Title
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 0.3, w: 0.08, h: 0.7,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{title}", {{
        x: 0.6, y: 0.3, w: 8.5, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.primary,
        fontFace: "Georgia", margin: 0
    }});

    // Divider
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 1.15, w: 9.2, h: 0.04,
        fill: {{ color: COLORS.secondary }}
    }});

    {card_js}
'''

    def _stat_callouts_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """Large stat callouts — big numbers with small labels."""
        title = self._esc(slide["title"])
        bullets = slide.get("bullets", [])[:4]

        # Extract key phrases as "stats" — first few words of each bullet
        stat_items: list[dict[str, str]] = []
        for bullet in bullets:
            # Take first 3-4 words as the "stat"
            words = bullet.split()
            stat_value = " ".join(words[: min(4, len(words))])
            label = " ".join(words[min(4, len(words)) :]) if len(words) > 4 else ""
            stat_items.append({"stat": stat_value, "label": label})

        stat_js = ""
        for j, stat_item in enumerate(stat_items[:4]):
            col = j % 2
            row = j // 2
            x_pos = 0.5 + col * 4.7
            y_pos = 1.5 + row * 2.0

            stat_text = self._esc(stat_item["stat"][:30])
            label_text = self._esc(stat_item["label"][:60])

            label_js = ""
            if label_text:
                label_js = (
                    f'slide{idx}.addText("{label_text}", {{\n'
                    f'    x: {x_pos + 0.3}, y: {y_pos + 1.0}, w: 3.8, h: 0.5,\n'
                    f'    fontSize: 13, color: COLORS.secondary,\n'
                    f'    fontFace: "Calibri", margin: 0, align: "center"\n'
                    f'}});'
                )

            stat_js += f"""
    // Stat {j + 1}
    slide{idx}.addShape("rect", {{
        x: {x_pos}, y: {y_pos}, w: 4.4, h: 1.7,
        fill: {{ color: COLORS.primary }},
        rectRadius: 0.1
    }});
    slide{idx}.addText("{stat_text}", {{
        x: {x_pos + 0.3}, y: {y_pos + 0.2}, w: 3.8, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.accent,
        fontFace: "Georgia", margin: 0, align: "center"
    }});
    {label_js}
"""

        return f'''
    // Stat Callouts Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: "FFFFFF" }};

    // Title
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 0.3, w: 0.08, h: 0.7,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{title}", {{
        x: 0.6, y: 0.3, w: 8.5, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.primary,
        fontFace: "Georgia", margin: 0
    }});

    // Divider
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 1.15, w: 9.2, h: 0.04,
        fill: {{ color: COLORS.secondary }}
    }});

    {stat_js}
'''

    def _bullets_with_accent_slide(self, idx: int, slide: dict[str, Any], p: dict[str, str]) -> str:
        """Clean bullets with left accent bar — improved version of basic layout."""
        title = self._esc(slide["title"])
        bullets = slide.get("bullets", [])[:6]

        bullet_js = ""
        for j, bullet in enumerate(bullets):
            y_pos = 1.5 + j * 0.65
            text = self._esc(bullet[:80])
            bullet_js += f'''
    slide{idx}.addShape("rect", {{
        x: 0.6, y: {y_pos + 0.1}, w: 0.06, h: 0.35,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{text}", {{
        x: 0.85, y: {y_pos}, w: 8.5, h: 0.5,
        fontSize: 16, color: COLORS.text,
        fontFace: "Calibri", margin: 0
    }});
'''

        return f'''
    // Bullets with Accent Slide
    let slide{idx} = pres.addSlide();
    slide{idx}.background = {{ color: "FFFFFF" }};

    // Title with accent
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 0.3, w: 0.08, h: 0.7,
        fill: {{ color: COLORS.primary }}
    }});
    slide{idx}.addText("{title}", {{
        x: 0.6, y: 0.3, w: 8.5, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.primary,
        fontFace: "Georgia", margin: 0
    }});

    // Divider
    slide{idx}.addShape("rect", {{
        x: 0.4, y: 1.15, w: 9.2, h: 0.04,
        fill: {{ color: COLORS.secondary }}
    }});

    {bullet_js}
'''

    def _diagram_overlay_slide(self, idx: int, diagram_path: Path, p: dict[str, str]) -> str:
        """Slide with diagram image as visual element."""
        return f'''
    // Diagram Slide
    let diagramSlide{idx} = pres.addSlide();
    diagramSlide{idx}.background = {{ color: COLORS.lightBg }};

    diagramSlide{idx}.addText("Architecture Overview", {{
        x: 0.6, y: 0.3, w: 8.5, h: 0.7,
        fontSize: 28, bold: true, color: COLORS.primary,
        fontFace: "Georgia", margin: 0
    }});

    diagramSlide{idx}.addShape("rect", {{
        x: 0.4, y: 1.1, w: 9.2, h: 0.04,
        fill: {{ color: COLORS.secondary }}
    }});

    diagramSlide{idx}.addImage({{
        path: "{diagram_path}",
        x: 0.5, y: 1.4, w: 9, h: 4.2,
        sizing: {{ type: 'contain', w: 9, h: 4.2 }}
    }});
'''

    def _full_diagram_slide(self, diagram_path: Path, p: dict[str, str]) -> str:
        """Full-slide diagram with dark background."""
        return f'''
    // Full Diagram Slide
    let fullDiag = pres.addSlide();
    fullDiag.background = {{ color: COLORS.primary }};

    fullDiag.addImage({{
        path: "{diagram_path}",
        x: 0.5, y: 0.8, w: 9, h: 4.5,
        sizing: {{ type: 'contain', w: 9, h: 4.5 }}
    }});
'''

    def _esc(self, s: str) -> str:
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
            raise RuntimeError(f"Failed to convert to pptx: {e}") from e
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

        slide_content = "\n\n---\n\n".join(
            ["\n".join(group) for group in self._group_into_slides(slides)]
        )

        return slide_content

    def _group_into_slides(self, items: list[str]) -> list[list[str]]:
        """Group content items into slides."""
        slides: list[list[str]] = []
        current_slide: list[str] = []

        for item in items:
            if item.startswith("# "):
                if current_slide:
                    slides.append(current_slide)
                current_slide = [item]
            elif item.startswith("## "):
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
