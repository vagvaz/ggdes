"""Tests for AST parser."""

import tempfile
from pathlib import Path

import pytest

from ggdes.parsing.ast_parser import ASTParser


class TestASTParser:
    """Test AST parser functionality."""

    @pytest.fixture
    def parser(self):
        """Create an AST parser instance."""
        return ASTParser()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        import shutil

        shutil.rmtree(temp_path, ignore_errors=True)

    def test_detect_language_python(self, parser):
        """Test detecting Python files."""
        assert parser.detect_language(Path("test.py")) == "python"
        assert parser.detect_language(Path("test.PY")) == "python"
        assert parser.detect_language(Path("/path/to/file.py")) == "python"

    def test_detect_language_cpp(self, parser):
        """Test detecting C++ files."""
        assert parser.detect_language(Path("test.cpp")) == "cpp"
        assert parser.detect_language(Path("test.cc")) == "cpp"
        assert parser.detect_language(Path("test.cxx")) == "cpp"
        assert parser.detect_language(Path("test.hpp")) == "cpp"
        assert parser.detect_language(Path("test.h")) == "cpp"
        assert parser.detect_language(Path("test.CPP")) == "cpp"

    def test_detect_language_unknown(self, parser):
        """Test detecting unsupported files."""
        assert parser.detect_language(Path("test.js")) is None
        assert parser.detect_language(Path("test.java")) is None
        assert parser.detect_language(Path("test.txt")) is None
        assert parser.detect_language(Path("test")) is None

    def test_parse_python_file(self, parser, temp_dir):
        """Test parsing a Python file."""
        test_file = temp_dir / "test_module.py"
        test_file.write_text('''
"""Test module docstring."""

def hello_world(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

class TestClass:
    """A test class."""
    
    def __init__(self, value: int):
        self.value = value
    
    def get_value(self) -> int:
        """Get the value."""
        return self.value
''')

        result = parser.parse_file(test_file, relative_to=temp_dir)

        assert result.success is True
        assert result.language == "python"
        assert len(result.elements) > 0

        # Check for functions
        func_names = [
            e.name for e in result.elements if e.element_type.value == "function"
        ]
        assert "hello_world" in func_names

        # Check for classes
        class_names = [
            e.name for e in result.elements if e.element_type.value == "class"
        ]
        assert "TestClass" in class_names

        # Check for methods
        method_names = [
            e.name for e in result.elements if e.element_type.value == "method"
        ]
        assert "__init__" in method_names
        assert "get_value" in method_names

    def test_parse_directory(self, parser, temp_dir):
        """Test parsing a directory of files."""
        # Create Python files
        (temp_dir / "module1.py").write_text("def func1(): pass")
        (temp_dir / "module2.py").write_text("def func2(): pass")
        (temp_dir / "submodule").mkdir()
        (temp_dir / "submodule" / "module3.py").write_text("def func3(): pass")

        # Create non-Python files (should be ignored)
        (temp_dir / "readme.txt").write_text("Hello")
        (temp_dir / "script.js").write_text("function test() {}")

        results = parser.parse_directory(temp_dir, relative_to=temp_dir, verbose=False)

        # Should find 3 Python files
        assert len(results) == 3

        # All should be successful
        for result in results:
            assert result.success is True
            assert result.language == "python"

    def test_parse_empty_directory(self, parser, temp_dir):
        """Test parsing empty directory."""
        results = parser.parse_directory(temp_dir, relative_to=temp_dir)
        assert len(results) == 0

    def test_parse_nonexistent_directory(self, parser):
        """Test parsing non-existent directory raises error."""
        with pytest.raises(FileNotFoundError):
            parser.parse_directory(Path("/nonexistent/path"))

    def test_parse_unsupported_file(self, parser, temp_dir):
        """Test parsing unsupported file type."""
        test_file = temp_dir / "script.js"
        test_file.write_text("function test() {}")

        result = parser.parse_file(test_file)

        assert result.success is False
        assert result.language == "unknown"
        assert "Unsupported file type" in result.error_message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
