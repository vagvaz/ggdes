"""Tool-augmented chat for LLM agents.

Provides a provider-agnostic tool calling loop that wraps the existing
chat() method with tool use capabilities. Works with all LLM providers
(OpenAI, Anthropic, Ollama, Custom) without modifying their internals.

The approach uses prompt engineering to elicit tool calls from the LLM,
parses the structured responses, executes the tools, and feeds results
back into the conversation.
"""

import json
import re
from typing import Any, Dict, List, Optional

from rich.console import Console

from ggdes.llm import LLMProvider
from ggdes.tools.definitions import ToolCall, ToolDefinition, ToolResult
from ggdes.tools.executor import ToolExecutor

console = Console()

# Maximum tool call rounds to prevent infinite loops
MAX_TOOL_ROUNDS = 10


def _format_tools_prompt(tools: List[ToolDefinition]) -> str:
    """Format tool definitions as a prompt section for the LLM.

    Args:
        tools: Available tool definitions

    Returns:
        Formatted prompt section describing available tools
    """
    lines = [
        "You have access to the following tools. Use them to verify your claims "
        "against the actual codebase before committing to technical facts or "
        "referencing code elements.",
        "",
        "## Available Tools",
        "",
    ]

    for tool in tools:
        lines.append(f"### {tool.name}")
        lines.append(f"{tool.description}")
        lines.append("")
        lines.append("Parameters:")
        for param in tool.parameters:
            req = "required" if param.required else "optional"
            type_str = param.type
            if param.enum:
                type_str += f" (one of: {', '.join(param.enum)})"
            lines.append(f"  - {param.name} ({type_str}, {req}): {param.description}")
        lines.append(f"Returns: {tool.returns}")
        lines.append("")

    lines.extend(
        [
            "## How to Call Tools",
            "",
            "When you need to use a tool, include a tool call block in your response "
            "using this exact format:",
            "",
            "```tool_call",
            '{"tool": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}',
            "```",
            "",
            "You can include multiple tool calls in a single response. After your tool "
            "calls, continue with your analysis. The tools will be executed and their "
            "results will be provided to you.",
            "",
            "IMPORTANT: Always verify code references before including them in technical "
            "facts. Use validate_reference to check that function names, class names, and "
            "file paths actually exist. Use read_file to examine actual code before "
            "describing what it does.",
            "",
        ]
    )

    return "\n".join(lines)


def _parse_tool_calls(response: str) -> List[ToolCall]:
    """Parse tool call blocks from LLM response.

    Looks for ```tool_call ... ``` blocks containing JSON.

    Args:
        response: LLM response text

    Returns:
        List of parsed ToolCall objects
    """
    calls = []

    # Match ```tool_call ... ``` blocks
    pattern = r"```tool_call\s*\n(.*?)\n```"
    matches = re.findall(pattern, response, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match.strip())
            tool_name = data.get("tool") or data.get("name") or data.get("function")
            arguments = (
                data.get("arguments")
                or data.get("args")
                or data.get("parameters")
                or {}
            )

            if tool_name:
                calls.append(
                    ToolCall(
                        tool_name=tool_name,
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        except json.JSONDecodeError:
            console.print(f"[dim]Failed to parse tool call: {match[:100]}[/dim]")
            continue

    return calls


def _format_tool_results(results: List[ToolResult]) -> str:
    """Format tool execution results for inclusion in LLM messages.

    Args:
        results: Tool execution results

    Returns:
        Formatted string with tool results
    """
    lines = ["", "## Tool Results", ""]

    for result in results:
        if result.success:
            lines.append(f"**{result.tool_name}**:")
            content = result.to_message_content()
            # Truncate very long results
            if len(content) > 3000:
                content = content[:2950] + "\n... (truncated)"
            lines.append(f"```{content}```")
        else:
            lines.append(f"**{result.tool_name}** (error): {result.error}")
        lines.append("")

    return "\n".join(lines)


def chat_with_tools(
    llm: LLMProvider,
    messages: List[Dict[str, Any]],
    tools: List[ToolDefinition],
    executor: ToolExecutor,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    """Chat with an LLM agent that can use tools.

    This function implements a tool-calling loop:
    1. Send messages with tool descriptions to the LLM
    2. Parse any tool calls from the response
    3. Execute the tool calls
    4. Feed results back to the LLM
    5. Repeat until no more tool calls or max rounds reached

    Args:
        llm: LLM provider instance
        messages: Conversation messages
        tools: Available tool definitions
        executor: Tool executor instance
        system_prompt: Optional system prompt (tool descriptions will be appended)
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        max_rounds: Maximum tool-calling rounds

    Returns:
        Final LLM response text (after all tool calls are resolved)
    """
    # Build system prompt with tool descriptions
    tools_prompt = _format_tools_prompt(tools)

    if system_prompt:
        full_system_prompt = f"{system_prompt}\n\n{tools_prompt}"
    else:
        full_system_prompt = tools_prompt

    # Build message list with system prompt
    working_messages = list(messages)

    # Ensure system prompt is present
    has_system = any(msg.get("role") == "system" for msg in working_messages)
    if has_system:
        # Append tools to existing system message
        for i, msg in enumerate(working_messages):
            if msg.get("role") == "system":
                working_messages[i] = {
                    "role": "system",
                    "content": msg["content"] + "\n\n" + tools_prompt,
                }
                break
    else:
        # Insert system prompt at the beginning
        working_messages.insert(
            0,
            {
                "role": "system",
                "content": full_system_prompt,
            },
        )

    # Tool calling loop
    for round_num in range(max_rounds):
        # Get LLM response
        response = llm.chat(
            messages=working_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Parse tool calls from response
        tool_calls = _parse_tool_calls(response)

        if not tool_calls:
            # No tool calls - we're done
            return response

        # Execute tool calls
        console.print(
            f"  [dim]Tool round {round_num + 1}: {len(tool_calls)} call(s)[/dim]"
        )
        for call in tool_calls:
            console.print(
                f"    [dim]→ {call.tool_name}({json.dumps(call.arguments, default=str)[:80]})[/dim]"
            )

        results = executor.execute_batch(tool_calls)

        for result in results:
            if result.success:
                console.print(f"    [green]✓ {result.tool_name}[/green]")
            else:
                console.print(f"    [red]✗ {result.tool_name}: {result.error}[/red]")

        # Format results and add to conversation
        tool_results_text = _format_tool_results(results)

        # Add assistant response and tool results to conversation
        working_messages.append({"role": "assistant", "content": response})
        working_messages.append({"role": "user", "content": tool_results_text})

    # If we hit max rounds, return the last response
    console.print(f"  [yellow]Warning: Reached max tool rounds ({max_rounds})[/yellow]")
    return response
