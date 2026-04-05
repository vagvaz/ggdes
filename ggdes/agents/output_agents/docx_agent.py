"""Docx output agent for generating Word documents using the docx skill."""

import json
import subprocess
from pathlib import Path
from typing import Optional

from ggdes.agents.output_agents.base import OutputAgent


class DocxAgent(OutputAgent):
    """Generate Word document using the docx skill.

    Uses docx-js for creating professional Word documents following
    the patterns documented in the docx skill.
    """

    def __init__(self, repo_path: Path, config, analysis_id: str):
        """Initialize docx agent."""
        super().__init__(repo_path, config, analysis_id)
        self.skill_content = self._load_skill("docx")

    def _load_plan(self) -> Optional[dict]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_docx.json"
        )

        if not plan_file.exists():
            return None

        return json.loads(plan_file.read_text())

    def _get_content_for_docx(self) -> str:
        """Extract content from markdown or plan for docx generation."""
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

    def generate(self) -> Path:
        """Generate Word document using docx skill patterns.

        Returns:
            Path to generated docx file
        """
        # Setup output path
        output_dir = self.repo_path / "docs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{self.analysis_id}-document.docx"

        # Get content
        content = self._get_content_for_docx()

        # Generate docx using docx-js via Node.js
        docx_js_script = self._generate_docx_script(content)

        # Write temporary JS file
        js_file = output_dir / f"{self.analysis_id}_generate_docx.js"
        js_file.write_text(docx_js_script)

        try:
            # Run docx-js script
            subprocess.run(
                ["node", str(js_file)],
                check=True,
                capture_output=True,
                text=True,
            )

            # Validate output if validation script exists
            self._validate_docx(output_file)

        except subprocess.CalledProcessError as e:
            # Fallback to pandoc if docx-js fails
            self._fallback_to_pandoc(content, output_file)
        except FileNotFoundError:
            # Node not available, use pandoc
            self._fallback_to_pandoc(content, output_file)
        finally:
            # Cleanup temp file
            if js_file.exists():
                js_file.unlink()

        return output_file

    def _generate_docx_script(self, content: str) -> str:
        """Generate Node.js script for docx-js document creation.

        Following the patterns from the docx skill documentation.
        """
        # Parse content into structured sections
        sections = self._parse_content_to_sections(content)

        script = f'''const {{ Document, Packer, Paragraph, TextRun, HeadingLevel,
            Table, TableRow, TableCell, Header, Footer, PageNumber,
            AlignmentType, BorderStyle, WidthType, ShadingType,
            LevelFormat, PageBreak }} = require('docx');
const fs = require('fs');

// Create document following skill patterns
const doc = new Document({{
    styles: {{
        default: {{
            document: {{
                run: {{ font: "Arial", size: 24 }}  // 12pt default
            }}
        }},
        paragraphStyles: [
            {{
                id: "Heading1",
                name: "Heading 1",
                basedOn: "Normal",
                next: "Normal",
                quickFormat: true,
                run: {{ size: 32, bold: true, font: "Arial" }},
                paragraph: {{ spacing: {{ before: 240, after: 240 }}, outlineLevel: 0 }}
            }},
            {{
                id: "Heading2",
                name: "Heading 2",
                basedOn: "Normal",
                next: "Normal",
                quickFormat: true,
                run: {{ size: 28, bold: true, font: "Arial" }},
                paragraph: {{ spacing: {{ before: 180, after: 180 }}, outlineLevel: 1 }}
            }},
            {{
                id: "Heading3",
                name: "Heading 3",
                basedOn: "Normal",
                next: "Normal",
                quickFormat: true,
                run: {{ size: 26, bold: true, font: "Arial" }},
                paragraph: {{ spacing: {{ before: 120, after: 120 }}, outlineLevel: 2 }}
            }}
        ]
    }},
    numbering: {{
        config: [
            {{
                reference: "bullets",
                levels: [
                    {{
                        level: 0,
                        format: LevelFormat.BULLET,
                        text: "•",
                        alignment: AlignmentType.LEFT,
                        style: {{
                            paragraph: {{
                                indent: {{ left: 720, hanging: 360 }}
                            }}
                        }}
                    }}
                ]
            }},
            {{
                reference: "numbers",
                levels: [
                    {{
                        level: 0,
                        format: LevelFormat.DECIMAL,
                        text: "%1.",
                        alignment: AlignmentType.LEFT,
                        style: {{
                            paragraph: {{
                                indent: {{ left: 720, hanging: 360 }}
                            }}
                        }}
                    }}
                ]
            }}
        ]
    }},
    sections: [{{
        properties: {{
            page: {{
                size: {{
                    width: 12240,   // 8.5 inches in DXA
                    height: 15840   // 11 inches in DXA
                }},
                margin: {{
                    top: 1440,
                    right: 1440,
                    bottom: 1440,
                    left: 1440  // 1 inch margins
                }}
            }}
        }},
        children: {sections}
    }}]
}});

// Generate document
Packer.toBuffer(doc).then(buffer => {{
    fs.writeFileSync("{output_file}", buffer);
    console.log("Document generated successfully");
}}).catch(err => {{
    console.error("Error:", err);
    process.exit(1);
}});
'''
        return script

    def _parse_content_to_sections(self, content: str) -> str:
        """Parse markdown content into docx-js section structure."""
        lines = content.split("\n")
        paragraphs = []

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Heading 1
            if line.startswith("# ") and not line.startswith("## "):
                title = line[2:].strip()
                paragraphs.append(
                    f"new Paragraph({{ heading: HeadingLevel.HEADING_1, "
                    f'children: [new TextRun({{ text: "{self._escape_js_string(title)}", bold: true }})] }})'
                )

            # Heading 2
            elif line.startswith("## ") and not line.startswith("### "):
                title = line[3:].strip()
                paragraphs.append(
                    f"new Paragraph({{ heading: HeadingLevel.HEADING_2, "
                    f'children: [new TextRun({{ text: "{self._escape_js_string(title)}", bold: true }})] }})'
                )

            # Heading 3
            elif line.startswith("### "):
                title = line[4:].strip()
                paragraphs.append(
                    f"new Paragraph({{ heading: HeadingLevel.HEADING_3, "
                    f'children: [new TextRun({{ text: "{self._escape_js_string(title)}", bold: true }})] }})'
                )

            # Bullet list
            elif line.startswith("- ") or line.startswith("* "):
                text = line[2:].strip()
                paragraphs.append(
                    f'new Paragraph({{ numbering: {{ reference: "bullets", level: 0 }}, '
                    f'children: [new TextRun("{self._escape_js_string(text)}")] }})'
                )

            # Numbered list
            elif line[0].isdigit() and ". " in line[:4]:
                text = line[line.find(" ") + 1 :].strip()
                paragraphs.append(
                    f'new Paragraph({{ numbering: {{ reference: "numbers", level: 0 }}, '
                    f'children: [new TextRun("{self._escape_js_string(text)}")] }})'
                )

            # Regular paragraph
            else:
                paragraphs.append(
                    f"new Paragraph({{ "
                    f'children: [new TextRun("{self._escape_js_string(line)}")] }})'
                )

            i += 1

        return "[\n            " + ",\n            ".join(paragraphs) + "\n        ]"

    def _escape_js_string(self, s: str) -> str:
        """Escape string for JavaScript."""
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    def _validate_docx(self, docx_path: Path) -> None:
        """Validate generated docx file if validator is available."""
        # Check for validation script in skill directory
        validate_script = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "docx"
            / "scripts"
            / "office"
            / "validate.py"
        )

        if validate_script.exists() and docx_path.exists():
            try:
                subprocess.run(
                    ["python", str(validate_script), str(docx_path)],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass  # Validation is optional

    def _fallback_to_pandoc(self, content: str, output_file: Path) -> None:
        """Fallback to pandoc for docx generation."""
        # Write content to temp markdown
        temp_md = output_file.with_suffix(".temp.md")
        temp_md.write_text(content)

        try:
            subprocess.run(
                ["pandoc", str(temp_md), "-o", str(output_file)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to convert to docx: {e}")
        finally:
            if temp_md.exists():
                temp_md.unlink()
