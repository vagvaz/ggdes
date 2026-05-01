# ggdes/prompts/

## Responsibility

Versioned prompt management system. Provides structured, versioned YAML prompt files for each agent in the GGDes pipeline, plus a `PromptLoader` that resolves versions and caches loaded prompts. Ensures prompt changes are tracked and rollback-able.

## Files

| File | Role |
|------|------|
| `loader.py` | `PromptLoader` class + convenience functions `get_default_loader()` and `get_prompt()` |
| `v1.0.0/` | Versioned prompt directory (current production prompts) |
| `v1.0.0/git_analyzer.yaml` | Git analysis agent prompts |
| `v1.0.0/technical_author.yaml` | Technical facts authoring agent prompts |
| `v1.0.0/coordinator.yaml` | Document planning/coordination agent prompts |
| `v1.0.0/output.yaml` | Output generation agent prompts (markdown/docx/pdf/pptx) |
| `v1.0.0/change_filter.yaml` | Feature-relevance filtering agent prompts |
| `v1.0.0/validation.yaml` | Documentation validation agent prompts |

## Design

### Prompt Versioning

Versions are subdirectories under `ggdes/prompts/` named like `v1.0.0`. The default version is `"current"`, resolved at the directory level. Future versions can be added as new directories (e.g., `v2.0.0/`).

### PromptLoader (`loader.py`)

**Constructor:**
```python
PromptLoader(version=None)  # None → uses "current"
```
- `prompts_dir`: Always `ggdes/prompts/` (same directory as the loader script)
- `version`: Directory name under prompts_dir; resolves to `"current"` if `None`
- `_cache`: In-memory dict keyed by `agent_name` → prompts dict, avoids repeated file I/O

**Key Methods:**

| Method | Description |
|--------|-------------|
| `load_agent_prompts(agent_name)` | Loads all prompts for an agent from `{version}/{agent_name}.yaml`; caches result |
| `get_prompt(agent_name, prompt_key, **format_kwargs)` | Gets a single prompt string with optional `str.format()` substitution; safe `KeyError` suppression |
| `get_system_prompt(agent_name)` | Shorthand for `get_prompt(agent_name, "system")` |
| `list_available_agents()` | Lists all `.yaml` files in the version directory (excluding `__init__.yaml`) |
| `list_available_versions()` | Lists all subdirectories under prompts_dir (excluding `_`-prefixed) |

**Format kwargs behavior:**
- Uses `str.format(**format_kwargs)` with suppressed `KeyError` — missing keys are left as-is rather than crashing
- Enables partial substitution where some template variables are filled later downstream

**Convenience functions:**
- `get_default_loader()` — returns `PromptLoader()` using default version
- `get_prompt(agent_name, prompt_key, version, **format_kwargs)` — one-shot prompt retrieval

### Prompt Files (v1.0.0)

Each file contains YAML with prompt keys mapped to template strings. Common keys: `system` (always present), plus task-specific keys.

| Agent File | Prompts | Purpose |
|------------|---------|---------|
| `git_analyzer.yaml` | `system`, `analyze_diff`, `analyze_commit_message` | Analyze git diffs and commits; classify change type, intent, impact |
| `technical_author.yaml` | `system`, `write_technical_facts`, `describe_function` | Synthesize technical facts from analysis + AST; confidence scoring |
| `coordinator.yaml` | `system`, `create_document_plan`, `interactive_review` | Plan document structure, sections, diagrams per format |
| `output.yaml` | `system`, `markdown_system` | Write documentation in specified format |
| `change_filter.yaml` | `system`, `classify_changes` | Filter files by relevance to a feature description |
| `validation.yaml` | `system`, `validate_document` | Verify doc accuracy against source code; severity rubric |

**Anti-Hallucination Rules** — Every system prompt includes critical rules:
- Only reference code/diffs provided in context
- Never invent function names, signatures, or behavior
- Use provided tools to verify source code before describing
- Express uncertainty rather than guessing

## Flow

```
Agent needs a prompt
      │
      ▼
PromptLoader(version).get_prompt(agent_name, prompt_key, **kwargs)
      │
      ├── Check _cache[agent_name]
      │     │
      │     └── miss ──► read {version}/{agent_name}.yaml ──► yaml.safe_load()
      │                       │
      │                       └── store in _cache
      │
      ├── Extract prompts[prompt_key]
      │
      ├── Format with **kwargs (safe, suppressed KeyError)
      │
      └── Return formatted prompt string
```

## Integration

- **Consumed by:** All agent classes in `ggdes/agents/` — `GitAnalyzer`, `TechnicalAuthor`, `Coordinator`, `OutputAgent`, `ChangeFilterAgent`, `ValidationAgent`
- **Used with `SystemPromptBuilder`** from `ggdes/agents/skill_utils.py` — the loaded system prompt becomes the base prompt, wrapped with skill content above and user guidance below
- **Future versions:** add `v2.0.0/` directory with same file names but updated content; `PromptLoader(version="v2.0.0")` selects it
