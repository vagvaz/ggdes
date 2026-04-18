"""Tests for refactored components."""

import pytest
from unittest.mock import MagicMock, patch

from ggdes.agents.skill_utils import SystemPromptBuilder
from ggdes.llm.factory import _strip_markdown_code_blocks


# ─── SystemPromptBuilder Tests ───────────────────────────────────────────────


class TestSystemPromptBuilder:
    """Tests for the SystemPromptBuilder class."""

    def test_builder_empty(self) -> None:
        """build() with no content returns empty string."""
        builder = SystemPromptBuilder()
        assert builder.build() == ""

    def test_builder_add_skill(self) -> None:
        """add_skill() appends skill content with === markers."""
        builder = SystemPromptBuilder()
        builder.add_skill("TEST SKILL", "skill content here")
        result = builder.build()
        assert "=== TEST SKILL ===" in result
        assert "skill content here" in result
        assert "=== END TEST SKILL ===" in result

    def test_builder_set_base_prompt(self) -> None:
        """set_base_prompt() adds base prompt."""
        builder = SystemPromptBuilder()
        builder.set_base_prompt("This is the base prompt.")
        result = builder.build()
        assert "This is the base prompt." in result

    def test_builder_set_user_guidance(self) -> None:
        """set_user_guidance() adds the VERY IMPORTANT box."""
        builder = SystemPromptBuilder()
        builder.set_user_guidance("Focus on performance.")
        result = builder.build()
        assert "VERY IMPORTANT" in result
        assert "USER REQUIREMENTS (MUST FOLLOW)" in result
        assert "Focus on performance." in result
        assert "YOU MUST ADHERE TO ALL USER REQUIREMENTS ABOVE" in result

    def test_builder_full_chain(self) -> None:
        """Chain all methods and verify order (skills → base → user guidance)."""
        builder = (
            SystemPromptBuilder()
            .add_skill("PYTHON EXPERT", "Python expertise content")
            .add_skill("DOC EXPERT", "Doc expertise content")
            .set_base_prompt("You are a helpful assistant.")
            .set_user_guidance("Focus on API changes.")
        )
        result = builder.build()

        # Skills come first
        python_pos = result.index("=== PYTHON EXPERT ===")
        doc_pos = result.index("=== DOC EXPERT ===")
        base_pos = result.index("You are a helpful assistant.")
        guidance_pos = result.index("VERY IMPORTANT")

        assert python_pos < doc_pos < base_pos < guidance_pos

    def test_builder_multiple_skills(self) -> None:
        """Multiple add_skill calls accumulate."""
        builder = SystemPromptBuilder()
        builder.add_skill("SKILL 1", "content 1")
        builder.add_skill("SKILL 2", "content 2")
        builder.add_skill("SKILL 3", "content 3")
        result = builder.build()

        assert "=== SKILL 1 ===" in result
        assert "=== SKILL 2 ===" in result
        assert "=== SKILL 3 ===" in result
        assert "content 1" in result
        assert "content 2" in result
        assert "content 3" in result

    def test_builder_returns_self_for_chaining(self) -> None:
        """All methods return self for fluent API."""
        builder = SystemPromptBuilder()
        assert builder.add_skill("X", "y") is builder
        assert builder.set_base_prompt("z") is builder
        assert builder.set_user_guidance("w") is builder


# ─── _strip_markdown_code_blocks Tests ───────────────────────────────────────


class TestStripMarkdownCodeBlocks:
    """Tests for the _strip_markdown_code_blocks helper."""

    def test_plain_text(self) -> None:
        """Plain text returns unchanged."""
        assert _strip_markdown_code_blocks("hello world") == "hello world"

    def test_code_block_single(self) -> None:
        """Strips single code block markers."""
        text = "```\nsome code\n```"
        assert _strip_markdown_code_blocks(text) == "some code"

    def test_code_block_with_language(self) -> None:
        """Strips code block with language specifier."""
        text = "```python\nprint('hello')\n```"
        assert _strip_markdown_code_blocks(text) == "print('hello')"

    def test_no_stripping_needed(self) -> None:
        """Text without code blocks unchanged."""
        text = "This is just plain text with no code blocks."
        assert _strip_markdown_code_blocks(text) == text

    def test_code_block_no_trailing_fence(self) -> None:
        """Handles code block without trailing fence."""
        text = "```\nsome code without closing"
        # Should not strip since it doesn't start with ``` followed by newline
        # Actually it does start with ```, finds newline, but no closing ```
        result = _strip_markdown_code_blocks(text)
        assert "some code without closing" in result

    def test_code_block_with_extra_whitespace(self) -> None:
        """Strips and trims content."""
        text = "```python\n\n  indented code  \n\n```"
        result = _strip_markdown_code_blocks(text)
        assert "indented code" in result

    def test_embedded_code_block_not_stripped(self) -> None:
        """Code blocks not at start are not stripped."""
        text = "Here is some text\n```python\ncode\n```"
        assert _strip_markdown_code_blocks(text) == text

    def test_multiple_code_blocks_strips_first(self) -> None:
        """Only strips the first code block fence."""
        text = "```python\ncode\n```"
        result = _strip_markdown_code_blocks(text)
        assert result == "code"


# ─── resolve_analysis Tests ──────────────────────────────────────────────────


class TestResolveAnalysis:
    """Tests for the resolve_analysis helper in cli.py."""

    def test_resolve_by_id(self) -> None:
        """Finds analysis by ID."""
        from ggdes.cli import resolve_analysis
        import typer

        mock_metadata = MagicMock()
        mock_metadata.name = "My Analysis"
        mock_kb = MagicMock()
        mock_kb.list_analyses.return_value = [
            ("abc123", mock_metadata),
            ("def456", MagicMock(name="Other")),
        ]

        with patch("ggdes.cli.console"):
            result = resolve_analysis(mock_kb, "abc123")
            assert result == ("abc123", mock_metadata)

    def test_resolve_by_name(self) -> None:
        """Finds analysis by name."""
        from ggdes.cli import resolve_analysis

        mock_metadata = MagicMock()
        mock_metadata.name = "My Analysis"
        mock_kb = MagicMock()
        mock_kb.list_analyses.return_value = [
            ("abc123", mock_metadata),
        ]

        with patch("ggdes.cli.console"):
            result = resolve_analysis(mock_kb, "My Analysis")
            assert result == ("abc123", mock_metadata)

    def test_resolve_not_found(self) -> None:
        """Raises typer.Exit(1) for unknown analysis."""
        from ggdes.cli import resolve_analysis
        import typer

        mock_kb = MagicMock()
        mock_kb.list_analyses.return_value = [
            ("abc123", MagicMock(name="Existing")),
        ]

        with patch("ggdes.cli.console"):
            with pytest.raises(typer.Exit):
                resolve_analysis(mock_kb, "nonexistent")

    def test_resolve_empty_list(self) -> None:
        """Handles empty analysis list."""
        from ggdes.cli import resolve_analysis
        import typer

        mock_kb = MagicMock()
        mock_kb.list_analyses.return_value = []

        with patch("ggdes.cli.console"):
            with pytest.raises(typer.Exit):
                resolve_analysis(mock_kb, "anything")

    def test_resolve_name_match_priority(self) -> None:
        """Returns first match when both ID and name could match."""
        from ggdes.cli import resolve_analysis

        mock_meta1 = MagicMock()
        mock_meta1.name = "First"
        mock_meta2 = MagicMock()
        mock_meta2.name = "Second"
        mock_kb = MagicMock()
        mock_kb.list_analyses.return_value = [
            ("id1", mock_meta1),
            ("id2", mock_meta2),
        ]

        with patch("ggdes.cli.console"):
            result = resolve_analysis(mock_kb, "Second")
            assert result == ("id2", mock_meta2)
