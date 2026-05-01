# ggdes/config/

## Responsibility

Manage all configuration for GGDes: loading, validating, merging, and exposing typed settings. Every part of the system — pipeline, agents, parsers, output generators — reads its settings from the config hierarchy rooted at `GGDesConfig`.

## Files

| File | Role |
|------|------|
| `loader.py` | Pydantic models, YAML loading, CLI-override merging, path helpers |
| `__init__.py` | Re-exports public API (`GGDesConfig`, helpers, sub-configs) |

## Design

### Configuration Hierarchy

```
GGDesConfig                      # Root — all sub-configs as fields
├── ModelConfig                  # LLM provider, model name, API key, structured format
├── PathsConfig                  # knowledge_base, worktrees, output directories
├── FeaturesConfig               # Feature flags (semantic_diff, auto_cleanup, retention)
├── AnalysisConfig               # Git analysis tuning (chunking, token thresholds, thinking)
├── ParsingConfig                # AST parsing mode (full / incremental), reference depth
├── OutputConfig                 # Target formats (markdown, docx, pptx, pdf)
└── RepoConfig                   # Repository path (set from CLI or project file)
```

### Sub-config detail

**ModelConfig** (`loader.py:20`)
- `provider` — `"anthropic"`, `"openai"`, `"ollama"`, `"opencodezen"`, `"custom"`
- `model_name` — e.g. `"claude-3-5-sonnet-20241022"`
- `api_key` — supports `${ENV_VAR}` and `env:VAR` patterns via `resolve_api_key` validator
- `base_url` — optional custom endpoint (required for `custom` provider)
- `structured_format` — `StructuredOutputFormat` enum: `"auto"`, `"json"`, `"xml"`
- `enable_thinking` — reasoning mode for compatible models (default `True` for model calls, `False` for git analysis)

**PathsConfig** (`loader.py:50`)
- `knowledge_base` — default `"~/ggdes-kb"` (expanded via `expand_user` validator)
- `worktrees` — default `"~/ggdes-worktrees"`
- `output` — default `"~/ggdes-output"`

**FeaturesConfig** (`loader.py:64`)
- `semantic_diff` — enable semantic diff analysis (default `True`)
- `auto_cleanup` — auto-clean old worktrees (default `True`)
- `worktree_retention_days` — days before cleanup (default `7`)

**AnalysisConfig** (`loader.py:81`)
- `enable_chunked_diff` — split large diffs into chunks (default `True`)
- `chunk_mode` — `ChunkAnalysisMode.INDEPENDENT` (fast) or `ACCUMULATED` (coherent)
- `chunk_token_threshold` — max tokens per chunk before splitting (default `25000`)
- `max_diff_tokens` — absolute max before chunking (default `50000`)
- `enable_thinking` — thinking mode for git analysis LLM calls (default `False`; used as fallback on failure)

**ParsingConfig** (`loader.py:118`)
- `mode` — `ParsingMode.FULL` (all files) or `INCREMENTAL` (changed + referenced)
- `include_referenced` — in incremental mode, parse importers of changed files
- `max_referenced_depth` — how deep to follow references (0-3, default 1)

**OutputConfig** (`loader.py:137`)
- `default_format` — default output format (default `"markdown"`)
- `formats` — list of enabled formats (default `["markdown", "docx", "pptx", "pdf"]`)
- `max_section_tokens` — token budget per section prompt (default `28000`), for content chunking

**RepoConfig** (`loader.py:155`)
- `path` — repository path (`None` = current directory)

### 4-Tier Resolution

Implemented in `load_config()` (`loader.py:190`). Priority (highest first):

```
1. CLI arguments          — --repo, --provider, --model, --api-key
2. Project YAML           — ./ggdes.yaml (local to project)
3. User YAML              — ~/.ggdes/config.yaml (global per user)
4. Pydantic defaults      — hardcoded in model definitions
```

**Merge algorithm** (`merge_configs`, `loader.py:248`):
- Recursive deep merge on dict representations (`model_dump()`)
- Scalar values from higher-priority config replace lower-priority ones
- Nested sub-configs (e.g. `ModelConfig.api_key`) are merged key-by-key, not replaced whole
- `None` values in the override are skipped (they don't erase existing values)

### Environment Variable Resolution

Two patterns are supported. Only `${...}` is handled in the Pydantic validator:

| Pattern | Example | Handler |
|---------|---------|---------|
| `${VAR}` | `${ANTHROPIC_API_KEY}` | Resolved by `ModelConfig.resolve_api_key()` validator — strips `${}` and reads `os.getenv()` |
| `env:VAR` | `env:MY_KEY` | (Not in loader.py — handled at a higher level in CLI arg parsing) |

The `resolve_api_key` validator returns the original string if the env var is unset, allowing the provider to surface the error later with a clear message.

### Path Resolution Helpers

All in `loader.py:270-289`. Each takes `config` + `analysis_id` and returns a `Path`:

| Helper | Returns | Example |
|--------|---------|---------|
| `get_kb_path(config, id)` | `~/ggdes-kb/analyses/<id>/` | KB root for analysis artifacts |
| `get_worktrees_path(config, id)` | `~/ggdes-worktrees/<id>/` | Where git worktrees live |
| `get_output_path(config, id)` | `~/ggdes-output/<id>/` | Generated documents land here |

All expand `~` via `Path.expanduser()`.

## Flow

```
User / CLI
    │
    ├── CLI args (--repo, --provider, ...)
    │
    ▼
load_config()                        # entry point
    │
    ├── GGDesConfig()                # 1. Start with Pydantic defaults
    ├── ~/.ggdes/config.yaml         # 2. Merge global config
    ├── ./ggdes.yaml                 # 3. Merge project-local config
    ├── CLI overrides                # 4. Apply CLI args (highest priority)
    │
    ▼
(tuple) GGDesConfig + resolved Path  # returned to pipeline / CLI
```

Downstream consumers access config fields directly:
```python
config.model.provider          # "anthropic"
config.parsing.mode            # ParsingMode.FULL
config.features.semantic_diff  # True
```

## Integration

- **Imported by**: `pipeline.py` (orchestration), all agent modules (LLM settings), `kb/` (paths), `worktree/` (retention), `cli/` (defaults)
- **Saves to**: `./ggdes.yaml` via `GGDesConfig.save()` — writes `model_dump()` as pretty YAML
- **Exposed via**: `ggdes/config/__init__.py` re-exports all public types and helpers
