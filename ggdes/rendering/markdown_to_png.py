"""Markdown to PNG renderer using Playwright."""

import asyncio
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class MarkdownToPngRenderer:
    """Renders markdown files to PNG images using Playwright."""

    def __init__(self, output_dir: Path, theme: str = "light", width: int = 1200):
        """Initialize the markdown to PNG renderer.

        Args:
            output_dir: Directory to save PNG images
            theme: "light" or "dark"
            width: Viewport width in pixels
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.theme = theme if theme in ("light", "dark") else "light"
        self.width = width

    def render(self, markdown_path: Path, sections: bool = False) -> list[Path]:
        """Render a markdown file to PNG images.

        Args:
            markdown_path: Path to the markdown file
            sections: If True, render each ## section as a separate PNG.
                      If False, render the entire document as one PNG.

        Returns:
            List of paths to generated PNG files
        """
        markdown_content = markdown_path.read_text()

        if sections:
            # Split by sections and render each separately
            section_parts = self._split_by_sections(markdown_content)
            png_paths = []

            for i, (title, content) in enumerate(section_parts):
                if not content.strip():
                    continue

                # Generate filename
                if title:
                    safe_title = (
                        re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
                    )
                    filename = f"{safe_title}_{i:03d}.png"
                else:
                    filename = f"section_{i:03d}.png"

                output_path = self.output_dir / filename

                # Convert to HTML and render
                html = self.render_to_html(content)
                png_path = asyncio.run(
                    self._render_html_to_png_async(html, output_path)
                )
                png_paths.append(png_path)

            return png_paths
        else:
            # Render entire document as one PNG
            html = self.render_to_html(markdown_content)
            output_path = self.output_dir / f"{markdown_path.stem}.png"
            png_path = asyncio.run(self._render_html_to_png_async(html, output_path))
            return [png_path]

    def render_to_html(self, markdown_content: str) -> str:
        """Convert markdown content to styled HTML suitable for rendering.

        Uses the `markdown` library with extensions:
        - fenced_code (for code blocks)
        - codehilite (for syntax highlighting)
        - tables
        - toc (table of contents)

        Wraps in a full HTML document with CSS styling that:
        - Uses a monospace font for code blocks (preserving ASCII art alignment)
        - Has proper spacing for headings, lists, tables
        - Supports both light and dark themes
        - Includes syntax highlighting CSS

        Args:
            markdown_content: Raw markdown content

        Returns:
            Complete HTML document as string
        """
        try:
            import markdown as md
            from pygments.formatters import HtmlFormatter
        except ImportError as e:
            raise ImportError(
                "Rendering dependencies not installed. "
                "Install with: pip install ggdes[render] && playwright install chromium"
            ) from e

        # Convert markdown to HTML
        md_extensions = [
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
        ]

        body_html = md.markdown(markdown_content, extensions=md_extensions)

        # Get Pygments CSS for syntax highlighting
        try:
            pygments_css = HtmlFormatter().get_style_defs(".highlight")
        except Exception:
            pygments_css = ""

        # Define theme colors
        if self.theme == "dark":
            bg_color = "#1e1e1e"
            text_color = "#e0e0e0"
            heading_color = "#ffffff"
            code_bg = "#2d2d2d"
            border_color = "#444444"
            link_color = "#66b3ff"
        else:
            bg_color = "#ffffff"
            text_color = "#333333"
            heading_color = "#1a1a1a"
            code_bg = "#f5f5f5"
            border_color = "#e0e0e0"
            link_color = "#0066cc"

        # Build complete HTML document
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width={self.width}, initial-scale=1.0">
    <title>Markdown Render</title>
    <style>
        /* Base styles */
        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: {text_color};
            background-color: {bg_color};
            max-width: {self.width}px;
            margin: 0 auto;
            padding: 40px;
        }}

        /* Headings */
        h1, h2, h3, h4, h5, h6 {{
            color: {heading_color};
            margin-top: 24px;
            margin-bottom: 16px;
            font-weight: 600;
            line-height: 1.25;
        }}

        h1 {{
            font-size: 2em;
            border-bottom: 2px solid {border_color};
            padding-bottom: 0.3em;
        }}

        h2 {{
            font-size: 1.5em;
            border-bottom: 1px solid {border_color};
            padding-bottom: 0.3em;
        }}

        h3 {{
            font-size: 1.25em;
        }}

        /* Paragraphs and lists */
        p {{
            margin-top: 0;
            margin-bottom: 16px;
        }}

        ul, ol {{
            margin-top: 0;
            margin-bottom: 16px;
            padding-left: 2em;
        }}

        li {{
            margin-bottom: 4px;
        }}

        /* Code blocks - CRITICAL for ASCII art alignment */
        pre {{
            background-color: {code_bg};
            border: 1px solid {border_color};
            border-radius: 6px;
            padding: 16px;
            overflow-x: auto;
            margin-bottom: 16px;
        }}

        pre code {{
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
            line-height: 1.4;
            white-space: pre;
            word-wrap: normal;
            background: transparent;
            padding: 0;
            border: none;
        }}

        /* Inline code */
        code {{
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            background-color: {code_bg};
            padding: 2px 6px;
            border-radius: 3px;
        }}

        /* Tables */
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 16px;
        }}

        th, td {{
            border: 1px solid {border_color};
            padding: 8px 12px;
            text-align: left;
        }}

        th {{
            background-color: {code_bg};
            font-weight: 600;
        }}

        /* Links */
        a {{
            color: {link_color};
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}

        /* Blockquotes */
        blockquote {{
            border-left: 4px solid {border_color};
            margin: 0 0 16px 0;
            padding-left: 16px;
            color: {text_color};
            opacity: 0.8;
        }}

        /* Horizontal rule */
        hr {{
            border: none;
            border-top: 2px solid {border_color};
            margin: 24px 0;
        }}

        /* Syntax highlighting */
        {pygments_css}

        /* Highlight class adjustments */
        .highlight {{
            background-color: {code_bg};
            border-radius: 6px;
            margin-bottom: 16px;
        }}

        .highlight pre {{
            margin: 0;
            border: none;
        }}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""

        return html

    def _split_by_sections(self, markdown_content: str) -> list[tuple[str, str]]:
        """Split markdown by ## headings.

        Returns list of (title, content) tuples.
        The first item may have title="" for content before the first ## heading.
        """
        lines = markdown_content.split("\n")
        sections: list[tuple[str, str]] = []
        current_title = ""
        current_lines: list[str] = []

        for line in lines:
            # Check for level 2 heading (## )
            if line.startswith("## ") and not line.startswith("### "):
                # Save previous section if it has content
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines).strip()))

                # Start new section
                current_title = line[3:].strip()  # Remove "## " prefix
                current_lines = [line]
            else:
                current_lines.append(line)

        # Don't forget the last section
        if current_lines:
            sections.append((current_title, "\n".join(current_lines).strip()))

        # If no sections found, return entire content as one section
        if not sections:
            sections = [("", markdown_content)]

        return sections

    async def _render_html_to_png_async(self, html: str, output_path: Path) -> Path:
        """Render HTML string to PNG using Playwright (async version).

        Uses headless Chromium with:
        - Full page screenshot (no clipping)
        - Proper viewport width
        - Wait for fonts to load
        - Scale factor of 2 for high-DPI output

        Args:
            html: HTML content to render
            output_path: Path to save the PNG file

        Returns:
            Path to the generated PNG file
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ImportError(
                "Playwright not installed. "
                "Install with: pip install ggdes[render] && playwright install chromium"
            ) from e

        # Create temp HTML file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as temp_file:
            temp_file.write(html)
            temp_path = Path(temp_file.name)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(
                    viewport={"width": self.width, "height": 800},
                    device_scale_factor=2,  # High-DPI output
                )
                page = await context.new_page()

                # Load the HTML file
                await page.goto(f"file://{temp_path}")

                # Wait for fonts to load and page to be stable
                await page.wait_for_load_state("networkidle")

                # Take full page screenshot
                await page.screenshot(
                    path=str(output_path),
                    full_page=True,
                )

                await browser.close()

            return output_path

        finally:
            # Cleanup temp file
            if temp_path.exists():
                temp_path.unlink()

    def _render_html_to_png(self, html: str, output_path: Path) -> Path:
        """Render HTML string to PNG using Playwright (sync wrapper).

        Uses headless Chromium with:
        - Full page screenshot (no clipping)
        - Proper viewport width
        - Wait for fonts to load
        - Scale factor of 2 for high-DPI output

        Args:
            html: HTML content to render
            output_path: Path to save the PNG file

        Returns:
            Path to the generated PNG file
        """
        return asyncio.run(self._render_html_to_png_async(html, output_path))
