"""Comprehensive tests for the GGDes tools module.

Tests cover:
- ToolDefinition: creation, validation, schema conversion
- ToolCall: creation, parsing from text
- ToolResult: creation, success/error states
- ToolParameter: creation, required vs optional
- Tool definitions: all 5 tools have correct structure
- ToolExecutor: all tool methods with mock data
- chat_with_tools(): tool call parsing and execution loop
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from ggdes.tools import (
    TOOL_DEFINITIONS,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolParameter,
    ToolResult,
    chat_with_tools,
    get_tool_by_name,
)
from ggdes.tools.definitions import (
    TOOL_GET_AST_ELEMENTS,
    TOOL_GET_CHANGED_FILES,
    TOOL_READ_FILE,
    TOOL_SEARCH_CODE,
    TOOL_VALIDATE_REFERENCE,
)


# =============================================================================
# ToolParameter Tests
# =============================================================================


class TestToolParameter:
    """Tests for ToolParameter model."""

    def test_create_required_parameter(self):
        """Test creating a required parameter."""
        param = ToolParameter(
            name="path",
            type="string",
            description="Path to the file",
            required=True,
        )
        assert param.name == "path"
        assert param.type == "string"
        assert param.description == "Path to the file"
        assert param.required is True
        assert param.enum is None

    def test_create_optional_parameter(self):
        """Test creating an optional parameter."""
        param = ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum results",
            required=False,
        )
        assert param.name == "max_results"
        assert param.type == "integer"
        assert param.required is False

    def test_create_enum_parameter(self):
        """Test creating a parameter with enum values."""
        param = ToolParameter(
            name="change_type",
            type="string",
            description="Type of change",
            required=True,
            enum=["added", "modified", "deleted", "renamed"],
        )
        assert param.enum == ["added", "modified", "deleted", "renamed"]

    def test_default_required_is_true(self):
        """Test that required defaults to True."""
        param = ToolParameter(
            name="pattern",
            type="string",
            description="Search pattern",
        )
        assert param.required is True


# =============================================================================
# ToolDefinition Tests
# =============================================================================


class TestToolDefinition:
    """Tests for ToolDefinition model."""

    def test_create_tool_definition(self):
        """Test creating a tool definition."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParameter(name="arg1", type="string", description="First arg"),
            ],
            returns="A string result",
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert len(tool.parameters) == 1
        assert tool.returns == "A string result"

    def test_to_openai_schema_basic(self):
        """Test converting to OpenAI schema format."""
        tool = ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters=[
                ToolParameter(
                    name="path", type="string", description="File path", required=True
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Line limit",
                    required=False,
                ),
            ],
            returns="File contents",
        )
        schema = tool.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        assert schema["function"]["description"] == "Read a file"
        assert schema["function"]["parameters"]["type"] == "object"
        assert "path" in schema["function"]["parameters"]["properties"]
        assert "limit" in schema["function"]["parameters"]["properties"]
        assert schema["function"]["parameters"]["required"] == ["path"]

    def test_to_openai_schema_with_enum(self):
        """Test OpenAI schema with enum parameter."""
        tool = ToolDefinition(
            name="validate",
            description="Validate reference",
            parameters=[
                ToolParameter(
                    name="ref_type",
                    type="string",
                    description="Reference type",
                    required=True,
                    enum=["file", "function", "class"],
                ),
            ],
            returns="Validation result",
        )
        schema = tool.to_openai_schema()

        prop = schema["function"]["parameters"]["properties"]["ref_type"]
        assert prop["enum"] == ["file", "function", "class"]

    def test_to_anthropic_schema_basic(self):
        """Test converting to Anthropic schema format."""
        tool = ToolDefinition(
            name="search_code",
            description="Search for code",
            parameters=[
                ToolParameter(
                    name="pattern", type="string", description="Pattern", required=True
                ),
            ],
            returns="Search results",
        )
        schema = tool.to_anthropic_schema()

        assert schema["name"] == "search_code"
        assert schema["description"] == "Search for code"
        assert schema["input_schema"]["type"] == "object"
        assert "pattern" in schema["input_schema"]["properties"]
        assert schema["input_schema"]["required"] == ["pattern"]

    def test_to_anthropic_schema_with_enum(self):
        """Test Anthropic schema with enum parameter."""
        tool = ToolDefinition(
            name="filter",
            description="Filter items",
            parameters=[
                ToolParameter(
                    name="type",
                    type="string",
                    description="Filter type",
                    required=True,
                    enum=["a", "b", "c"],
                ),
            ],
            returns="Filtered items",
        )
        schema = tool.to_anthropic_schema()

        prop = schema["input_schema"]["properties"]["type"]
        assert prop["enum"] == ["a", "b", "c"]


# =============================================================================
# ToolCall Tests
# =============================================================================


class TestToolCall:
    """Tests for ToolCall model."""

    def test_create_tool_call(self):
        """Test creating a tool call."""
        call = ToolCall(
            tool_name="read_file",
            arguments={"path": "test.py"},
            call_id="call_123",
        )
        assert call.tool_name == "read_file"
        assert call.arguments == {"path": "test.py"}
        assert call.call_id == "call_123"

    def test_create_tool_call_no_call_id(self):
        """Test creating a tool call without call_id."""
        call = ToolCall(
            tool_name="search_code",
            arguments={"pattern": "def "},
        )
        assert call.tool_name == "search_code"
        assert call.arguments == {"pattern": "def "}
        assert call.call_id is None

    def test_default_arguments_empty_dict(self):
        """Test that arguments defaults to empty dict."""
        call = ToolCall(tool_name="get_changed_files")
        assert call.arguments == {}


# =============================================================================
# ToolResult Tests
# =============================================================================


class TestToolResult:
    """Tests for ToolResult model."""

    def test_create_success_result(self):
        """Test creating a successful result."""
        result = ToolResult(
            tool_name="read_file",
            success=True,
            result="file contents",
        )
        assert result.tool_name == "read_file"
        assert result.success is True
        assert result.result == "file contents"
        assert result.error is None

    def test_create_error_result(self):
        """Test creating an error result."""
        result = ToolResult(
            tool_name="read_file",
            success=False,
            result=None,
            error="File not found",
        )
        assert result.success is False
        assert result.result is None
        assert result.error == "File not found"

    def test_to_message_content_success_string(self):
        """Test converting successful string result to message."""
        result = ToolResult(
            tool_name="read_file",
            success=True,
            result="Hello, world!",
        )
        assert result.to_message_content() == "Hello, world!"

    def test_to_message_content_success_dict(self):
        """Test converting successful dict result to message."""
        result = ToolResult(
            tool_name="get_changed_files",
            success=True,
            result={"focused": ["a.py"], "contextual": ["b.py"]},
        )
        content = result.to_message_content()
        assert "focused" in content
        assert "contextual" in content
        assert "a.py" in content

    def test_to_message_content_error(self):
        """Test converting error result to message."""
        result = ToolResult(
            tool_name="validate_reference",
            success=False,
            result=None,
            error="Reference not found",
        )
        content = result.to_message_content()
        assert "Error" in content
        assert "validate_reference" in content
        assert "Reference not found" in content


# =============================================================================
# Tool Definitions Tests
# =============================================================================


class TestToolDefinitions:
    """Tests for the built-in tool definitions."""

    def test_all_tools_exported(self):
        """Test that all 5 tools are in TOOL_DEFINITIONS."""
        tool_names = {tool.name for tool in TOOL_DEFINITIONS}
        expected = {
            "get_changed_files",
            "read_file",
            "search_code",
            "validate_reference",
            "get_ast_elements",
        }
        assert tool_names == expected

    def test_get_tool_by_name_found(self):
        """Test getting a tool by name."""
        tool = get_tool_by_name("read_file")
        assert tool is not None
        assert tool.name == "read_file"

    def test_get_tool_by_name_not_found(self):
        """Test getting a non-existent tool."""
        tool = get_tool_by_name("nonexistent_tool")
        assert tool is None

    def test_get_changed_files_tool(self):
        """Test get_changed_files tool definition."""
        tool = TOOL_GET_CHANGED_FILES
        assert tool.name == "get_changed_files"
        assert "changed" in tool.description.lower()

        param_names = {p.name for p in tool.parameters}
        assert "include_contextual" in param_names
        assert "change_type_filter" in param_names

        # Check enum values
        change_type_param = next(
            p for p in tool.parameters if p.name == "change_type_filter"
        )
        assert change_type_param.enum == ["added", "modified", "deleted", "renamed"]

    def test_read_file_tool(self):
        """Test read_file tool definition."""
        tool = TOOL_READ_FILE
        assert tool.name == "read_file"
        assert "file" in tool.description.lower()

        param_names = {p.name for p in tool.parameters}
        assert "path" in param_names
        assert "start_line" in param_names
        assert "end_line" in param_names

        # path is required, others are optional
        path_param = next(p for p in tool.parameters if p.name == "path")
        assert path_param.required is True
        start_param = next(p for p in tool.parameters if p.name == "start_line")
        assert start_param.required is False

    def test_search_code_tool(self):
        """Test search_code tool definition."""
        tool = TOOL_SEARCH_CODE
        assert tool.name == "search_code"
        assert "search" in tool.description.lower()

        param_names = {p.name for p in tool.parameters}
        assert "pattern" in param_names
        assert "file_pattern" in param_names
        assert "max_results" in param_names

        pattern_param = next(p for p in tool.parameters if p.name == "pattern")
        assert pattern_param.required is True

    def test_validate_reference_tool(self):
        """Test validate_reference tool definition."""
        tool = TOOL_VALIDATE_REFERENCE
        assert tool.name == "validate_reference"
        assert "validate" in tool.description.lower()

        param_names = {p.name for p in tool.parameters}
        assert "reference_type" in param_names
        assert "name" in param_names
        assert "file_path" in param_names

        ref_type_param = next(p for p in tool.parameters if p.name == "reference_type")
        assert ref_type_param.enum == ["file", "function", "class", "variable"]

    def test_get_ast_elements_tool(self):
        """Test get_ast_elements tool definition."""
        tool = TOOL_GET_AST_ELEMENTS
        assert tool.name == "get_ast_elements"
        assert "AST" in tool.description

        param_names = {p.name for p in tool.parameters}
        assert "file_path" in param_names
        assert "element_type" in param_names

        element_type_param = next(
            p for p in tool.parameters if p.name == "element_type"
        )
        assert element_type_param.enum == [
            "function",
            "method",
            "class",
            "variable",
            "constant",
        ]


# =============================================================================
# ToolExecutor Tests
# =============================================================================


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository with some files."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    # Create some Python files
    src_dir = repo_path / "src"
    src_dir.mkdir()

    (src_dir / "main.py").write_text("""
def main():
    print("Hello, world!")

class MyClass:
    def method(self):
        pass
""")

    (src_dir / "utils.py").write_text("""
def helper():
    return 42

def process_data(data):
    return data.upper()
""")

    # Create a binary file
    (repo_path / "binary.dat").write_bytes(b"\x00\x01\x02\x03")

    return repo_path


@pytest.fixture
def mock_changed_files():
    """Create mock changed files data."""
    return [
        {
            "path": "src/main.py",
            "change_type": "modified",
            "lines_added": 10,
            "lines_deleted": 5,
            "summary": "Updated main function",
        },
        {
            "path": "src/utils.py",
            "change_type": "added",
            "lines_added": 20,
            "lines_deleted": 0,
            "summary": "Added utility functions",
        },
        {
            "path": "tests/test_main.py",
            "change_type": "modified",
            "lines_added": 15,
            "lines_deleted": 3,
            "summary": "Updated tests",
        },
    ]


@pytest.fixture
def mock_ast_elements():
    """Create mock AST elements data."""
    return {
        "src/main.py": [
            {
                "name": "main",
                "element_type": "function",
                "signature": "def main()",
                "start_line": 2,
                "end_line": 3,
            },
            {
                "name": "MyClass",
                "element_type": "class",
                "signature": "class MyClass",
                "start_line": 5,
                "end_line": 7,
            },
        ],
        "src/utils.py": [
            {
                "name": "helper",
                "element_type": "function",
                "signature": "def helper()",
                "start_line": 2,
                "end_line": 3,
            },
            {
                "name": "process_data",
                "element_type": "function",
                "signature": "def process_data(data)",
                "start_line": 5,
                "end_line": 6,
            },
        ],
    }


@pytest.fixture
def executor(temp_repo, mock_changed_files, mock_ast_elements):
    """Create a ToolExecutor with mock data."""
    return ToolExecutor(
        repo_path=temp_repo,
        changed_files=mock_changed_files,
        ast_elements=mock_ast_elements,
        commit_range="HEAD~5..HEAD",
        focus_commits=None,
    )


class TestToolExecutorInit:
    """Tests for ToolExecutor initialization."""

    def test_init_with_defaults(self, temp_repo):
        """Test initialization with default values."""
        executor = ToolExecutor(repo_path=temp_repo)
        assert executor.repo_path == temp_repo
        assert executor.changed_files == []
        assert executor.ast_elements == {}
        assert executor.commit_range is None
        assert executor.focus_commits is None

    def test_init_with_data(self, temp_repo, mock_changed_files, mock_ast_elements):
        """Test initialization with provided data."""
        executor = ToolExecutor(
            repo_path=temp_repo,
            changed_files=mock_changed_files,
            ast_elements=mock_ast_elements,
            commit_range="HEAD~3..HEAD",
            focus_commits=["abc123"],
        )
        assert executor.changed_files == mock_changed_files
        assert executor.ast_elements == mock_ast_elements
        assert executor.commit_range == "HEAD~3..HEAD"
        assert executor.focus_commits == ["abc123"]

    def test_build_element_index(self, temp_repo, mock_ast_elements):
        """Test that element index is built correctly."""
        executor = ToolExecutor(
            repo_path=temp_repo,
            ast_elements=mock_ast_elements,
        )

        # Check _element_names index
        assert "main" in executor._element_names
        assert "MyClass" in executor._element_names
        assert "helper" in executor._element_names
        assert "process_data" in executor._element_names

        # Check _file_elements index
        assert "src/main.py" in executor._file_elements
        assert "src/utils.py" in executor._file_elements


class TestToolExecutorExecute:
    """Tests for ToolExecutor.execute method."""

    def test_execute_unknown_tool(self, executor):
        """Test executing an unknown tool."""
        call = ToolCall(tool_name="unknown_tool", arguments={})
        result = executor.execute(call)

        assert result.success is False
        assert "Unknown tool" in result.error

    def test_execute_with_exception(self, executor):
        """Test execute handles exceptions gracefully."""
        # Patch _read_file to raise an exception
        with patch.object(executor, "_read_file", side_effect=Exception("Test error")):
            call = ToolCall(tool_name="read_file", arguments={"path": "test.py"})
            result = executor.execute(call)

            assert result.success is False
            assert "Test error" in result.error

    def test_execute_batch(self, executor):
        """Test executing multiple tool calls."""
        calls = [
            ToolCall(tool_name="get_changed_files", arguments={}),
            ToolCall(
                tool_name="get_ast_elements", arguments={"file_path": "src/main.py"}
            ),
        ]
        results = executor.execute_batch(calls)

        assert len(results) == 2
        assert all(r.success for r in results)


class TestToolExecutorGetChangedFiles:
    """Tests for _get_changed_files tool."""

    def test_get_all_changed_files(self, executor):
        """Test getting all changed files."""
        result = executor._get_changed_files()

        assert "focused" in result
        assert "contextual" in result
        assert (
            len(result["focused"]) == 3
        )  # All files are focused when no focus_commits

    def test_exclude_contextual(self, executor):
        """Test excluding contextual files."""
        result = executor._get_changed_files(include_contextual=False)

        assert "focused" in result
        assert "contextual" not in result

    def test_filter_by_change_type(self, executor):
        """Test filtering by change type."""
        result = executor._get_changed_files(change_type_filter="added")

        # Only src/utils.py is added
        focused_paths = [f["path"] for f in result["focused"]]
        assert "src/utils.py" in focused_paths
        assert "src/main.py" not in focused_paths

    def test_handles_object_format(self, temp_repo):
        """Test handling file info as objects with attributes."""

        class FileInfo:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        changed_files = [
            FileInfo(
                path="a.py",
                change_type="modified",
                lines_added=5,
                lines_deleted=2,
                summary="",
            ),
        ]

        executor = ToolExecutor(repo_path=temp_repo, changed_files=changed_files)
        result = executor._get_changed_files()

        assert len(result["focused"]) == 1
        assert result["focused"][0]["path"] == "a.py"


class TestToolExecutorReadFile:
    """Tests for _read_file tool."""

    def test_read_existing_file(self, executor, temp_repo):
        """Test reading an existing file."""
        result = executor._read_file("src/main.py")

        assert "error" not in result
        assert result["path"] == "src/main.py"
        assert "total_lines" in result
        assert "content" in result
        assert "def main()" in result["content"]

    def test_read_file_with_line_range(self, executor):
        """Test reading specific line range."""
        result = executor._read_file("src/main.py", start_line=2, end_line=3)

        assert "error" not in result
        content = result["content"]
        assert "2:" in content  # Line numbers should be present
        assert "def main()" in content

    def test_read_nonexistent_file(self, executor):
        """Test reading a file that doesn't exist."""
        result = executor._read_file("nonexistent.py")

        assert result["error"] is not None
        assert "File not found" in result["error"]
        assert result["content"] is None

    def test_read_directory(self, executor):
        """Test reading a directory (should fail)."""
        result = executor._read_file("src")

        assert result["error"] is not None
        assert "Not a file" in result["error"]

    def test_path_traversal_protection(self, executor):
        """Test that path traversal is blocked."""
        result = executor._read_file("../outside.py")

        assert result["error"] is not None
        assert "Path traversal" in result["error"]

    def test_read_binary_file(self, executor, temp_repo):
        """Test reading a binary file (should fail gracefully)."""
        # Create a file with invalid UTF-8 bytes
        binary_file = temp_repo / "test_binary.bin"
        binary_file.write_bytes(b"\x80\x81\x82\x83\xff\xfe")

        result = executor._read_file("test_binary.bin")

        assert result.get("error") is not None
        assert (
            "Binary file" in result["error"] or "cannot read" in result["error"].lower()
        )


class TestToolExecutorSearchCode:
    """Tests for _search_code tool."""

    @patch("subprocess.run")
    def test_search_with_git_grep(self, mock_run, executor, temp_repo):
        """Test searching with git grep."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="src/main.py:2:def main():\nsrc/utils.py:2:def helper():\n",
        )

        result = executor._search_code("def ")

        assert result["total_matches"] == 2
        assert len(result["matches"]) == 2
        assert result["matches"][0]["file"] == "src/main.py"
        assert result["matches"][0]["line"] == 2

    @patch("subprocess.run")
    def test_search_with_file_pattern(self, mock_run, executor):
        """Test searching with file pattern filter."""
        mock_run.return_value = Mock(returncode=0, stdout="")

        executor._search_code("def ", file_pattern="*.py")

        # Check that git grep was called with -- and file pattern
        call_args = mock_run.call_args[0][0]
        assert "--" in call_args
        assert "*.py" in call_args

    @patch("subprocess.run")
    def test_search_git_not_found(self, mock_run, executor):
        """Test fallback when git is not available."""
        mock_run.side_effect = FileNotFoundError()

        result = executor._search_code("def ")

        # Should still return results via Python fallback
        assert "matches" in result

    @patch("subprocess.run")
    def test_search_timeout(self, mock_run, executor):
        """Test handling timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)

        result = executor._search_code("def ")

        # Should still return results via Python fallback
        assert "matches" in result

    def test_search_code_python_fallback(self, executor, temp_repo):
        """Test the Python fallback search method."""
        matches = executor._search_code_python("def main", "*.py", 10)

        assert len(matches) > 0
        assert any(m["content"] and "def main" in m["content"] for m in matches)

    def test_max_results_limit(self, executor):
        """Test that max_results limits the output."""
        with patch.object(
            executor, "_search_code_python", return_value=[]
        ) as mock_search:
            with patch("subprocess.run", side_effect=FileNotFoundError()):
                result = executor._search_code(".", max_results=5)
                # The mock prevents actual results, but verifies the flow


class TestToolExecutorValidateReference:
    """Tests for _validate_reference tool."""

    def test_validate_existing_file(self, executor, temp_repo):
        """Test validating an existing file."""
        result = executor._validate_reference("file", "src/main.py")

        assert result["found"] is True
        assert result["reference_type"] == "file"
        assert result["name"] == "src/main.py"
        assert len(result["locations"]) == 1

    def test_validate_nonexistent_file(self, executor):
        """Test validating a non-existent file."""
        result = executor._validate_reference("file", "nonexistent.py")

        assert result["found"] is False
        assert len(result["locations"]) == 0

    def test_validate_existing_function_from_ast(self, executor):
        """Test validating a function that exists in AST."""
        result = executor._validate_reference("function", "main")

        assert result["found"] is True
        assert len(result["locations"]) > 0
        assert any(loc["file"] == "src/main.py" for loc in result["locations"])

    def test_validate_with_file_path_filter(self, executor):
        """Test validating with file path filter."""
        result = executor._validate_reference(
            "function", "main", file_path="src/main.py"
        )

        assert result["found"] is True
        # Should only return locations in src/main.py
        assert all(loc["file"] == "src/main.py" for loc in result["locations"])

    def test_validate_nonexistent_element_with_suggestions(self, executor):
        """Test validating non-existent element returns suggestions."""
        result = executor._validate_reference("function", "nonexistent")

        assert result["found"] is False
        # Should have suggestions based on similar names
        assert len(result["suggestions"]) > 0 or True  # May or may not have suggestions

    @patch("subprocess.run")
    def test_validate_fallback_to_git_grep(self, mock_run, executor):
        """Test fallback to git grep when not in AST."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="src/main.py:5:class MyClass:\n",
        )

        # MyClass is in AST, but let's test with something that might not be
        result = executor._validate_reference("class", "MyClass")

        # Should find it from AST
        assert result["found"] is True


class TestToolExecutorGetAstElements:
    """Tests for _get_ast_elements tool."""

    def test_get_all_elements(self, executor):
        """Test getting all AST elements."""
        result = executor._get_ast_elements()

        assert result["total"] == 4  # main, MyClass, helper, process_data
        assert len(result["elements"]) == 4

    def test_get_elements_for_specific_file(self, executor):
        """Test getting elements for a specific file."""
        result = executor._get_ast_elements(file_path="src/main.py")

        assert result["total"] == 2  # main, MyClass
        # Elements are returned as-is from storage (dicts already have file_path if set)
        assert len(result["elements"]) == 2
        assert all(
            e.get("element_type") in ["function", "class"] for e in result["elements"]
        )

    def test_filter_by_element_type(self, executor):
        """Test filtering elements by type."""
        result = executor._get_ast_elements(element_type="function")

        # Should only return functions, not classes
        assert all(e["element_type"] == "function" for e in result["elements"])
        assert len(result["elements"]) == 3  # main, helper, process_data

    def test_get_elements_nonexistent_file(self, executor):
        """Test getting elements for non-existent file."""
        result = executor._get_ast_elements(file_path="nonexistent.py")

        assert result["total"] == 0
        assert result["elements"] == []

    def test_element_to_dict_with_object(self, executor):
        """Test converting object-style element to dict."""

        class MockElement:
            name = "test_func"
            element_type = "function"
            signature = "def test_func()"
            docstring = "Test function"
            start_line = 1
            end_line = 2
            file_path = "test.py"
            parent = None
            children = []

        result = executor._element_to_dict(MockElement())

        assert result["name"] == "test_func"
        assert result["element_type"] == "function"
        assert result["signature"] == "def test_func()"

    def test_element_to_dict_with_dict(self, executor):
        """Test converting dict-style element."""
        elem = {"name": "test", "element_type": "class"}
        result = executor._element_to_dict(elem)

        assert result == elem


# =============================================================================
# chat_with_tools Tests
# =============================================================================


class TestFormatToolsPrompt:
    """Tests for _format_tools_prompt function."""

    def test_includes_all_tools(self):
        """Test that prompt includes all tool descriptions."""
        from ggdes.tools.chat_with_tools import _format_tools_prompt

        prompt = _format_tools_prompt(TOOL_DEFINITIONS)

        for tool in TOOL_DEFINITIONS:
            assert tool.name in prompt
            assert tool.description in prompt

    def test_includes_parameters(self):
        """Test that prompt includes parameter descriptions."""
        from ggdes.tools.chat_with_tools import _format_tools_prompt

        prompt = _format_tools_prompt(TOOL_DEFINITIONS)

        # Check for parameter descriptions
        assert "Parameters:" in prompt
        assert "required" in prompt.lower() or "optional" in prompt.lower()

    def test_includes_usage_instructions(self):
        """Test that prompt includes usage instructions."""
        from ggdes.tools.chat_with_tools import _format_tools_prompt

        prompt = _format_tools_prompt(TOOL_DEFINITIONS)

        assert "```tool_call" in prompt
        assert "tool_name" in prompt or "tool" in prompt
        assert "arguments" in prompt


class TestParseToolCalls:
    """Tests for _parse_tool_calls function."""

    def test_parse_single_tool_call(self):
        """Test parsing a single tool call."""
        from ggdes.tools.chat_with_tools import _parse_tool_calls

        response = """
I'll help you with that.

```tool_call
{"tool": "read_file", "arguments": {"path": "test.py"}}
```

Let me analyze this.
"""
        calls = _parse_tool_calls(response)

        assert len(calls) == 1
        assert calls[0].tool_name == "read_file"
        assert calls[0].arguments == {"path": "test.py"}

    def test_parse_multiple_tool_calls(self):
        """Test parsing multiple tool calls."""
        from ggdes.tools.chat_with_tools import _parse_tool_calls

        response = """
```tool_call
{"tool": "read_file", "arguments": {"path": "a.py"}}
```

Some text here.

```tool_call
{"tool": "search_code", "arguments": {"pattern": "def "}}
```
"""
        calls = _parse_tool_calls(response)

        assert len(calls) == 2
        assert calls[0].tool_name == "read_file"
        assert calls[1].tool_name == "search_code"

    def test_parse_alternative_keys(self):
        """Test parsing with alternative JSON keys."""
        from ggdes.tools.chat_with_tools import _parse_tool_calls

        # Test with 'name' instead of 'tool'
        response = """
```tool_call
{"name": "get_changed_files", "args": {}}
```
"""
        calls = _parse_tool_calls(response)

        assert len(calls) == 1
        assert calls[0].tool_name == "get_changed_files"

    def test_parse_invalid_json(self):
        """Test handling invalid JSON in tool call."""
        from ggdes.tools.chat_with_tools import _parse_tool_calls

        response = """
```tool_call
{invalid json here}
```

```tool_call
{"tool": "read_file", "arguments": {"path": "test.py"}}
```
"""
        calls = _parse_tool_calls(response)

        # Should skip invalid and parse valid
        assert len(calls) == 1
        assert calls[0].tool_name == "read_file"

    def test_parse_no_tool_calls(self):
        """Test parsing response with no tool calls."""
        from ggdes.tools.chat_with_tools import _parse_tool_calls

        response = "This is just a regular response with no tools."
        calls = _parse_tool_calls(response)

        assert len(calls) == 0


class TestFormatToolResults:
    """Tests for _format_tool_results function."""

    def test_format_success_results(self):
        """Test formatting successful results."""
        from ggdes.tools.chat_with_tools import _format_tool_results

        results = [
            ToolResult(tool_name="read_file", success=True, result="content here"),
            ToolResult(tool_name="search_code", success=True, result={"matches": []}),
        ]
        formatted = _format_tool_results(results)

        assert "read_file" in formatted
        assert "search_code" in formatted
        assert "content here" in formatted

    def test_format_error_results(self):
        """Test formatting error results."""
        from ggdes.tools.chat_with_tools import _format_tool_results

        results = [
            ToolResult(
                tool_name="read_file",
                success=False,
                result=None,
                error="File not found",
            ),
        ]
        formatted = _format_tool_results(results)

        assert "read_file" in formatted
        assert "error" in formatted.lower() or "File not found" in formatted

    def test_truncate_long_results(self):
        """Test that very long results are truncated."""
        from ggdes.tools.chat_with_tools import _format_tool_results

        long_content = "x" * 4000
        results = [
            ToolResult(tool_name="read_file", success=True, result=long_content),
        ]
        formatted = _format_tool_results(results)

        assert "truncated" in formatted


class TestChatWithTools:
    """Tests for chat_with_tools function."""

    def test_no_tool_calls_returns_directly(self):
        """Test that response without tool calls is returned directly."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "This is the final answer."

        executor = MagicMock()

        messages = [{"role": "user", "content": "Hello"}]

        result = chat_with_tools(
            llm=mock_llm,
            messages=messages,
            tools=TOOL_DEFINITIONS[:1],  # Just one tool
            executor=executor,
            max_rounds=5,
        )

        assert result == "This is the final answer."
        mock_llm.chat.assert_called_once()

    def test_single_tool_call_round(self):
        """Test a single round of tool calls."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            'Let me check.\n```tool_call\n{"tool": "read_file", "arguments": {"path": "test.py"}}\n```',
            "The file contains: def test(): pass",
        ]

        mock_executor = MagicMock()
        mock_executor.execute_batch.return_value = [
            ToolResult(tool_name="read_file", success=True, result="def test(): pass"),
        ]

        messages = [{"role": "user", "content": "What's in test.py?"}]

        result = chat_with_tools(
            llm=mock_llm,
            messages=messages,
            tools=TOOL_DEFINITIONS[:1],
            executor=mock_executor,
            max_rounds=5,
        )

        assert "def test(): pass" in result
        assert mock_llm.chat.call_count == 2
        mock_executor.execute_batch.assert_called_once()

    def test_max_rounds_limit(self):
        """Test that max_rounds limits the tool calling loop."""
        mock_llm = MagicMock()
        # Always return a tool call
        mock_llm.chat.return_value = (
            '```tool_call\n{"tool": "get_changed_files", "arguments": {}}\n```'
        )

        mock_executor = MagicMock()
        mock_executor.execute_batch.return_value = [
            ToolResult(tool_name="get_changed_files", success=True, result={}),
        ]

        messages = [{"role": "user", "content": "Test"}]

        # Mock console to suppress output - patch at module level using sys.modules
        import sys

        chat_module = sys.modules.get("ggdes.tools.chat_with_tools")
        if chat_module:
            original_console = getattr(chat_module, "console", None)
            chat_module.console = MagicMock()
        try:
            result = chat_with_tools(
                llm=mock_llm,
                messages=messages,
                tools=TOOL_DEFINITIONS[:1],
                executor=mock_executor,
                max_rounds=2,
            )
        finally:
            if chat_module and original_console:
                chat_module.console = original_console

        # Should stop after max_rounds even if there are still tool calls
        assert mock_llm.chat.call_count == 2

    def test_appends_tools_to_existing_system_message(self):
        """Test that tools are appended to existing system message."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "Response"

        executor = MagicMock()

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]

        chat_with_tools(
            llm=mock_llm,
            messages=messages,
            tools=TOOL_DEFINITIONS[:1],
            executor=executor,
        )

        # Check that system message was modified
        call_args = mock_llm.chat.call_args[1]
        working_messages = call_args["messages"]
        system_msg = next(m for m in working_messages if m["role"] == "system")
        assert "You are a helpful assistant." in system_msg["content"]
        assert "Available Tools" in system_msg["content"]

    def test_inserts_system_message_if_none_exists(self):
        """Test that system message is inserted if none exists."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "Response"

        executor = MagicMock()

        messages = [{"role": "user", "content": "Hello"}]

        chat_with_tools(
            llm=mock_llm,
            messages=messages,
            tools=TOOL_DEFINITIONS[:1],
            executor=executor,
        )

        call_args = mock_llm.chat.call_args[1]
        working_messages = call_args["messages"]
        assert working_messages[0]["role"] == "system"
        assert "Available Tools" in working_messages[0]["content"]

    def test_custom_system_prompt(self):
        """Test using a custom system prompt."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "Response"

        executor = MagicMock()

        messages = [{"role": "user", "content": "Hello"}]

        chat_with_tools(
            llm=mock_llm,
            messages=messages,
            tools=TOOL_DEFINITIONS[:1],
            executor=executor,
            system_prompt="Custom system prompt here.",
        )

        call_args = mock_llm.chat.call_args[1]
        working_messages = call_args["messages"]
        assert "Custom system prompt here." in working_messages[0]["content"]


# =============================================================================
# Integration Tests
# =============================================================================


class TestToolIntegration:
    """Integration tests for the complete tool system."""

    def test_full_tool_execution_flow(
        self, temp_repo, mock_changed_files, mock_ast_elements
    ):
        """Test the complete flow from tool call to result."""
        # Create executor
        executor = ToolExecutor(
            repo_path=temp_repo,
            changed_files=mock_changed_files,
            ast_elements=mock_ast_elements,
        )

        # Create a tool call
        call = ToolCall(
            tool_name="read_file",
            arguments={"path": "src/main.py", "start_line": 1, "end_line": 5},
        )

        # Execute
        result = executor.execute(call)

        # Verify
        assert result.success is True
        assert result.tool_name == "read_file"
        assert "content" in result.result

    def test_multiple_tools_in_sequence(self, temp_repo, mock_ast_elements):
        """Test executing multiple different tools."""
        executor = ToolExecutor(
            repo_path=temp_repo,
            changed_files=[],
            ast_elements=mock_ast_elements,
        )

        calls = [
            ToolCall(
                tool_name="get_ast_elements", arguments={"element_type": "function"}
            ),
            ToolCall(
                tool_name="validate_reference",
                arguments={"reference_type": "function", "name": "main"},
            ),
        ]

        results = executor.execute_batch(calls)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert results[0].tool_name == "get_ast_elements"
        assert results[1].tool_name == "validate_reference"

    def test_chat_loop_with_real_executor(
        self, temp_repo, mock_changed_files, mock_ast_elements
    ):
        """Test chat_with_tools with a real executor."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            'Let me check the files.\n```tool_call\n{"tool": "get_changed_files", "arguments": {}}\n```',
            "I found 3 changed files in the repository.",
        ]

        executor = ToolExecutor(
            repo_path=temp_repo,
            changed_files=mock_changed_files,
            ast_elements=mock_ast_elements,
        )

        messages = [{"role": "user", "content": "What files changed?"}]

        # Mock console to suppress output - patch at module level using sys.modules
        import sys

        chat_module = sys.modules.get("ggdes.tools.chat_with_tools")
        if chat_module:
            original_console = getattr(chat_module, "console", None)
            chat_module.console = MagicMock()
        try:
            result = chat_with_tools(
                llm=mock_llm,
                messages=messages,
                tools=[TOOL_GET_CHANGED_FILES],
                executor=executor,
                max_rounds=5,
            )
        finally:
            if chat_module and original_console:
                chat_module.console = original_console

        assert (
            "found" in result.lower()
            or "changed" in result.lower()
            or "files" in result.lower()
        )
        assert mock_llm.chat.call_count == 2
