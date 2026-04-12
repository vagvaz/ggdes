"""Tool definitions for LLM function calling.

Defines the schema for tools that LLM agents can invoke during analysis.
These tools provide grounded access to the codebase, preventing hallucinations.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """Parameter definition for a tool."""

    name: str = Field(description="Parameter name")
    type: str = Field(description="Parameter type: string, integer, boolean, array")
    description: str = Field(description="What this parameter provides")
    required: bool = Field(
        default=True, description="Whether this parameter is required"
    )
    enum: Optional[List[str]] = Field(
        default=None, description="Allowed values if this is an enum type"
    )


class ToolDefinition(BaseModel):
    """Definition of a tool available to LLM agents."""

    name: str = Field(description="Unique tool name")
    description: str = Field(description="What this tool does and when to use it")
    parameters: List[ToolParameter] = Field(description="Parameters this tool accepts")
    returns: str = Field(description="Description of what this tool returns")

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling schema.

        Returns:
            Dictionary compatible with OpenAI's function calling format
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic tool use schema.

        Returns:
            Dictionary compatible with Anthropic's tool use format
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolCall(BaseModel):
    """A tool invocation request from an LLM."""

    tool_name: str = Field(description="Name of the tool to invoke")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the tool"
    )
    call_id: Optional[str] = Field(
        default=None, description="Call ID for tracking (used by OpenAI-style APIs)"
    )


class ToolResult(BaseModel):
    """Result from a tool execution."""

    tool_name: str = Field(description="Name of the tool that was executed")
    success: bool = Field(description="Whether the tool execution succeeded")
    result: Any = Field(description="The tool's return value")
    error: Optional[str] = Field(
        default=None, description="Error message if execution failed"
    )

    def to_message_content(self) -> str:
        """Convert result to a string suitable for inclusion in LLM messages.

        Returns:
            String representation of the result
        """
        if not self.success:
            return f"Error calling {self.tool_name}: {self.error}"

        if isinstance(self.result, str):
            return self.result

        import json

        return json.dumps(self.result, indent=2, default=str)


# ============================================================================
# Tool Definitions
# ============================================================================

TOOL_GET_CHANGED_FILES = ToolDefinition(
    name="get_changed_files",
    description=(
        "Get the list of files changed in the analysis commit range, "
        "categorized by whether they are in the focused commits or are "
        "contextual (referenced/imported by changed files). Use this tool "
        "to understand which files are the primary focus of the analysis "
        "and which are merely related context."
    ),
    parameters=[
        ToolParameter(
            name="include_contextual",
            type="boolean",
            description="Whether to include contextual (non-focused) files",
            required=False,
        ),
        ToolParameter(
            name="change_type_filter",
            type="string",
            description="Filter by change type",
            required=False,
            enum=["added", "modified", "deleted", "renamed"],
        ),
    ],
    returns="Object with 'focused' and 'contextual' file lists, each containing "
    "file path, change type, and lines changed",
)

TOOL_READ_FILE = ToolDefinition(
    name="read_file",
    description=(
        "Read the contents of a source file from the repository. Use this tool "
        "to examine actual code when you need to verify function signatures, "
        "class definitions, implementation details, or understand how code "
        "elements relate to each other. Always prefer this over guessing code content."
    ),
    parameters=[
        ToolParameter(
            name="path",
            type="string",
            description="Path to the file relative to repository root",
            required=True,
        ),
        ToolParameter(
            name="start_line",
            type="integer",
            description="Starting line number (1-indexed, inclusive)",
            required=False,
        ),
        ToolParameter(
            name="end_line",
            type="integer",
            description="Ending line number (1-indexed, inclusive)",
            required=False,
        ),
    ],
    returns="File contents as a string, with line numbers. Returns an error if "
    "the file does not exist or cannot be read.",
)

TOOL_SEARCH_CODE = ToolDefinition(
    name="search_code",
    description=(
        "Search for code patterns in the repository using regex. Use this tool "
        "to find where functions, classes, or variables are defined or used. "
        "Helpful for verifying that code elements you reference actually exist "
        "and understanding their usage patterns."
    ),
    parameters=[
        ToolParameter(
            name="pattern",
            type="string",
            description="Regex pattern to search for (e.g., 'def my_function', 'class MyClass')",
            required=True,
        ),
        ToolParameter(
            name="file_pattern",
            type="string",
            description="Glob pattern to filter files (e.g., '*.py', 'src/**/*.js')",
            required=False,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of results to return (default: 20)",
            required=False,
        ),
    ],
    returns="List of matches with file path, line number, and matching line content",
)

TOOL_VALIDATE_REFERENCE = ToolDefinition(
    name="validate_reference",
    description=(
        "Validate that a code reference (file path, function name, class name) "
        "actually exists in the codebase. Use this tool before committing to "
        "a technical fact or diagram component name to ensure you are not "
        "hallucinating code elements that don't exist."
    ),
    parameters=[
        ToolParameter(
            name="reference_type",
            type="string",
            description="Type of reference to validate",
            required=True,
            enum=["file", "function", "class", "variable"],
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Name of the element to validate (e.g., 'MyClass', 'process_data')",
            required=True,
        ),
        ToolParameter(
            name="file_path",
            type="string",
            description="Optional file path to narrow the search scope",
            required=False,
        ),
    ],
    returns="Object with 'found' (boolean), 'locations' (list of file:line where found), "
    "and 'suggestions' (similar names if not found)",
)

TOOL_GET_AST_ELEMENTS = ToolDefinition(
    name="get_ast_elements",
    description=(
        "Get AST (Abstract Syntax Tree) elements for a specific file or the "
        "entire changed file set. Returns structured information about functions, "
        "classes, methods, and their signatures. Use this to get accurate "
        "signatures and relationships between code elements."
    ),
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="Specific file to get elements for, or empty for all changed files",
            required=False,
        ),
        ToolParameter(
            name="element_type",
            type="string",
            description="Filter by element type",
            required=False,
            enum=["function", "method", "class", "variable", "constant"],
        ),
    ],
    returns="List of code elements with name, type, signature, file path, and line numbers",
)

TOOL_GET_ELEMENT_SOURCE = ToolDefinition(
    name="get_element_source",
    description=(
        "Get the actual source code for a named code element (function, class, method). "
        "Use this tool BEFORE describing what a function or class does, to ensure your "
        "description matches the real implementation. This is the PRIMARY anti-hallucination "
        "tool: always call this when you need to reference or describe specific code behavior, "
        "signatures, or implementation details. Never guess or fabricate code — always retrieve "
        "the actual source first."
    ),
    parameters=[
        ToolParameter(
            name="element_name",
            type="string",
            description="Name of the code element (function, class, or method name) to retrieve source for",
            required=True,
        ),
        ToolParameter(
            name="file_path",
            type="string",
            description="Optional file path to narrow the search scope when multiple elements share the same name",
            required=False,
        ),
        ToolParameter(
            name="max_lines",
            type="integer",
            description="Maximum number of source lines to return (default: 50, to avoid overwhelming context)",
            required=False,
        ),
    ],
    returns="Source code of the element with file path, line numbers, signature, and docstring. "
    "Returns an error if the element is not found.",
)

# All available tools
TOOL_DEFINITIONS: List[ToolDefinition] = [
    TOOL_GET_CHANGED_FILES,
    TOOL_READ_FILE,
    TOOL_SEARCH_CODE,
    TOOL_VALIDATE_REFERENCE,
    TOOL_GET_AST_ELEMENTS,
    TOOL_GET_ELEMENT_SOURCE,
]

# Lookup by name
_TOOL_LOOKUP = {tool.name: tool for tool in TOOL_DEFINITIONS}


def get_tool_by_name(name: str) -> Optional[ToolDefinition]:
    """Get a tool definition by name.

    Args:
        name: Tool name

    Returns:
        ToolDefinition or None if not found
    """
    return _TOOL_LOOKUP.get(name)
