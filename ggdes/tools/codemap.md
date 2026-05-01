# ggdes/tools/

## Responsibility

Tool system for LLM agents to access grounded, real codebase data during analysis.
Prevents hallucinations by letting agents verify claims against actual source code
before committing to technical facts. Provides a provider-agnostic tool-calling loop.

## Design

### File Layout

| File | Key Exports | Responsibility |
|---|---|---|
| `definitions.py` | `ToolDefinition`, `ToolCall`, `ToolResult`, `TOOL_DEFINITIONS`, `get_tool_by_name()` | Pydantic schemas for tool definitions, calls, and results; schema converters for OpenAI/Anthropic; all 7 tool definitions |
| `executor.py` | `ToolExecutor` | Executes tool calls against git repo filesystem, AST data, and source diffs |
| `chat_with_tools.py` | `chat_with_tools()` | Provider-agnostic multi-turn tool-calling loop |

### Available Tools (`TOOL_DEFINITIONS`)

| Tool | Parameters | Returns | Purpose |
|---|---|---|---|
| `get_changed_files` | `include_contextual` (bool), `change_type_filter` ("added"\|"modified"\|"deleted"\|"renamed") | Focused + contextual file lists with change type and line counts | Get files changed in the analysis commit range |
| `read_file` | `path` (string, required), `start_line`, `end_line` | File content with line numbers, total lines | Examine actual code in the repository |
| `search_code` | `pattern` (regex, required), `file_pattern` (glob), `max_results` | Matches with file, line, and content | Find where functions/classes/variables are defined or used |
| `validate_reference` | `reference_type` ("file"\|"function"\|"class"\|"variable"), `name`, `file_path` | Found status, locations, suggestions | Verify a code element exists before referencing it |
| `get_ast_elements` | `file_path`, `element_type` ("function"\|"method"\|"class"\|"variable"\|"constant") | List of code elements with name, type, signature, location | Get structured AST info about code elements |
| `get_element_source` | `element_name` (required), `file_path`, `max_lines` | Source code with signature, docstring, line range | PRIMARY anti-hallucination tool — retrieves real source code |
| `find_element_name` | `search_term` (required) | List of actual element names matching search | Look up exact code element name before writing facts |

### Schema Converters

Each `ToolDefinition` provides:
- **`to_openai_schema()`** — OpenAI function-calling format
- **`to_anthropic_schema()`** — Anthropic tool-use format

### ToolExecutor (`executor.py`)

Initialized with:
- `repo_path: Path` — Git repository root
- `changed_files: list[dict]` — Changed file info from git analysis
- `ast_elements: dict[str, list[Any]]` — Parsed AST elements per file
- `commit_range: str` — Git commit range
- `focus_commits: list[str]` — Specific commits to focus on
- `source_diffs_cache: dict` — Pre-computed source diffs for instant `get_element_source()`

Internal indexes:
- `_element_names: dict[str, list[str]]` — Element name → list of file paths
- `_file_elements: dict[str, list[Any]]` — File path → list of elements

Key architectural details:

- **Path traversal prevention:** `read_file` resolves the path and verifies it's
  within `repo_path`.
- **Binary file detection:** `read_file` catches `UnicodeDecodeError` and returns
  an error rather than corrupt data.
- **Dual-mode search:** `search_code` tries `git grep` first (fast), falls back to
  Python-based `re` search on the filesystem.
- **Focused file detection:** `_get_changed_files` uses `git diff-tree` against
  `focus_commits` to categorize files as focused vs. contextual.
- **Similar name suggestions:** `_validate_reference` tries substring and prefix
  matching to suggest corrections when a name is not found.

### Caching Strategy (`source_diffs_cache`)

The `source_diffs_cache` provides a fast path for `get_element_source()`:
- Keyed by `file_path::element_name` or just `element_name`
- Contains `{before, after, diff, element_name, file_path}`
- When populated, returns instantly without file I/O
- Set via `executor.set_source_diffs_cache()`

### Tool-Augmented Chat (`chat_with_tools.py`)

`chat_with_tools()` implements a multi-turn tool-calling loop:

```
1. Build system prompt with tool descriptions appended
2. Send messages to LLM via llm.chat()
3. Parse response for ```tool_call ... ``` blocks
4. If no tool calls → return final response
5. Execute tool calls via executor.execute_batch()
6. Format results and append to conversation
7. Goto 2 (max MAX_TOOL_ROUNDS = 10 rounds)
```

Tool call format in LLM response:
```markdown
```tool_call
{"tool": "tool_name", "arguments": {"param1": "value1"}}
```
```

The loop aggregates tool usage stats and warns if the same element is requested
multiple times (detecting inefficient agent behavior).

## Flow

```
LLM Agent (in analysis pipeline)
    ↓
chat_with_tools(llm, messages, tools, executor)
    ↓
  Round 1: Send messages → LLM generates response
    ↓
  Parse tool calls from ```tool_call``` blocks
    ↓
  If none → return final response
    ↓
  Execute via executor.execute_batch(tool_calls)
    ↓
  → _get_changed_files / _read_file / _search_code / etc.
    ↓
  Append results to messages → Round 2
    ↓
  ... (up to 10 rounds)
    ↓
  Return final LLM response
```

## Integration

- **Used by** analysis agents (`ggdes/agents/`) during technical author and
  chart generation to verify facts against the codebase.
- **`chat_with_tools()`** wraps any `LLMProvider` instance — provider-agnostic by design.
- **`TOOL_DEFINITIONS`** are registered in `ggdes/tools/__init__.py` and re-exported
  for use by agent code.
- **`ToolExecutor`** is constructed with data from earlier pipeline stages:
  `changed_files` from git analysis, `ast_elements` from AST parsing,
  `source_diffs_cache` from semantic diff.
- **`validate_reference`** complements `ggdes/validation/code_references.py`:
  the validator checks LLM *output* for hallucinated references, while the tool
  lets the LLM *proactively* verify references during generation.
