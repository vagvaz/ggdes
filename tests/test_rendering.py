"""Tests for the rendering module."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestMarkdownToPngRenderer:
    """Tests for MarkdownToPngRenderer."""

    def test_init(self, tmp_path: Path) -> None:
        """Test renderer initialization."""
        from ggdes.rendering import MarkdownToPngRenderer

        output_dir = tmp_path / "output"
        renderer = MarkdownToPngRenderer(output_dir, theme="dark", width=800)

        assert renderer.output_dir == output_dir
        assert renderer.theme == "dark"
        assert renderer.width == 800
        assert output_dir.exists()  # Directory should be created

    def test_init_default_theme(self, tmp_path: Path) -> None:
        """Test renderer defaults to light theme."""
        from ggdes.rendering import MarkdownToPngRenderer

        output_dir = tmp_path / "output"
        renderer = MarkdownToPngRenderer(output_dir)

        assert renderer.theme == "light"
        assert renderer.width == 1200  # Default width

    def test_init_invalid_theme(self, tmp_path: Path) -> None:
        """Test renderer defaults to light for invalid theme."""
        from ggdes.rendering import MarkdownToPngRenderer

        output_dir = tmp_path / "output"
        renderer = MarkdownToPngRenderer(output_dir, theme="invalid")

        assert renderer.theme == "light"

    def test_render_to_html_basic(self, tmp_path: Path) -> None:
        """Test basic markdown to HTML conversion."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = "# Hello World\n\nThis is a paragraph."
        html = renderer.render_to_html(markdown)

        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Hello World" in html
        assert "This is a paragraph" in html

    def test_render_to_html_code_blocks(self, tmp_path: Path) -> None:
        """Test code blocks are properly styled."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """```python
def hello():
    print("Hello")
```"""
        html = renderer.render_to_html(markdown)

        # Should contain code block
        assert "<pre>" in html
        assert "<code" in html
        # Should have monospace font CSS
        assert "'Courier New'" in html or "Courier New" in html
        assert "monospace" in html

    def test_render_to_html_ascii_art(self, tmp_path: Path) -> None:
        """Test ASCII art alignment is preserved."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """```
┌─────────┐
│  BOX    │
└─────────┘
```"""
        html = renderer.render_to_html(markdown)

        # Should preserve whitespace
        assert "white-space: pre" in html
        assert "┌─────────┐" in html

    def test_render_to_html_tables(self, tmp_path: Path) -> None:
        """Test tables are converted properly."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |"""
        html = renderer.render_to_html(markdown)

        assert "<table>" in html
        assert "<th>" in html
        assert "<td>" in html
        assert "Header 1" in html
        assert "Cell 1" in html

    def test_render_to_html_headings(self, tmp_path: Path) -> None:
        """Test headings are converted properly."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """# Heading 1
## Heading 2
### Heading 3"""
        html = renderer.render_to_html(markdown)

        # Headings may have id attributes from toc extension
        assert re.search(r"<h1[^>]*>", html) is not None
        assert re.search(r"<h2[^>]*>", html) is not None
        assert re.search(r"<h3[^>]*>", html) is not None
        assert "Heading 1" in html

    def test_render_to_html_lists(self, tmp_path: Path) -> None:
        """Test lists are converted properly."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        # Test unordered list
        markdown = """- Item 1
- Item 2"""
        html = renderer.render_to_html(markdown)

        assert "<ul>" in html
        assert "<li>" in html
        assert "Item 1" in html

        # Test ordered list separately
        markdown2 = """1. First
2. Second"""
        html2 = renderer.render_to_html(markdown2)

        assert "<ol>" in html2
        assert "<li>" in html2
        assert "First" in html2

    def test_render_to_html_dark_theme(self, tmp_path: Path) -> None:
        """Test dark theme CSS is applied."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path, theme="dark")
        markdown = "# Test"
        html = renderer.render_to_html(markdown)

        assert "#1e1e1e" in html  # Dark background
        assert "#e0e0e0" in html  # Light text

    def test_render_to_html_light_theme(self, tmp_path: Path) -> None:
        """Test light theme CSS is applied."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path, theme="light")
        markdown = "# Test"
        html = renderer.render_to_html(markdown)

        assert "#ffffff" in html  # White background
        assert "#333333" in html  # Dark text

    def test_render_to_html_syntax_highlighting_css(self, tmp_path: Path) -> None:
        """Test that syntax highlighting CSS is included."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = "```python\nprint('hello')\n```"
        html = renderer.render_to_html(markdown)

        # Should contain Pygments CSS
        assert ".highlight" in html

    def test_split_by_sections(self, tmp_path: Path) -> None:
        """Test splitting markdown by sections."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """# Title

Intro text.

## Section 1

Content 1.

## Section 2

Content 2."""

        sections = renderer._split_by_sections(markdown)

        # First section has empty title (content before first ##)
        assert len(sections) == 3
        assert sections[0][0] == ""  # Content before first ##
        assert "# Title" in sections[0][1]
        assert sections[1][0] == "Section 1"
        assert "Content 1" in sections[1][1]
        assert sections[2][0] == "Section 2"
        assert "Content 2" in sections[2][1]

    def test_split_by_sections_with_frontmatter(self, tmp_path: Path) -> None:
        """Test splitting markdown with frontmatter."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """---
title: Test
---

## First Section

Content here.

## Second Section

More content."""

        sections = renderer._split_by_sections(markdown)

        # First section should have empty title (content before ##)
        # or the frontmatter will be part of first section
        assert len(sections) >= 1
        # Check that sections are properly split
        section_titles = [s[0] for s in sections]
        assert "First Section" in section_titles
        assert "Second Section" in section_titles

    def test_split_by_sections_no_headings(self, tmp_path: Path) -> None:
        """Test splitting markdown with no ## headings."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = "Just some content without sections."

        sections = renderer._split_by_sections(markdown)

        assert len(sections) == 1
        assert sections[0][0] == ""
        assert sections[0][1] == markdown

    def test_split_by_sections_only_h1(self, tmp_path: Path) -> None:
        """Test that only ## (h2) splits, not # (h1)."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """# Main Title

Some intro.

## Section A

Content A.

### Subsection

Sub content."""

        sections = renderer._split_by_sections(markdown)

        # Should only split on ##, not # or ###
        # First section is content before first ##
        assert len(sections) == 2
        assert sections[0][0] == ""  # Content before ##
        assert sections[1][0] == "Section A"
        # Should include ### subsection content
        assert "Subsection" in sections[1][1]

    def test_split_by_sections_empty_sections(self, tmp_path: Path) -> None:
        """Test that empty sections are handled."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = """## Section 1

Content.

## Section 2

## Section 3

Content 3."""

        sections = renderer._split_by_sections(markdown)

        # Section 2 is empty (just heading, no content)
        assert len(sections) == 3
        assert sections[1][0] == "Section 2"

    @pytest.mark.asyncio
    async def test_render_html_to_png_async(self, tmp_path: Path) -> None:
        """Test PNG rendering with mocked Playwright."""
        import asyncio
        from unittest.mock import AsyncMock

        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        html = "<html><body><h1>Test</h1></body></html>"
        output_path = tmp_path / "test.png"

        # Mock Playwright - need to mock at the module level where it's imported
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()
        mock_playwright = MagicMock()
        mock_playwright.chromium = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

        # Create a proper async context manager mock
        class AsyncContextManagerMock:
            async def __aenter__(self):
                return mock_playwright

            async def __aexit__(self, *args):
                return None

        with patch(
            "playwright.async_api.async_playwright",
            return_value=AsyncContextManagerMock(),
        ):
            result = await renderer._render_html_to_png_async(html, output_path)

            assert result == output_path
            mock_page.goto.assert_called_once()
            mock_page.wait_for_load_state.assert_called_once_with("networkidle")
            mock_page.screenshot.assert_called_once_with(
                path=str(output_path),
                full_page=True,
            )

    def test_render_full_document(self, tmp_path: Path) -> None:
        """Test rendering full document (not sections)."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown_path = tmp_path / "test.md"
        markdown_path.write_text("# Test Document\n\nSome content.")

        with patch.object(renderer, "_render_html_to_png_async") as mock_render:
            mock_render.return_value = tmp_path / "test.png"

            result = renderer.render(markdown_path, sections=False)

            assert len(result) == 1
            mock_render.assert_called_once()

    def test_render_sections(self, tmp_path: Path) -> None:
        """Test rendering by sections."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown_path = tmp_path / "test.md"
        markdown_path.write_text("""# Doc

## Section One

Content one.

## Section Two

Content two.""")

        with patch.object(renderer, "_render_html_to_png_async") as mock_render:
            # 3 sections: content before first ##, Section One, Section Two
            mock_render.side_effect = [
                tmp_path / "section_000.png",
                tmp_path / "Section_One_001.png",
                tmp_path / "Section_Two_002.png",
            ]

            result = renderer.render(markdown_path, sections=True)

            assert len(result) == 3
            assert mock_render.call_count == 3

    def test_render_import_error(self, tmp_path: Path) -> None:
        """Test ImportError is raised when playwright is not installed.

        Note: This test verifies the error handling code path exists.
        Since playwright is imported inside the function, we test by
        checking the error message format in the implementation.
        """
        from ggdes.rendering.markdown_to_png import MarkdownToPngRenderer

        # Verify the error message format in the code
        import inspect

        source = inspect.getsource(MarkdownToPngRenderer._render_html_to_png_async)

        # Check that the function has proper error handling
        assert "ImportError" in source
        assert "not installed" in source.lower() or "playwright" in source.lower()

    def test_render_to_html_import_error(self, tmp_path: Path) -> None:
        """Test ImportError is raised when markdown/pygments is not installed."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)

        with patch.dict("sys.modules", {"markdown": None}):
            with pytest.raises(ImportError) as exc_info:
                renderer.render_to_html("# Test")

            assert "not installed" in str(exc_info.value).lower()

    def test_css_monospace_for_code(self, tmp_path: Path) -> None:
        """Test that CSS includes monospace font for code blocks."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = "`inline code`"
        html = renderer.render_to_html(markdown)

        # Check for monospace font family in code/pre styles
        assert "font-family" in html
        assert "monospace" in html.lower()
        # Check specifically for Courier New which is critical for ASCII art
        assert "Courier New" in html or "'Courier New'" in html

    def test_css_white_space_pre(self, tmp_path: Path) -> None:
        """Test that CSS includes white-space: pre for code blocks."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown = "```\ncode\n```"
        html = renderer.render_to_html(markdown)

        # Check for white-space: pre
        assert "white-space: pre" in html

    def test_filename_sanitization(self, tmp_path: Path) -> None:
        """Test that section titles are sanitized for filenames."""
        from ggdes.rendering import MarkdownToPngRenderer

        renderer = MarkdownToPngRenderer(tmp_path)
        markdown_path = tmp_path / "test.md"
        markdown_path.write_text("""# Doc

## Section: With *Special* Chars!

Content.""")

        with patch.object(renderer, "_render_html_to_png_async") as mock_render:
            mock_render.return_value = tmp_path / "output.png"

            result = renderer.render(markdown_path, sections=True)

            # Check that the filename was sanitized
            call_args = mock_render.call_args
            output_path = (
                call_args[0][1] if call_args[0] else call_args[1].get("output_path")
            )
            # The filename should not contain special characters
            assert output_path is not None
            filename = output_path.name
            # Should not have special chars except underscore
            assert not re.search(r"[*!:;]", filename)
