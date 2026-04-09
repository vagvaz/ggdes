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

    def test_parse_files(self, parser, temp_dir):
        """Test parsing specific list of files."""
        # Create multiple files
        file1 = temp_dir / "module1.py"
        file1.write_text("def func1(): pass")
        file2 = temp_dir / "module2.py"
        file2.write_text("def func2(): pass")
        file3 = temp_dir / "module3.py"
        file3.write_text("def func3(): pass")

        # Parse only specific files
        results = parser.parse_files(
            [file1, file2], relative_to=temp_dir, verbose=False
        )

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_parse_incremental_changed_only(self, parser, temp_dir):
        """Test incremental parsing with only changed files."""
        # Create files
        changed_file = temp_dir / "changed_module.py"
        changed_file.write_text("def changed_func(): pass")
        unchanged_file = temp_dir / "unchanged_module.py"
        unchanged_file.write_text("def unchanged_func(): pass")

        # Parse only the changed file
        results = parser.parse_incremental(
            directory=temp_dir,
            changed_files=["changed_module.py"],
            relative_to=temp_dir,
            include_referenced=False,
            max_referenced_depth=0,
            verbose=False,
        )

        assert len(results) == 1
        assert results[0].file_path == "changed_module.py"
        assert results[0].success is True

    def test_find_referenced_files_python(self, parser, temp_dir):
        """Test finding files that reference seed files in Python."""
        # Create seed file
        seed_file = temp_dir / "seed_module.py"
        seed_file.write_text("def seed_func(): pass")

        # Create referencing file
        referencing_file = temp_dir / "referencing_module.py"
        referencing_file.write_text(
            "from seed_module import seed_func\n\ndef main():\n    seed_func()"
        )

        # Create non-referencing file
        unrelated_file = temp_dir / "unrelated_module.py"
        unrelated_file.write_text("def unrelated_func(): pass")

        # Find references
        referenced = parser.find_referenced_files(
            seed_files=[seed_file],
            directory=temp_dir,
            max_depth=1,
            verbose=False,
        )

        assert referencing_file in referenced
        assert unrelated_file not in referenced
        assert seed_file not in referenced

    def test_parse_incremental_with_references(self, parser, temp_dir):
        """Test incremental parsing including referenced files."""
        # Create seed file
        seed_file = temp_dir / "seed_module.py"
        seed_file.write_text("def seed_func(): pass")

        # Create referencing file
        referencing_file = temp_dir / "referencing_module.py"
        referencing_file.write_text(
            "from seed_module import seed_func\n\ndef main():\n    seed_func()"
        )

        # Parse with references
        results = parser.parse_incremental(
            directory=temp_dir,
            changed_files=["seed_module.py"],
            relative_to=temp_dir,
            include_referenced=True,
            max_referenced_depth=1,
            verbose=False,
        )

        file_paths = [r.file_path for r in results]
        assert "seed_module.py" in file_paths
        assert "referencing_module.py" in file_paths
        assert len(results) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
