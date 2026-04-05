# GGDes: Git-based Design Documentation Generator

GGDes is a multi-agent system that automatically generates design documentation from git commits. It uses AI agents to analyze code changes, extract technical facts, and produce comprehensive documentation in multiple formats (Markdown, Word, PowerPoint, PDF).

## Features

- **Multi-Agent Pipeline**: Git Analysis → AST Parsing → Technical Author → Coordinator → Output Generation
- **Worktree-Based Analysis**: Isolated git worktrees for clean, non-destructive analysis
- **Multi-Turn LLM Conversations**: Context-aware agent interactions with conversation persistence
- **Chunking for Large Diffs**: Automatically handles large code changes in manageable pieces
- **Multiple Output Formats**: Markdown (native), Word, PowerPoint, PDF
- **Interactive & Auto Modes**: Full automation or user-guided planning
- **State Persistence**: Resume interrupted analyses from any stage
- **TUI**: Rich terminal interface for visualizing and managing analyses

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd ggdes

# Install dependencies with uv
uv sync

# Or with pip
pip install -e ".[dev]"
```

## Quick Start

### 1. Configure

Create `ggdes.yaml` in your project root:

```yaml
model:
  provider: "anthropic"  # or "openai", "ollama", "opencodezen"
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}"  # or env:ANTHROPIC_API_KEY

paths:
  knowledge_base: ".ggdes/kb"
  worktrees: ".ggdes/worktrees"

output:
  default_format: "markdown"
  formats: ["markdown", "docx"]
```

### 2. Run Analysis

```bash
# Start a new analysis
uv run ggdes analyze --feature "user-authentication" --commits "HEAD~5..HEAD"

# Or run everything automatically
uv run ggdes analyze --feature "api-refactor" --commits "abc123..def456" --auto
```

### 3. Resume/Continue

```bash
# Resume from where it left off
uv run ggdes resume user-authentication-20240115-123456

# Or run specific stage
uv run ggdes resume user-authentication-20240115-123456 --stage technical_author
```

### 4. Check Status

```bash
# List all analyses
uv run ggdes status

# Show specific analysis
uv run ggdes status user-authentication-20240115-123456
```

### 5. Launch TUI

```bash
# Interactive terminal UI
uv run ggdes tui
```

## Pipeline Stages

| Stage | Description | Output |
|-------|-------------|--------|
| **worktree_setup** | Create BASE/HEAD worktrees | Isolated git worktrees |
| **git_analysis** | Analyze diffs with LLM | ChangeSummary with intent/impact |
| **ast_parsing_base** | Parse AST of base commit | CodeElement[] |
| **ast_parsing_head** | Parse AST of head commit | CodeElement[] |
| **technical_author** | Synthesize technical facts | TechnicalFact[] |
| **coordinator_plan** | Create document plans | DocumentPlan[] |
| **output_generation** | Generate documents | .md, .docx, .pptx, .pdf |

## Configuration

### Model Providers

**Anthropic (Claude)**
```yaml
model:
  provider: "anthropic"
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}"
```

**OpenAI (GPT)**
```yaml
model:
  provider: "openai"
  model_name: "gpt-4"
  api_key: "${OPENAI_API_KEY}"
```

**Ollama (Local)**
```yaml
model:
  provider: "ollama"
  model_name: "llama3.2"
  api_key: "ollama"  # Not used but required
```

**OpencodeZen (Gateway)**
```yaml
model:
  provider: "opencodezen"
  model_name: "claude-opus-4"
  api_key: "${OPENCODEZEN_API_KEY}"
```

### API Key Resolution

GGDes supports flexible API key specification:

- Direct: `api_key: "sk-xxx"`
- Environment variable: `api_key: "${OPENAI_API_KEY}"`
- Prefix syntax: `api_key: "env:OPENAI_API_KEY"`

### Configuration Locations

Configuration is loaded in this order (later overrides earlier):

1. Defaults
2. `~/.ggdes/config.yaml` (global user config)
3. `./ggdes.yaml` (project-local config)
4. CLI flags (`--provider`, `--model`, `--api-key`)

## Architecture

```
┌─ AnalysisPipeline ──────────────────────────────┐
│  Orchestrates stage execution                     │
│  Manages locks, KB updates, state                │
└─────────────────┬────────────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
┌───────┐   ┌─────────┐   ┌───────────┐
│ Stage │   │  Agent  │   │   LLM     │
│Runner │──►│ (with  │──►│ (via      │
│       │   │Context │   │Instructor)│
│       │   │ Policy) │   │           │
└───────┘   └─────────┘   └───────────┘
                  │
                  ▼
         ┌────────────────┐
         │ Conversation   │
         │ Storage (KB)   │
         │ - Per turn     │
         │ - Summaries    │
         └────────────────┘
```

### Key Components

**ConversationContext**: Multi-turn conversation management
- Token tracking and compression
- Automatic summarization at 50k token threshold
- Three storage policies: RAW, SUMMARY, NONE

**GitAnalyzer**: Analyzes git changes
- Multi-turn analysis (initial → breaking changes → impact → structured)
- Chunking for large diffs (>50k tokens)
- Extracts ChangeSummary with intent and impact

**TechnicalAuthor**: Synthesizes technical facts
- API changes (new/modified/deleted functions)
- Behavioral changes (what code does differently)
- Architecture changes (dependencies, class hierarchy)

**Coordinator**: Plans document structure
- Interactive mode: asks user for audience, focus, detail level
- Plans sections with TechnicalFact references
- Plans diagrams (PlantUML) for each section

**Output Agents**: Generate final documents
- MarkdownAgent: Native markdown with PlantUML diagrams
- DocxAgent: Markdown → Word via pandoc
- PptxAgent: Markdown → PowerPoint with slide extraction
- PdfAgent: Markdown → PDF via pandoc/LaTeX

## Command Reference

### analyze

Start a new analysis.

```bash
ggdes analyze --feature <name> --commits <range> [options]

Options:
  --feature TEXT          Name for this analysis [required]
  --commits TEXT          Git commit range (e.g., HEAD~5..HEAD) [required]
  --repo TEXT            Path to repository
  --provider TEXT        Model provider
  --model TEXT           Model name
  --api-key TEXT         API key
  --auto                 Run all stages automatically
  --force                Force run even if locked
```

### resume

Resume an incomplete analysis.

```bash
ggdes resume <analysis-id> [options]

Options:
  --stage TEXT           Run specific stage only
  --force                Force resume even if locked
```

### status

Show analysis status.

```bash
ggdes status [analysis-id]
```

### cleanup

Clean up worktrees.

```bash
ggdes cleanup <analysis-id> [--remove-kb]
```

### tui

Launch interactive terminal UI.

```bash
ggdes tui
```

### config

View configuration.

```bash
ggdes config
```

## Knowledge Base Structure

```
.ggdes/kb/analyses/<analysis-id>/
├── metadata.yaml              # Stage tracking, config
├── git_analysis/
│   └── summary.json           # ChangeSummary
├── ast_base/
│   └── <file>.json            # CodeElement[]
├── ast_head/
│   └── <file>.json            # CodeElement[]
├── technical_facts/
│   ├── facts.json             # All TechnicalFact[]
│   └── <fact_id>.json         # Individual facts
├── plans/
│   ├── plan_markdown.json     # DocumentPlan
│   ├── plan_docx.json
│   ├── index.json             # Plan index
│   └── ...
└── conversations/
    ├── git_analyzer/
    │   └── conversation_summary.json
    ├── technical_author/
    └── coordinator/
```

## Development

### Project Structure

```
ggdes/
├── __init__.py
├── cli.py                  # Typer CLI commands
├── config/                 # Configuration management
│   └── loader.py
├── agents/                 # AI agents
│   ├── git_analyzer.py
│   ├── technical_author.py
│   ├── coordinator.py
│   └── output_agents/
│       ├── markdown_agent.py
│       ├── docx_agent.py
│       ├── pptx_agent.py
│       └── pdf_agent.py
├── kb/                     # Knowledge base
│   └── manager.py
├── llm/                    # LLM providers
│   ├── factory.py
│   └── conversation.py
├── parsing/                # AST parsing
│   └── ast_parser.py
├── schemas/                # Pydantic models
│   └── models.py
├── prompts/                # Prompt templates
│   └── v1.0.0/
├── tui/                    # Textual TUI
│   └── app.py
├── validation/             # Guardrails
│   └── validators.py
├── pipeline.py             # Pipeline orchestrator
├── worktree/               # Git worktree management
│   └── manager.py
└── utils/                  # Utilities
    └── lock.py
```

### Running Tests

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Limitations

- **AST Parsing**: Currently supports Python and C++ only
- **LLM Dependency**: Requires API key for cloud providers or local Ollama
- **Output Formats**: Docx, Pptx, Pdf require pandoc (or fall back to text placeholders)
- **Large Repos**: Very large diffs (>100k tokens) may require chunking which loses some context

## Future Enhancements

- [ ] Dual-state analysis (compare semantic descriptions before/after)
- [ ] Support for more languages (Java, TypeScript, Go, Rust)
- [ ] Enhanced diagram generation (Mermaid, Graphviz)
- [ ] Web UI in addition to TUI
- [ ] CI/CD integration (GitHub Actions, GitLab CI)
- [ ] Template system for custom document formats
- [ ] Incremental analysis (only process changed files)

## License

MIT
