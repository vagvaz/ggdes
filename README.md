# GGDes: Git-based Design Documentation Generator

**GGDes** automatically generates design documentation from your git commits using AI agents. It analyzes code changes, extracts technical facts, and produces comprehensive documentation in Markdown, Word, PowerPoint, or PDF.

**Why GGDes?**
- Turn code changes into technical docs without manual writing
- Understand the "why" behind changes, not just the "what"
- Generate consistent documentation for PRs, releases, or architecture reviews
- Keep docs in sync with code through automated analysis

---

## 🚀 Quick Start (5 minutes)

### 1. Install

```bash
# Clone and enter repository
git clone <repo-url>
cd ggdes

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e ".[dev]"
```

### 2. Configure

Create `ggdes.yaml` in your project root:

**Option A: Anthropic Claude (Recommended)**
```yaml
model:
  provider: "anthropic"
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}"
```

**Option B: Ollama (Local, Free)**
```yaml
model:
  provider: "ollama"
  model_name: "llama3.2"
  api_key: "ollama"
  base_url: "http://localhost:11434/v1"
```

**Option C: OpenAI**
```yaml
model:
  provider: "openai"
  model_name: "gpt-4"
  api_key: "${OPENAI_API_KEY}"
```

### 3. Analyze Your First Change

```bash
# Analyze the last 5 commits
uv run ggdes analyze --feature "my-feature" --commits "HEAD~5..HEAD" --auto
```

That's it! Your documentation will be in `docs/` when complete.

---

## 📖 Full User Manual

### Table of Contents

1. [Installation Guide](#installation-guide)
2. [Configuration](#configuration)
3. [Basic Usage](#basic-usage)
4. [Advanced Usage](#advanced-usage)
5. [Understanding the Pipeline](#understanding-the-pipeline)
6. [Output Formats](#output-formats)
7. [TUI Guide](#tui-guide)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Installation Guide

### Prerequisites

- **Python**: 3.10 or higher
- **Git**: 2.20 or higher
- **uv** (recommended) or pip

### Method 1: Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup
git clone <repo-url>
cd ggdes
uv sync
```

### Method 2: Using pip

```bash
git clone <repo-url>
cd ggdes
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Method 3: From PyPI (when published)

```bash
pip install ggdes
```

---

## Configuration

GGDes uses a YAML configuration file. It searches for config in this order:

1. CLI flags (`--provider`, `--model`, `--api-key`)
2. `./ggdes.yaml` (project-local)
3. `~/.ggdes/config.yaml` (global user config)
4. Defaults

### Complete Configuration Options

```yaml
# Required: Model configuration
model:
  provider: "anthropic"           # anthropic, openai, ollama, opencodezen
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}" # Environment variable syntax
  base_url: null                  # For Ollama or custom endpoints

# Optional: Paths configuration
paths:
  knowledge_base: ".ggdes/kb"     # Where analysis data is stored
  worktrees: ".ggdes/worktrees"   # Temporary git worktrees

# Optional: Output configuration
output:
  default_format: "markdown"      # markdown, docx, pptx, pdf
  formats: ["markdown", "docx"]   # Generate multiple formats
  output_dir: "docs"              # Where final docs are saved

# Optional: Feature flags
features:
  dual_state_analysis: false      # Compare before/after in detail
  auto_cleanup: true              # Clean up worktrees after analysis
  worktree_retention_days: 7      # How long to keep worktrees
```

### Provider-Specific Setup

#### Anthropic (Claude)

1. Get API key: https://console.anthropic.com/
2. Set environment variable:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```

#### OpenAI (GPT-4)

1. Get API key: https://platform.openai.com/
2. Set environment variable:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

#### Ollama (Local Models)

1. Install Ollama: https://ollama.com/
2. Pull a model:
   ```bash
   ollama pull llama3.2
   ```
3. Configure base_url if not on localhost:
   ```yaml
   base_url: "http://192.168.0.179:11434/v1"
   ```

#### OpencodeZen (Gateway)

1. Get API key from OpencodeZen
2. Configure:
   ```yaml
   provider: "opencodezen"
   api_key: "${OPENCODEZEN_API_KEY}"
   ```
   Automatically routes to correct provider backend based on model name.

---

## Basic Usage

### Starting an Analysis

```bash
# Interactive mode (asks questions during planning)
uv run ggdes analyze --feature "user-auth" --commits "HEAD~3..HEAD"

# Automatic mode (uses defaults)
uv run ggdes analyze --feature "api-refactor" --commits "abc123..def456" --auto

# Specify a different repository
uv run ggdes analyze --feature "backend-changes" --commits "HEAD~10..HEAD" --repo /path/to/other/repo
```

### Understanding Commit Ranges

GGDes uses standard git revision syntax:

| Syntax | Meaning |
|--------|---------|
| `HEAD~5..HEAD` | Last 5 commits |
| `abc123..def456` | From commit abc123 to def456 |
| `v1.0..v2.0` | Between two tags |
| `main..feature-branch` | Compare branches |
| `HEAD~1` | Just the last commit |

### Checking Status

```bash
# List all analyses
uv run ggdes status

# Show specific analysis details
uv run ggdes status my-analysis-20240115-123456
```

### Resuming Analysis

If an analysis fails or you want to re-run a stage:

```bash
# Resume from where it left off
uv run ggdes resume my-analysis-20240115-123456

# Run a specific stage only
uv run ggdes resume my-analysis-20240115-123456 --stage technical_author

# Force re-run even if stage is complete
uv run ggdes resume my-analysis-20240115-123456 --stage git_analysis --force
```

### Cleaning Up

```bash
# Remove worktrees for an analysis (keeps KB data)
uv run ggdes cleanup my-analysis-20240115-123456

# Remove everything including KB data
uv run ggdes cleanup my-analysis-20240115-123456 --remove-kb
```

---

## Advanced Usage

### Multi-Format Output

Generate documentation in multiple formats at once:

```yaml
# ggdes.yaml
output:
  formats: ["markdown", "docx", "pptx", "pdf"]
```

Or via CLI:

```bash
# Currently, formats are set in config. Future versions may support:
# uv run ggdes analyze ... --format markdown --format docx
```

### Custom Output Directory

```yaml
# ggdes.yaml
paths:
  output_dir: "documentation/releases"
```

### Working with Large Changes

For very large diffs (>50k tokens), GGDes automatically chunks the analysis:

```bash
# Increase chunk size (default: 25000 tokens)
# This is controlled internally, but you can monitor progress
uv run ggdes analyze --feature "big-refactor" --commits "HEAD~50..HEAD" --auto
```

### Using the TUI

```bash
# Launch interactive UI
uv run ggdes tui
```

Keyboard shortcuts:
- `q` - Quit
- `r` - Resume selected analysis
- `a` - Show all / Active only toggle
- `↑/↓` - Navigate analyses

---

## Understanding the Pipeline

GGDes runs 8 stages in sequence:

```
┌─────────────────────────────────────────────────────────────┐
│  Stage              │  What It Does                          │
├─────────────────────────────────────────────────────────────┤
│  1. worktree_setup  │  Creates isolated git worktrees        │
│  2. git_analysis    │  LLM analyzes diffs for intent/impact  │
│  3. ast_parsing_base│  Parses AST of "before" state          │
│  4. ast_parsing_head│  Parses AST of "after" state           │
│  5. semantic_diff   │  (Future) Semantic comparison          │
│  6. technical_author│  Extracts technical facts from code     │
│  7. coordinator_plan│  Plans document structure              │
│  8. output_gen      │  Generates final documents             │
└─────────────────────────────────────────────────────────────┘
```

### What's in the Knowledge Base

Each analysis creates a knowledge base at `.ggdes/kb/analyses/<id>/`:

```
metadata.yaml           # Stage tracking, timestamps
git_analysis/
  └── summary.json      # ChangeSummary (intent, impact, files)
ast_base/               # AST of base commit
  └── <file>.json       # CodeElement[]
ast_head/               # AST of head commit
  └── <file>.json       # CodeElement[]
technical_facts/
  ├── facts.json        # All TechnicalFact[]
  └── <fact_id>.json    # Individual facts
plans/
  ├── plan_markdown.json
  ├── plan_docx.json
  └── index.json
conversations/
  ├── git_analyzer/     # LLM conversation history
  ├── technical_author/
  └── coordinator/
```

You can inspect these files to understand what the agents extracted.

---

## Output Formats

### Markdown (Native)

- No external dependencies
- Includes PlantUML diagrams
- Best for GitHub, wikis, or further editing

### Word (Docx)

Requires **pandoc**:

```bash
# Ubuntu/Debian
sudo apt-get install pandoc

# macOS
brew install pandoc

# Windows
choco install pandoc
```

If pandoc is not available, falls back to plain text files.

### PowerPoint (Pptx)

Requires **pandoc** for conversion.

Slides are automatically extracted from markdown headers.

### PDF

Requires **pandoc** and **LaTeX**:

```bash
# Ubuntu/Debian
sudo apt-get install pandoc texlive

# macOS
brew install pandoc texlive
```

---

## TUI Guide

The Terminal User Interface provides a visual way to manage analyses.

```bash
uv run ggdes tui
```

### Navigation

- **Left panel**: List of analyses with status
- **Right panel**: Details of selected analysis
- **Progress bar**: Shows overall completion

### Status Indicators

| Icon | Meaning |
|------|---------|
| `○` | Pending |
| `◐` | In Progress |
| `✓` | Complete |
| `✗` | Failed |
| `⊘` | Skipped |

### Actions

- **Resume**: Continue an incomplete analysis
- **Delete**: Remove analysis data
- **Open Worktree**: Open the git worktree in your $EDITOR

---

## Troubleshooting

### "Request timed out" Error

**Cause**: LLM API is slow or unreachable

**Solutions**:
1. Check your internet connection
2. Verify API key is set: `echo $ANTHROPIC_API_KEY`
3. For Ollama, ensure server is running: `curl http://localhost:11434/api/tags`
4. Increase timeout (not currently configurable, but planned)

### "No technical facts found" Error

**Cause**: Commit range has no actual code changes

**Solutions**:
1. Check commit range has file changes:
   ```bash
   git diff --stat HEAD~5..HEAD
   ```
2. Use a larger range: `HEAD~10..HEAD` instead of `HEAD~1..HEAD`
3. Ensure changes are in tracked files (not just config/docs)

### "Failed to parse AST" Warning

**Cause**: File uses unsupported language or syntax

**Solutions**:
1. Currently supports Python and C++
2. Other languages are parsed but may miss some constructs
3. Check file is valid syntax

### Pandoc Not Found

**Cause**: Docx/Pptx/Pdf generation requires pandoc

**Solutions**:
1. Install pandoc (see [Output Formats](#output-formats))
2. Use markdown-only output:
   ```yaml
   output:
     formats: ["markdown"]
   ```

### Lock File Stuck

**Cause**: Previous analysis crashed without cleanup

**Solutions**:
```bash
# Force remove lock
rm .ggdes/kb/analyses/<id>/metadata.lock

# Or use force flag
uv run ggdes resume <id> --force
```

---

## Best Practices

### 1. Use Descriptive Feature Names

```bash
# Good
ggdes analyze --feature "user-authentication-v2" --commits "HEAD~5..HEAD"

# Avoid
ggdes analyze --feature "test" --commits "HEAD~5..HEAD"
```

### 2. Analyze Logical Groups

Analyze one feature/PR at a time rather than large ranges:

```bash
# Good: Just the auth feature commits
ggdes analyze --feature "oauth-integration" --commits "abc123..def456"

# Avoid: Too broad
ggdes analyze --feature "everything" --commits "HEAD~50..HEAD"
```

### 3. Review Before Finalizing

In interactive mode, review the coordinator's document plan:

```bash
# Interactive mode shows you the plan before generating
ggdes analyze --feature "api-changes" --commits "HEAD~3..HEAD"
# When prompted, review the planned sections and diagrams
```

### 4. Keep Worktrees for Review

```yaml
# ggdes.yaml
features:
  auto_cleanup: false  # Keep worktrees for manual inspection
  worktree_retention_days: 30
```

### 5. Version Your Docs

```bash
# Generate docs before each release
ggdes analyze --feature "release-v2.1" --commits "v2.0..v2.1" --auto

# Output: docs/release-v2.1-20240115-design-document.md
```

---

## Command Reference

### Global Options

| Flag | Description |
|------|-------------|
| `--repo PATH` | Path to git repository |
| `--provider TEXT` | LLM provider (anthropic, openai, ollama, opencodezen) |
| `--model TEXT` | Model name |
| `--api-key TEXT` | API key (overrides config) |
| `--config PATH` | Path to config file |

### Commands

#### `analyze`

Start a new analysis.

```bash
ggdes analyze --feature <name> --commits <range> [options]

Options:
  --feature TEXT          Analysis name [required]
  --commits TEXT          Git commit range [required]
  --repo TEXT            Repository path
  --provider TEXT        Model provider
  --model TEXT           Model name
  --api-key TEXT         API key
  --auto                 Run all stages automatically
  --force                Force run even if locked
```

#### `resume`

Resume incomplete analysis.

```bash
ggdes resume <analysis-id> [options]

Options:
  --stage TEXT           Run specific stage
  --force                Force resume
```

#### `status`

Show analysis status.

```bash
ggdes status [analysis-id]
```

#### `cleanup`

Clean up worktrees.

```bash
ggdes cleanup <analysis-id> [--remove-kb]
```

#### `tui`

Launch interactive terminal UI.

```bash
ggdes tui
```

#### `config`

View current configuration.

```bash
ggdes config
```

---

## Development

### Project Structure

```
ggdes/
├── cli.py                  # CLI commands
├── config/                 # Configuration
├── agents/                 # AI agents
│   ├── git_analyzer.py
│   ├── technical_author.py
│   ├── coordinator.py
│   └── output_agents/
├── kb/                     # Knowledge base
├── llm/                    # LLM providers
├── parsing/                # AST parsing
├── schemas/                # Data models
├── tui/                    # Terminal UI
└── pipeline.py             # Orchestrator
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

---

## Limitations

- **Languages**: Python and C++ have full AST support; others are partially supported
- **LLM Required**: Cloud providers need API keys; Ollama needs local setup
- **Large Diffs**: Very large changes (>100k tokens) use chunking which may lose some context
- **Output Dependencies**: Docx, Pptx, Pdf require pandoc installation

---

## Future Roadmap

- [ ] Dual-state semantic analysis
- [ ] Support for Java, TypeScript, Go, Rust
- [ ] Web UI for non-terminal users
- [ ] CI/CD integrations (GitHub Actions, etc.)
- [ ] Custom document templates
- [ ] Incremental analysis (changed files only)
- [ ] Team collaboration features

---

## License

MIT License - See LICENSE file for details.

---

## Getting Help

- **Issues**: https://github.com/yourorg/ggdes/issues
- **Discussions**: https://github.com/yourorg/ggdes/discussions
- **Documentation**: This README + inline help (`ggdes --help`)
