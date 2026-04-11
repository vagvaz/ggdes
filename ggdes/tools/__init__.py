"""LLM tool definitions and implementations for grounded analysis.

Tools allow LLM agents to access real codebase data during analysis,
preventing hallucinations and ensuring generated content references
actual code elements.
"""

from ggdes.tools.chat_with_tools import chat_with_tools
from ggdes.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolParameter,
    ToolResult,
    TOOL_DEFINITIONS,
    get_tool_by_name,
)
from ggdes.tools.executor import ToolExecutor

__all__ = [
    "ToolCall",
    "ToolDefinition",
    "ToolParameter",
    "ToolResult",
    "TOOL_DEFINITIONS",
    "ToolExecutor",
    "chat_with_tools",
    "get_tool_by_name",
]
