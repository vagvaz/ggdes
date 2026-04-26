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
  semantic_diff: true             # Compare before/after in detail (disable for faster analysis)
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
- `r` - Refresh
- `a` - New Analysis
- `s` - Set Start Commit (Git Log tab)
- `e` - Set End Commit (Git Log tab)
- `f` - Toggle Focus (Git Log tab)
- `c` - Clear Selection (Git Log tab)
- `t` - Switch to Feedback tab

### Tabs

| Tab | Purpose |
|-----|---------|
| 📊 Analyses | List, view details, resume, delete analyses |
| 🌳 Worktrees | Manage git worktrees |
| 📜 Git Log | Visual commit selection for analysis ranges |
| 📝 Feedback | Section-level feedback + live output viewer |
| ❓ Help | Command reference |

### Interactive Review Mode

Run analyses with `--interactive` to review each stage before proceeding:

```bash
uv run ggdes analyze --feature "my-feature" --commits "HEAD~5..HEAD" --interactive
```

After each reviewable stage completes, you'll see a preview and can:
- **Accept** — continue to the next stage
- **Regenerate all** — re-run with your feedback text
- **Regenerate specific items** — select items to regenerate
- **Skip review** — skip all remaining reviews

Feedback is persisted to the knowledge base and incorporated during regeneration.

### TUI Review & Feedback

The TUI provides two ways to give feedback:

#### 1. Review Screen (per-stage)
In the Analyses tab, select an analysis with completed stages and click **📝 Review**. You'll see:
- All reviewable stages with their status (✓ completed, ○ pending, ✗ failed)
- Checkboxes to mark stages for regeneration
- Text inputs for feedback per stage
- "Submit & Resume" to save feedback and continue analysis

#### 2. Feedback Tab (section-level)
Press `t` or switch to the **📝 Feedback** tab for granular, section-level feedback:
- **Left panel**: Document sections from the Coordinator's plan, each with a Markdown TextArea for targeted feedback
- **Right panel**: Live output file browser that auto-refreshes every 3 seconds, showing files as the pipeline generates them
- **Analysis selector**: Choose which analysis to provide feedback for
- **Save All Feedback**: Persists section feedback to the KB

Section feedback is injected into the output agent's prompts during document generation, ensuring each section reflects your specific guidance.

### Web UI

```bash
# Start web server
uv run ggdes web

# Custom host/port
uv run ggdes web --host 0.0.0.0 --port 8080

# Development mode with auto-reload
uv run ggdes web --reload
```

Features:
- Real-time updates via WebSocket
- View all analyses with progress bars
- Resume analyses with one click
- Download generated documents
- Preview and cleanup old worktrees
- System statistics dashboard

---

## Understanding the Pipeline

GGDes runs stages in sequence:

```
┌─────────────────────────────────────────────────────────────┐
│  Stage              │  What It Does                          │
├─────────────────────────────────────────────────────────────┤
│  1. worktree_setup  │  Creates isolated git worktrees        │
│  2. git_analysis    │  LLM analyzes diffs for intent/impact  │
│  3. change_filter   │  Filters relevant files for analysis   │
│  4. ast_parsing_base│  Parses AST of "before" state          │
│  5. ast_parsing_head│  Parses AST of "after" state           │
│  6. semantic_diff   │  Semantic change analysis              │
│  7. technical_author│  Extracts technical facts from code     │
│  8. coordinator_plan│  Plans document structure              │
│  9. output_gen      │  Generates final documents             │
└─────────────────────────────────────────────────────────────┘
```

### Interactive Review

When running with `--interactive`, reviewable stages (git_analysis, change_filter, technical_author, coordinator_plan, output_generation) pause for your feedback. Feedback is persisted to the KB and injected into agent prompts during regeneration.

### Feedback Loop

User feedback flows through the system:
1. **Collection**: CLI review prompts or TUI Feedback tab
2. **Persistence**: Saved to KB as `review_session.json` and `section_feedback.json`
3. **Injection**: Passed to TechnicalAuthor, Coordinator, and output agents
4. **Regeneration**: LLM incorporates feedback into regenerated output
5. **Self-Review**: Coordinator runs an LLM self-review after plan generation when feedback is present

### What's in the Knowledge Base

Each analysis creates a knowledge base at `.ggdes/kb/analyses/<id>/`:

```
metadata.yaml                # Stage tracking, timestamps
review_session.json          # Persisted review session feedback
section_feedback.json        # Section-level feedback from TUI
git_analysis/
  └── summary.json           # ChangeSummary (intent, impact, files)
ast_base/                    # AST of base commit
  └── <file>.json            # CodeElement[]
ast_head/                    # AST of head commit
  └── <file>.json            # CodeElement[]
semantic_diff/
  └── result.json            # Semantic change analysis
technical_facts/
  ├── facts.json             # All TechnicalFact[]
  └── <fact_id>.json         # Individual facts
plans/
  ├── plan_markdown.json     # Document plan with sections
  ├── plan_docx.json
  └── index.json
conversations/
  ├── git_analyzer/          # LLM conversation history
  ├── technical_author/
  └── coordinator/
```

You can inspect these files to understand what the agents extracted. The `review_session.json` and `section_feedback.json` files contain user feedback that is injected into agent prompts during regeneration.

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

### Tabs

| Tab | Description |
|-----|-------------|
| 📊 Analyses | List of analyses, detail view, resume, review, delete |
| 🌳 Worktrees | Active worktree management |
| 📜 Git Log | Visual commit selection with focus commits |
| 📝 Feedback | Section-level feedback + live output viewer |
| ❓ Help | Keyboard shortcut reference |

### Navigation

- **Left panel**: List of analyses with progress status
- **Right panel**: Details of selected analysis
- **Progress bar**: Shows overall completion
- **Review button**: Appears when reviewable stages are completed

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
- **Review**: Provide feedback on completed stages (appears when applicable)
- **Delete**: Remove analysis data with confirmation
- **New Analysis**: Create analysis from Git Log selection

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh |
| `a` | New Analysis |
| `t` | Switch to Feedback tab |
| `s` | Set Start Commit (Git Log) |
| `e` | Set End Commit (Git Log) |
| `f` | Toggle Focus (Git Log) |
| `c` | Clear Selection (Git Log) |

### Feedback Tab

The Feedback tab (`t` shortcut) provides:
- **Analysis selector**: Choose which analysis to work with
- **Section tree**: Document sections from the Coordinator's plan
- **Per-section feedback**: Markdown TextArea for each section
- **Live output viewer**: Auto-refreshing file browser showing pipeline output
- **Save All Feedback**: Persists to KB for use during document generation

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

### 3. Use Interactive Review for Quality Control

```bash
# Interactive mode lets you review each stage
ggdes analyze --feature "api-changes" --commits "HEAD~3..HEAD" --interactive
```

When prompted, review the planned sections and diagrams. Provide specific feedback like:
- "Add more detail about the authentication flow"
- "Include migration examples for the breaking API changes"
- "Focus on the performance improvements in the database layer"

### 4. Use the TUI Feedback Tab for Section-Level Guidance

Press `t` in the TUI to open the Feedback tab:
- Select your analysis from the dropdown
- Review document sections from the Coordinator's plan
- Provide targeted feedback per section in the Markdown TextAreas
- Click "Save All Feedback" to persist to the KB
- Watch live output files appear in the right panel as the pipeline runs

### 5. Resume with Feedback

If you provided feedback during review, resume the analysis to regenerate with your guidance:

```bash
# Via CLI
ggdes resume my-analysis-id --interactive

# Via TUI: select analysis → click Resume
```

The system loads your persisted feedback and injects it into agent prompts during regeneration.

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
  --interactive          Enable review mode after each stage
  --no-semantic-diff     Skip semantic diff analysis (faster)
```

#### `resume`

Resume incomplete analysis.

```bash
ggdes resume <analysis-id> [options]

Options:
  --stage TEXT           Run specific stage
  --force                Force resume
  --interactive          Enable review mode with feedback prompts
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

#### `web`

Start web server with real-time dashboard.

```bash
ggdes web [--host HOST] [--port PORT] [--reload]
```

#### `doctor`

Check system health and auto-fix issues.

```bash
ggdes doctor [--fix]
```

#### `compare`

Compare two analyses side-by-side.

```bash
ggdes compare analysis1 analysis2 [--output comparison.json]
```

#### `export`

Export analysis to JSON or ZIP.

```bash
ggdes export analysis-id output.zip [--include-diagrams]
```

#### `archive`

Archive old analyses.

```bash
ggdes archive analysis-id [--keep-days 30]
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
- **Output Dependencies**: Docx, Pptx, Pdf require pandoc or Node.js packages

---

## Future Roadmap

- [ ] Dual-state semantic analysis
- [ ] Support for Java, TypeScript, Go, Rust
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
