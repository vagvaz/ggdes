# GGDes Codebase Comprehensive Audit

## Executive Summary

GGDes (Git-based Design Documentation Generator) is a sophisticated multi-agent system that analyzes git commits and generates comprehensive documentation in multiple formats (Markdown, DOCX, PDF, PPTX). The system uses a staged pipeline architecture with LLM-powered agents, AST parsing, semantic diff analysis, and PlantUML diagram generation.

---

## 1. Directory Structure

```
/home/vagvaz/Projects/ai/ggdes/
├── main.py                          # Entry point
├── pyproject.toml                   # Project configuration (uv)
├── ggdes.yaml                       # Default configuration
├── AGENTS.md                        # Development documentation
├── README.md                        # User documentation
├── Makefile                         # Build automation
├── tests/                           # Test suite
│   ├── test_ast_parser.py
│   ├── test_comparison.py
│   ├── test_ggdes.py
│   ├── test_pipeline.py
│   ├── test_semantic_diff.py
│   ├── test_validation.py
│   └── ...
└── ggdes/                           # Main package
    ├── __init__.py
    ├── logging_config.py
    ├── pipeline.py                  # Pipeline orchestrator
    ├── comparison.py                # Analysis comparison
    ├── semantic_diff.py             # Semantic diff analysis
    ├── agents/                      # Deep analysis agents
    │   ├── __init__.py
    │   ├── git_analyzer.py          # Git analysis agent
    │   ├── technical_author.py      # Technical fact synthesis
    │   ├── coordinator.py           # Document planning
    │   ├── change_filter.py         # Semantic change filtering
    │   ├── skill_utils.py           # Skill loading utilities
    │   └── output_agents/           # Document generation agents
    │       ├── __init__.py
    │       ├── base.py              # Base output agent class
    │       ├── markdown_agent.py    # Markdown generator
    │       ├── docx_agent.py        # Word document generator
    │       ├── pdf_agent.py         # PDF generator
    │       └── pptx_agent.py        # PowerPoint generator
    ├── cli/                         # CLI implementation
    │   ├── __init__.py
    │   ├── utils.py                 # CLI utilities
    │   └── commands/
    │       ├── __init__.py
    │       ├── analyze.py           # analyze command
    │       ├── compare.py           # compare command
    │       ├── config_cmd.py        # config command
    │       ├── doctor.py            # doctor command
    │       ├── export_cmd.py        # export command
    │       ├── manage.py            # manage command
    │       ├── resume.py            # resume command
    │       ├── server.py            # web/tui/debug commands
    │       └── status.py            # status command
    ├── config/                      # Configuration system
    │   ├── __init__.py
    │   └── loader.py                # Config loading with overrides
    ├── diagrams/                    # Diagram generation
    │   ├── __init__.py              # PlantUML generator
    │   ├── cache.py                 # Diagram caching
    │   └── plantuml.jar             # PlantUML executable
    ├── kb/                          # Knowledge base
    │   ├── __init__.py
    │   └── manager.py               # KB management
    ├── llm/                         # LLM provider system
    │   ├── __init__.py
    │   ├── factory.py               # Provider factory
    │   └── conversation.py          # Conversation context
    ├── parsing/                     # AST parsing
    │   ├── __init__.py
    │   └── ast_parser.py            # tree-sitter parser
    ├── prompts/                     # Prompt templates
    │   ├── __init__.py
    │   ├── loader.py                # Prompt loading
    │   └── v1.0.0/                  # Prompt version directory
    │       ├── git_analyzer/
    │       ├── technical_author/
    │       ├── coordinator/
    │       └── output/
    ├── rendering/                   # Markdown rendering
    │   ├── __init__.py
    │   └── markdown_to_png.py       # Playwright renderer
    ├── review/                      # Interactive review system
    │   ├── __init__.py
    │   ├── review.py                # Review data structures
    │   └── reviewer.py              # Review UI
    ├── schemas/                     # Pydantic models
    │   ├── __init__.py
    │   ├── models.py                # Core data models
    │   └── enums.py                 # Enumerations
    ├── skills/                      # Skill documentation
    │   ├── python-expert/
    │   ├── cpp-expert/
    │   ├── doc-coauthoring/
    │   ├── markdown/
    │   ├── docx/
    │   ├── pdf/
    │   └── pptx/
    ├── tools/                       # LLM tool system
    │   ├── __init__.py
    │   ├── definitions.py           # Tool schemas
    │   ├── executor.py              # Tool execution
    │   └── chat_with_tools.py       # Tool-augmented chat
    ├── tui/                         # Terminal UI
    │   ├── __init__.py
    │   ├── app.py                   # Main TUI application
    │   └── debug_view.py            # Debug view
    ├── validation/                  # Validation system
    │   ├── __init__.py
    │   ├── validators.py            # AST/input validators
    │   └── code_references.py       # Code reference validator
    ├── web/                         # Web interface
    │   └── __init__.py              # FastAPI application
    ├── worktree/                    # Worktree management
    │   ├── __init__.py
    │   └── manager.py               # Worktree manager
    └── utils/
        ├── __init__.py
        └── lock.py                  # Analysis locking
```

---

## 2. Pipeline Stages (Core Architecture)

### Stage 1: worktree_setup
**File:** `ggdes/pipeline.py:356-427`
**Purpose:** Create isolated git worktrees for base and head commits
**Key Methods:**
- `_run_worktree_setup()` - Parses commit range, creates worktree pair
- Uses `WorktreeManager.create_for_analysis()`
**Output:** `metadata.worktrees` with base/head paths

### Stage 2: git_analysis
**File:** `ggdes/pipeline.py:429-528`
**Purpose:** Analyze git commits and extract change summaries
**Key Components:**
- `GitAnalyzer` agent (`ggdes/agents/git_analyzer.py`)
- Multi-turn LLM conversation with chunking support
- Code reference validation
**Output:** `kb/analyses/{id}/git_analysis/summary.json`
**Key Classes:**
- `ChangeSummary` - Structured change information
- `FileChange` - Per-file change details

### Stage 3: change_filter (Optional)
**File:** `ggdes/pipeline.py:530-589`
**Purpose:** Filter changes by semantic relevance to feature
**Key Components:**
- `ChangeFilter` agent (`ggdes/agents/change_filter.py`)
- Uses feature description from metadata
**Output:** Filtered `summary.json` (overwrites original)

### Stage 4: ast_parsing_base
**File:** `ggdes/pipeline.py:591-690`
**Purpose:** Parse AST for base commit worktree
**Key Components:**
- `ASTParser` using tree-sitter (`ggdes/parsing/ast_parser.py`)
- Supports Python and C++
- Incremental mode available
**Output:** `kb/analyses/{id}/ast_base/*.json`

### Stage 5: ast_parsing_head
**File:** `ggdes/pipeline.py:692-720`
**Purpose:** Parse AST for head commit worktree
**Output:** `kb/analyses/{id}/ast_head/*.json`

### Stage 6: semantic_diff (Optional)
**File:** `ggdes/pipeline.py:948-1028`
**Purpose:** Analyze semantic code changes beyond text diffs
**Key Components:**
- `SemanticDiffAnalyzer` (`ggdes/semantic_diff.py`)
- Detects: API changes, behavior changes, refactoring, documentation changes
**Output:** `kb/analyses/{id}/semantic_diff/result.json`
**Change Types:**
- `SemanticChangeType.API_ADDED/REMOVED/MODIFIED`
- `SemanticChangeType.BEHAVIOR_CHANGE`
- `SemanticChangeType.REFACTORING`
- `SemanticChangeType.DOCUMENTATION_ADDED`

### Stage 7: technical_author
**File:** `ggdes/pipeline.py:821-898`
**Purpose:** Synthesize technical facts from analysis data
**Key Components:**
- `TechnicalAuthor` agent (`ggdes/agents/technical_author.py`)
- Tool-augmented LLM calls (anti-hallucination)
- Parallel analysis turns (API, behavioral, architecture)
**Output:** `kb/analyses/{id}/technical_facts/facts.json`
**Key Features:**
- Source code diff computation
- Usage example extraction
- Tool-based validation

### Stage 8: coordinator_plan
**File:** `ggdes/pipeline.py:899-946`
**Purpose:** Create document generation plans
**Key Components:**
- `Coordinator` agent (`ggdes/agents/coordinator.py`)
- Interactive user input (optional)
- Format-specific planning
**Output:** `kb/analyses/{id}/plans/plan_{format}.json`
**Plans Include:**
- `DocumentPlan` with sections and diagrams
- `SectionPlan` with technical facts and code references
- `DiagramSpec` for PlantUML generation

### Stage 9: output_generation
**File:** `ggdes/pipeline.py:1030-1134`
**Purpose:** Generate documents in target formats
**Key Components:**
- `MarkdownAgent`, `DocxAgent`, `PdfAgent`, `PptxAgent`
- Parallel generation for non-markdown formats
- Diagram integration
**Output:** Documents in `ggdes-output/{analysis_id}/`

---

## 3. CLI Commands

**File:** `ggdes/cli/__init__.py`, `ggdes/cli/commands/*.py`

| Command | File | Description |
|---------|------|-------------|
| `analyze` | `commands/analyze.py:21-191` | Start new analysis with feature name and commit range |
| `resume` | `commands/resume.py` | Resume incomplete analysis |
| `status` | `commands/status.py` | Show all analyses with progress |
| `compare` | `commands/compare.py` | Compare two analyses side-by-side |
| `cleanup` | `commands/manage.py` | Clean up worktrees |
| `export` | `commands/export_cmd.py` | Export analysis to JSON/ZIP |
| `archive` | `commands/manage.py` | Archive old analyses |
| `config` | `commands/config_cmd.py` | View/edit configuration |
| `doctor` | `commands/doctor.py` | System health checks |
| `tui` | `commands/server.py:13-18` | Launch terminal UI |
| `web` | `commands/server.py:196-230` | Start web interface |
| `debug` | `commands/server.py:31-194` | Launch debug TUI for conversations |

**Key CLI Options:**
- `--feature` - Analysis name
- `--commits` - Git commit range
- `--focus` - Specific commits to focus on
- `--formats` - Output formats (markdown,docx,pdf,pptx)
- `--storage` - Conversation storage (raw, summary, none)
- `--semantic-diff` / `--no-semantic-diff` - Enable/disable semantic analysis
- `--no-filter` - Disable semantic change filtering
- `--interactive` - Enable stage-by-stage review
- `--context-file` - YAML/JSON file with user context
- `--render-png` - Render diagrams to PNG images

---

## 4. LLM Provider System

**File:** `ggdes/llm/factory.py:1-1140`

### Supported Providers
| Provider | Class | Default Format | Key Features |
|----------|-------|----------------|--------------|
| `anthropic` | `AnthropicProvider:718-829` | XML | Native XML support |
| `openai` | `OpenAIProvider:896-912` | JSON | Custom base_url support |
| `ollama` | `OllamaProvider:914-929` | JSON | Local models |
| `opencodezen` | `OpencodeZenProvider:981-1024` | JSON | Multi-model gateway |
| `custom` | `CustomOpenAIProvider:931-978` | XML | Any OpenAI-compatible API |

### Retry Logic
**Decorator:** `@retry_on_failure:80-185`
- Exponential backoff with jitter
- Configurable max retries (default: 3)
- Initial delay: 1 second, max delay: 60 seconds
- Logs all retry attempts

### Structured Output
**Method:** `generate_structured:599-716`
- Supports JSON and XML formats
- Auto-correction on parse failures (up to 3 retries)
- Temperature increases on retries for variety
- Pydantic model validation

### API Key Resolution
**Function:** `resolve_api_key:43-78`
- Supports `${VAR}` pattern
- Supports `env:VAR` pattern
- Provider-specific fallbacks

---

## 5. Diagram Generation System

**File:** `ggdes/diagrams/__init__.py:1-523`

### PlantUMLGenerator Class
**Methods:**
- `generate:54-151` - Generate diagram from PlantUML code
- `validate:153-189` - Validate PlantUML syntax
- `validate_and_repair:191-230` - Auto-repair common errors
- `generate_from_file:153-175` - Generate from .puml file

### Diagram Types
| Function | Type | Use Case |
|----------|------|----------|
| `generate_architecture_diagram:312-359` | Architecture | System components |
| `generate_flow_diagram:361-415` | Flow/Process | Workflows |
| `generate_class_diagram:417-481` | Class | OOP hierarchies |
| `generate_sequence_diagram:483-523` | Sequence | Object interactions |

### Auto-Generation
**Location:** `agents/output_agents/base.py`
- `_generate_diagrams_for_facts()` - Creates diagrams from technical facts
- Supports: architecture, flow, class diagrams
- Caches generated diagrams

---

## 6. Output Agents

**Base Class:** `ggdes/agents/output_agents/base.py`

### MarkdownAgent
**File:** `ggdes/agents/output_agents/markdown_agent.py:1-538`
- Generates markdown with YAML front matter
- Integrates PlantUML diagrams (both images and code blocks)
- Includes executive summary and TOC
- Supports PNG rendering via Playwright

### DocxAgent
**File:** `ggdes/agents/output_agents/docx_agent.py`
- Uses docx-js (Node.js) or pandoc fallback
- Embeds diagrams as images
- Professional Word formatting

### PdfAgent
**File:** `ggdes/agents/output_agents/pdf_agent.py`
- Uses reportlab library
- High-resolution diagrams (300 DPI)
- Bookmarks and page numbers

### PptxAgent
**File:** `ggdes/agents/output_agents/pptx_agent.py`
- Uses pptxgenjs (Node.js) or pandoc fallback
- 6x6 rule enforcement (6 bullets, 6 words each)
- Visual elements on every slide

### Skill Loading
**File:** `ggdes/agents/skill_utils.py`
- `load_skill()` - Loads skill documentation from `ggdes/skills/`
- `SystemPromptBuilder` - Constructs layered system prompts
- Skills loaded: python-expert, cpp-expert, doc-coauthoring

---

## 7. Validation System

**File:** `ggdes/validation/`

### CodeReferenceValidator
**File:** `ggdes/validation/code_references.py`
- Extracts code references from LLM output
- Validates against git diff and AST data
- Auto-correction flow with LLM
- Prevents hallucinated function/file names

### ASTValidator
**File:** `ggdes/validation/validators.py`
- Validates technical facts against AST elements
- Checks function/class existence
- Reports errors and warnings

### InputValidator
**File:** `ggdes/validation/validators.py`
- Validates commit ranges
- Checks repository state

---

## 8. Comparison System

**File:** `ggdes/comparison.py:1-667`

### AnalysisComparator Class
**Methods:**
- `compare:60-113` - Compare two analyses
- `_compare_commits:269-313` - Commit range differences
- `_compare_file_changes:315-360` - File change metrics
- `_compare_facts:362-406` - Technical facts differences
- `_compare_breaking_changes:408-440` - Breaking changes
- `_compare_semantic_diff:176-267` - Semantic analysis differences
- `_compute_similarity:442-467` - Similarity score (0-1)

### Output
- Rich table display
- JSON export via `export_comparison:601-667`
- Includes semantic diff comparison

---

## 9. Worktree Management

**File:** `ggdes/worktree/manager.py:1-381`

### WorktreeManager Class
**Methods:**
- `create_for_analysis:40-171` - Create base/head worktrees
- `get_existing:173-197` - Find existing worktrees
- `cleanup:198-218` - Remove worktrees
- `cleanup_old_worktrees:220-273` - Age-based cleanup
- `list_all:275-318` - List all worktree pairs

### WorktreePair Dataclass
- `base` - Base commit worktree path
- `head` - Head commit worktree path
- `cleanup()` - Remove both worktrees

### Retention Policy
- Configurable via `worktree_retention_days` (default: 7)
- Accessible via web UI and CLI

---

## 10. Web Interface

**File:** `ggdes/web/__init__.py` (FastAPI application)

### Features
- Real-time updates via WebSocket
- Analysis listing with progress bars
- One-click resume
- Document download
- Worktree preview and cleanup
- System statistics dashboard

### Dependencies
- `fastapi>=0.115.0`
- `uvicorn[standard]>=0.32.0`
- `websockets>=13.0`

### Installation
```bash
uv pip install -e ".[web]"
```

---

## 11. TUI Components

**File:** `ggdes/tui/app.py:1-1221`

### Main Classes
- `GGDesTUI` - Main application
- `AnalysisDetailView` - Analysis details with progress
- `WorktreeView` - Worktree management
- `GitLogView` - Commit browser with selection
- `NewAnalysisDialog` - Create analysis dialog
- `ConfirmDialog` - Confirmation dialogs

### Features
- Tabbed interface (Analyses, Worktrees, Git Log, Help)
- Resume analysis with one click
- Delete with confirmation
- Git commit selection for new analyses
- Stage status icons (○ pending, ◐ in progress, ✓ completed, ✗ failed)

### Keyboard Shortcuts
- `q` - Quit
- `r` - Refresh
- `a` - New analysis
- `s` - Set start commit
- `e` - Set end commit
- `f` - Toggle focus commit
- `c` - Clear selection

---

## 12. Import/Export/Archive System

### Export
**Command:** `ggdes export`
**File:** `ggdes/cli/commands/export_cmd.py`
- Export to JSON or ZIP
- Option to include diagrams
- Preserves all analysis data

### Archive
**Command:** `ggdes archive`
- Archives old analyses
- Configurable retention period
- Data preserved for future reference

---

## 13. Doctor Command

**File:** `ggdes/cli/commands/doctor.py`

### Checks Performed
- Repository configuration
- LLM provider connectivity
- PlantUML availability
- Knowledge base integrity
- Worktree state

### Auto-Fix
- `--fix` flag enables automatic repairs
- Fixes common configuration issues

---

## 14. Configuration System

**File:** `ggdes/config/loader.py:1-235`

### Configuration Classes
- `GGDesConfig` - Main configuration
- `ModelConfig` - LLM settings
- `PathsConfig` - Directory paths
- `FeaturesConfig` - Feature flags
- `ParsingConfig` - AST parsing settings
- `OutputConfig` - Output format settings

### Resolution Order
1. CLI arguments (highest priority)
2. Project-local config (`./ggdes.yaml`)
3. User global config (`~/.ggdes/config.yaml`)
4. Defaults

### Key Configuration Options
```yaml
model:
  provider: "anthropic"  # or openai, ollama, opencodezen, custom
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}"
  base_url: "https://custom-endpoint.com/v1"  # Optional
  structured_format: "auto"  # auto, json, xml

paths:
  knowledge_base: "~/ggdes-kb"
  worktrees: "~/ggdes-worktrees"
  output: "~/ggdes-output"

features:
  dual_state_analysis: false
  auto_cleanup: true
  worktree_retention_days: 7

parsing:
  mode: "full"  # or "incremental"
  include_referenced: true
  max_referenced_depth: 1

output:
  default_format: "markdown"
  formats: ["markdown", "docx", "pptx", "pdf"]
```

---

## 15. Tool System (Anti-Hallucination)

**File:** `ggdes/tools/`

### Available Tools
**File:** `ggdes/tools/definitions.py:1-350`

| Tool | Purpose |
|------|---------|
| `get_changed_files` | List files in commit range |
| `read_file` | Read source file contents |
| `search_code` | Regex search in codebase |
| `validate_reference` | Verify code element exists |
| `get_ast_elements` | Get AST elements for file |
| `get_element_source` | Get actual source code for element |

### Tool Executor
**File:** `ggdes/tools/executor.py`
- Executes tool calls from LLM
- Caches results for efficiency
- Provides grounded codebase access

### Chat with Tools
**File:** `ggdes/tools/chat_with_tools.py`
- Multi-turn tool-augmented conversation
- LLM requests tools, executor runs them
- Results fed back to LLM

---

## 16. Knowledge Base Structure

**File:** `ggdes/kb/manager.py:1-425`

### Directory Layout
```
{knowledge_base}/analyses/{analysis_id}/
├── metadata.yaml              # Analysis metadata
├── git_analysis/
│   └── summary.json           # Change summary
├── ast_base/                  # Base AST elements
│   └── *.json
├── ast_head/                  # Head AST elements
│   └── *.json
├── semantic_diff/
│   └── result.json            # Semantic analysis
├── technical_facts/
│   └── facts.json             # Synthesized facts
├── plans/
│   ├── index.json
│   └── plan_{format}.json     # Document plans
├── diagrams/                  # Generated diagrams
│   └── *.png
└── conversations/             # LLM conversations
    ├── git_analyzer/
    ├── technical_author/
    ├── coordinator/
    └── markdown_agent/
```

### AnalysisMetadata Fields
- `id`, `name`, `repo_path`, `commit_range`
- `focus_commits` - Non-contiguous analysis support
- `target_formats` - Selected output formats
- `storage_policy` - Conversation storage level
- `user_context` - User-provided context
- `feature_description` - For semantic filtering
- `stages` - Stage status tracking
- `documents` - Generated document tracking

---

## 17. Schema Models

**File:** `ggdes/schemas/models.py:1-249`

### Core Models
- `ChangeSummary` - Git change summary
- `FileChange` - Per-file change info
- `CodeElement` - AST-extracted element
- `TechnicalFact` - Synthesized technical fact
- `DocumentPlan` - Document generation plan
- `SectionPlan` - Document section plan
- `DiagramSpec` - Diagram specification

### Enums
- `ChangeType` - feature, bugfix, refactor, docs, test, chore, performance, security
- `ImpactLevel` - none, low, medium, high, critical
- `CodeElementType` - function, method, class, variable, constant, import, decorator
- `StoragePolicy` - raw, summary, none

---

## 18. Prompt System

**File:** `ggdes/prompts/loader.py`

### Structure
```
ggdes/prompts/v1.0.0/
├── git_analyzer/
│   └── system.md
├── technical_author/
│   └── system.md
├── coordinator/
│   └── system.md
└── output/
    ├── markdown_system.md
    └── ...
```

### Loading
- `get_prompt(agent, prompt_type)` - Load prompt by agent and type
- Versioned prompts (v1.0.0 directory)
- Supports prompt evolution without breaking changes

---

## 19. Skill System

**Location:** `ggdes/skills/`

### Available Skills
- `python-expert` - Python language expertise
- `cpp-expert` - C++ language expertise
- `doc-coauthoring` - Documentation writing expertise
- `markdown` - Markdown formatting
- `docx` - Word document patterns
- `pdf` - PDF generation patterns
- `pptx` - PowerPoint presentation patterns

### Loading
**File:** `ggdes/agents/skill_utils.py`
- `load_skill(skill_name, repo_path)` - Load skill from file
- Skills injected into system prompts
- Provides domain-specific expertise

---

## 20. Key Design Patterns

### Anti-Hallucination Measures
1. **Tool-augmented LLM calls** - `get_element_source` tool
2. **Code reference validation** - `CodeReferenceValidator`
3. **Source code injection** - Actual code in prompts
4. **Before/after diffs** - Computed source diffs
5. **Usage examples** - Real call sites from codebase

### Parallel Execution
- AST parsing (base + head can run in parallel)
- Semantic diff (can run with AST parsing)
- Output generation (docx, pdf, pptx in parallel)

### Conversation Storage
- **raw** - Store all messages
- **summary** - Store system prompt + summary only
- **none** - Don't store conversations

### Interactive Review
- Stage-by-stage review mode
- Feedback collection for regeneration
- Skip/accept/regenerate decisions

---

## 21. File Reference Summary

| Component | Primary Files | Line Count |
|-----------|--------------|------------|
| Pipeline | `pipeline.py` | 1134 |
| LLM Factory | `llm/factory.py` | 1140 |
| TUI | `tui/app.py` | 1221 |
| Technical Author | `agents/technical_author.py` | 1488 |
| Git Analyzer | `agents/git_analyzer.py` | 875 |
| Semantic Diff | `semantic_diff.py` | 983 |
| KB Manager | `kb/manager.py` | 425 |
| AST Parser | `parsing/ast_parser.py` | 756 |
| Coordinator | `agents/coordinator.py` | 670 |
| Comparison | `comparison.py` | 667 |
| Worktree Manager | `worktree/manager.py` | 381 |
| Diagrams | `diagrams/__init__.py` | 523 |
| Markdown Agent | `agents/output_agents/markdown_agent.py` | 538 |
| Tools | `tools/definitions.py` | 350 |
| Config | `config/loader.py` | 235 |

---

## 22. Integration Points

### External Dependencies
- **tree-sitter** - AST parsing (Python, C++)
- **PlantUML** - Diagram generation (Java required)
- **Node.js** - docx-js, pptxgenjs (optional, pandoc fallback)
- **Playwright** - Markdown to PNG rendering (optional)
- **reportlab** - PDF generation
- **textual** - TUI framework
- **fastapi** - Web interface
- **anthropic/openai** - LLM providers

### Git Integration
- Worktrees for isolation
- Commit range parsing
- Diff extraction
- Log browsing

---

## 23. Detailed Stage Analysis

### Stage 1: worktree_setup (pipeline.py:356-426, worktree/manager.py:381 lines)
- Creates isolated git worktrees at ~/ggdes-worktrees/{analysis_id}/base and head
- Parses commit_range "base..head" → calls WorktreeManager.create_for_analysis()
- Runs `git worktree add <path> <commit>` for both commits
- Verifies worktrees exist and have content, stores resolved paths in metadata.worktrees
- Supports cleanup_old_worktrees() with configurable retention (default 7 days)

### Stage 2: git_analysis (pipeline.py:428-492, agents/git_analyzer.py:875 lines)
- GitAnalyzer gathers: git diff, commit log, changed files with stats
- Two modes: single-pass (diff ≤50K tokens) or chunked (splits by file boundaries at 25K tokens with 50-line overlap)
- LLM returns structured ChangeSummary via Pydantic model (change_type, description, intent, impact, impact_level, breaking_changes)
- Anti-hallucination: CodeReferenceValidator validates all file/function references against actual diff, auto-corrects (up to 2 attempts)
- Language expert skill auto-detected and loaded
- Conversation saved to kb/analyses/{id}/conversations/git_analyzer/

### Stage 3: change_filter (pipeline.py:494-590, agents/change_filter.py:387 lines)
- Filters changes by semantic relevance to feature description (--feature flag)
- Parses diff into hunks with line numbers, groups by file
- LLM classifies each file: is_relevant, relevant_line_ranges, reason
- Safety valve: never filters out ALL files (fallback keeps everything)
- Overwrites summary.json, backs up as summary_unfiltered.json, sets is_filtered=True
- Skipped if --no-filter or no feature description

### Stages 4&5: ast_parsing_base/head (pipeline.py:592-719, parsing/ast_parser.py:756 lines)
- Shared _run_ast_parsing(variant) for "base" and "head" worktrees
- ASTParser uses tree-sitter for Python (.py) and C++ (.cpp,.cc,.cxx,.hpp,.h)
- Extracts: classes (docstrings, decorators, child methods), functions (signatures, docstrings, decorators, parent)
- Two modes: incremental (only changed files + referenced files via import/include search) or full (scan entire worktree)
- Output: kb/analyses/{id}/ast_base/*.json and ast_head/*.json with CodeElement dicts

### Stage 6: semantic_diff (pipeline.py:946-1026, semantic_diff.py:983 lines)
- Rule-based (not LLM) semantic change detection using Python's ast module
- 4 detectors per file: signature changes (added/removed/modified functions), documentation changes (docstring count), control flow changes (if/for/while count, threshold ±2), error handling changes (try/except additions/removals)
- Each SemanticChange has: change_type (25 enum values), description, confidence (0-1), impact_score (0-1), before/after snippets
- Auto-categorizes into: breaking_changes, behavioral_changes, refactoring_changes, documentation_changes, test_changes, performance_changes, dependency_changes
- Output: kb/analyses/{id}/semantic_diff/result.json with summary stats

### Stage 7: technical_author (agents/technical_author.py, 1488 lines)
- Synthesizes git analysis, AST data, and semantic diffs into structured TechnicalFact objects
- **Anti-Hallucination Architecture (6 layers):**
  1. Source Code Injection: _build_source_code_context() provides real source (50 lines max, 15 elements)
  2. Source Code Diffs: _compute_source_diffs() computes unified diffs between base/head (20 elements max)
  3. Tool-Augmented LLM: chat_with_tools() + get_element_source tool for runtime verification
  4. Post-Validation: _validate_facts_with_tools() validates every source_file/source_element reference, auto-corrects
  5. Semantic Diff Integration: _load_semantic_diff() injects rule-based detections as ground truth
  6. Usage Examples: _find_usages_in_worktree() finds real call sites in src/lib/include/core dirs
- **Three Analysis Turns (parallel via asyncio.gather):**
  - API Changes: _analyze_api_changes() - new/deleted/modified functions & methods
  - Behavioral Changes: _analyze_behavioral_changes() - logic/algorithm/control flow changes
  - Architecture Changes: _analyze_architecture_changes() - dependencies, class hierarchies (rule-based)
- Each turn gets separate ConversationContext to avoid cross-contamination
- Data Flow: Load git summary → Load AST base+head → Filter to changed files → Compute source diffs → Cache in tool executor → Load semantic diff → Run 3 turns → Merge facts → Validate → Enrich (code_snippets, before_after_code, usages) → Save to kb/technical_facts/facts.json

### Stage 8: coordinator_plan (agents/coordinator.py, 670 lines)
- Transforms technical facts into DocumentPlan objects (one per target format) defining sections, diagrams, code references
- Planning-only agent (no tool-augmented LLM). Reads facts + semantic diffs, asks LLM for JSON document plan
- Data Flow: Load facts → Load semantic diff → Categorize facts → (Interactive: gather user prefs) → For each format (parallel): create fresh ConversationContext → build planning prompt → LLM generates JSON (temp=0.4) → Parse → DocumentPlan with SectionPlan[] + DiagramSpec[] → Enrich sections with code from facts → Save plans
- Interactive vs Auto: Interactive mode asks 5-7 Rich prompts (audience, focus, detail, diagrams, API ref, migration guide). Auto mode uses CLI user_context
- DocumentPlan Schema: title, format, audience, sections[] (SectionPlan with title, description, technical_facts[], code_references[], diagrams[], source_code{}, before_after_code{}, usages{}), diagrams[] (DiagramSpec with type/title/description/elements)
- Parallel Planning: Separate ConversationContext per format, runs via asyncio.gather(). Fallback: minimal default plan if JSON parsing fails

### Stage 9: output_generation (pipeline.py:1030-1134, agents/output_agents/)
- Pipeline Orchestration: Reads target_formats from metadata. Generates markdown first (sequential), then other formats (docx/pdf/pptx) in parallel via ThreadPoolExecutor. Each format agent instantiated with (repo_path, config, analysis_id). Errors caught per-format, doesn't block others. Returns True if any documents generated.
- **OutputAgent Base (base.py, 695 lines):** Abstract base with shared infrastructure:
  - output_dir property → ~/ggdes-output/<analysis_id>/
  - _load_user_context() → from plan or metadata fallback
  - _load_validated_elements() → AST head element names for validation
  - _load_technical_facts() → cache facts from technical_facts/*.json
  - _load_ast_classes() → class metadata with methods/attributes/bases
  - _load_changed_classes() → from semantic diff
  - _validate_element_name() → prefix/case-insensitive match against AST
  - _load_skill() → loads skill doc from ggdes/skills/
  - _generate_diagrams_for_facts() → auto-generates architecture/flow/class diagrams from facts with caching
  - _generate_architecture_diagram() → extracts components from architecture+API facts, creates PlantUML with relationships
  - _generate_flow_diagram() → builds process steps from behavior/data_flow facts with step types (process/decision/database/boundary)
  - _generate_class_diagram() → extracts class hierarchies from AST
- **MarkdownAgent (markdown_agent.py, 538 lines):** LLM-powered generation:
  - _init_conversation() → loads markdown_system prompt + user context
  - generate() → loads plan, generates each section via LLM (asyncio.run), auto-generates diagrams from facts, renders PNGs via Playwright (optional)
  - _generate_section() → LLM call with facts, source code, before/after diffs, usage examples injected into prompt. Temp=0.4, max_tokens=4096
  - _generate_plantuml() → generates PlantUML for architecture/flow/sequence/class diagrams from DiagramSpec
  - _build_markdown() → assembles YAML front matter, title, metadata, executive summary, TOC, sections content, diagrams (images + PlantUML code blocks), footer
  - _save_markdown() → {analysis_id}-{safe_title}.md
- **DocxAgent (docx_agent.py, 421 lines):** Uses docx-js (Node.js) or pandoc fallback. Loads docx skill. Reads markdown as source content. Generates diagrams via base class. Converts to .docx.
- **PdfAgent (pdf_agent.py, 346 lines):** Uses reportlab library. Loads pdf skill. Reads markdown as source. Generates diagrams. Creates PDF with proper styling.
- **PptxAgent (pptx_agent.py, 417 lines):** Uses pptxgenjs (Node.js) or pandoc fallback. Loads pptx skill. Parses markdown into slides. Enforces 6x6 rule (6 bullets, 6 words). Generates diagrams. Creates .pptx.

---

This audit provides a complete map of the GGDes codebase architecture, with all major components, their locations, and how they interconnect. The system is well-organized with clear separation of concerns between agents, pipeline orchestration, output generation, and supporting infrastructure.
