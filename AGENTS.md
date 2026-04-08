# AGENTS.md

This is a uv-managed Python project for GGDes (Get from Git Design Documentation).

## Setup

```bash
uv sync
```

## System Dependencies

The output agents require additional system-level dependencies for document generation:

### For DOCX Output (Word Documents)

**Option A: Node.js + docx-js (Recommended)**
```bash
# Install Node.js (if not already installed)
# Then install docx package globally
npm install -g docx
```

**Option B: Pandoc (Fallback)**
```bash
# Install pandoc for markdown-to-docx conversion
# Ubuntu/Debian: sudo apt-get install pandoc
# macOS: brew install pandoc
# Windows: winget install pandoc
```

### For PDF Output

No additional system dependencies required - uses reportlab Python library.

**Optional: For OCR on scanned PDFs:**
```bash
# Install tesseract OCR
# Ubuntu/Debian: sudo apt-get install tesseract-ocr
# macOS: brew install tesseract
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
```

### For PPTX Output (PowerPoint Presentations)

**Option A: Node.js + pptxgenjs (Recommended)**
```bash
# Install Node.js (if not already installed)
# Then install pptxgenjs package globally
npm install -g pptxgenjs
```

**Option B: Pandoc (Fallback)**
```bash
# Pandoc can also convert to PPTX (see DOCX section)
```

## Project Structure

- `main.py` - Entry point
- `pyproject.toml` - Project config (uv)
- `.python-version` - Python 3.13
- `ggdes/skills/` - Skill documentation for output agents
  - `docx/` - Word document generation patterns and scripts
  - `pdf/` - PDF generation patterns and scripts
  - `pptx/` - PowerPoint generation patterns and scripts
- `ggdes/agents/output_agents/` - Document output agents
  - `base.py` - Base class with skill loading support
  - `docx_agent.py` - Word document generator (loads docx skill)
  - `pdf_agent.py` - PDF generator (loads pdf skill)
  - `pptx_agent.py` - PowerPoint generator (loads pptx skill)

## Development

```bash
uv run main.py
```

## Output Agents

Each output agent loads its corresponding skill and generates documents with integrated diagrams:

### DocxAgent
- Loads skill from `ggdes/skills/docx/SKILL.md`
- Uses docx-js (Node.js) for professional Word document generation
- Auto-generates diagrams from technical facts and embeds them as images
- Supports proper styling, tables, lists, and formatting
- Falls back to pandoc if Node.js is unavailable

### PdfAgent
- Loads skill from `ggdes/skills/pdf/SKILL.md`
- Uses reportlab library for PDF generation
- Embeds generated diagrams as images in the PDF
- Supports text, headings, bullet lists, and visual elements
- Falls back to pandoc if reportlab fails

### PptxAgent
- Loads skill from `ggdes/skills/pptx/SKILL.md`
- Uses pptxgenjs (Node.js) for PowerPoint generation
- Creates visually engaging slides with embedded diagrams
- Follows the 6x6 rule: 6 bullet points max, 6 words per bullet
- Ensures every slide has a visual element (diagram, chart, or image)
- Falls back to pandoc if Node.js is unavailable

### MarkdownAgent
- Generates markdown documentation with YAML front matter
- Creates architecture, flow, and class diagrams from technical facts
- Embeds diagrams as both rendered images and PlantUML code blocks
- Includes executive summary and table of contents
- Provides navigation links for multi-page documentation

### Usage Example

```python
from ggdes.agents.output_agents import MarkdownAgent, DocxAgent, PdfAgent, PptxAgent
from pathlib import Path

# Create markdown documentation with diagrams
md_agent = MarkdownAgent(
    repo_path=Path("/path/to/repo"),
    config=config,
    analysis_id="analysis_123"
)
md_file = await md_agent.generate(auto_generate_diagrams=True)

# Create Word document with embedded diagrams
docx_agent = DocxAgent(
    repo_path=Path("/path/to/repo"),
    config=config,
    analysis_id="analysis_123"
)
docx_file = docx_agent.generate(auto_generate_diagrams=True)

# Create PDF with diagrams
pdf_agent = PdfAgent(
    repo_path=Path("/path/to/repo"),
    config=config,
    analysis_id="analysis_123"
)
pdf_file = pdf_agent.generate(auto_generate_diagrams=True)

# Create PowerPoint with diagrams
pptx_agent = PptxAgent(
    repo_path=Path("/path/to/repo"),
    config=config,
    analysis_id="analysis_123"
)
pptx_file = pptx_agent.generate(auto_generate_diagrams=True)
```

## LLM Providers

The project supports multiple LLM providers with automatic retry logic and configurable endpoints:

### Supported Providers

| Provider | Description | Required Config |
|----------|-------------|-----------------|
| `anthropic` | Claude API | `api_key` |
| `openai` | OpenAI API (with custom base_url support) | `api_key`, optional `base_url` |
| `ollama` | Local Ollama models | `base_url` |
| `opencodezen` | OpencodeZen gateway | `api_key` |
| `custom` | Generic OpenAI-compatible endpoint | `api_key`, `base_url` (required) |

### Configuration

Configure in `ggdes.yaml`:

```yaml
model:
  provider: "custom"  # or openai, anthropic, ollama, opencodezen
  model_name: "your-model"
  api_key: "${YOUR_API_KEY}"  # or literal, or env:VAR_NAME
  base_url: "https://api.example.com/v1"  # Required for custom, optional for openai
```

### Retry Logic

All LLM calls now include automatic retry with exponential backoff:
- 3 retry attempts by default
- Initial delay: 1 second
- Exponential backoff with jitter
- Configurable per-provider

The `retry_on_failure` decorator can also be used independently:

```python
from ggdes.llm import retry_on_failure

@retry_on_failure(max_retries=3, initial_delay=1.0)
def my_llm_call():
    # Your LLM call here
    pass
```

### Custom OpenAI Provider

Use the `custom` provider for any OpenAI-compatible API:

```yaml
model:
  provider: "custom"
  model_name: "your-model"
  api_key: "your-api-key"
  base_url: "https://api.custom-llm.com/v1"
```

### Structured Output Formats

The project supports both JSON and XML structured output formats, automatically selecting the best format for each provider:

| Provider | Default Format | Override |
|----------|------------------|----------|
| `anthropic` | XML | Yes |
| `custom` | XML | Yes |
| `openai` | JSON | Yes |
| `ollama` | JSON | Yes |
| `opencodezen` | JSON | Yes |

**Why XML for Anthropic/Custom?**
- Claude models have excellent native XML handling
- More reliable parsing than JSON for complex nested structures
- Self-documenting format with explicit tags

**Configuration:**

```yaml
model:
  provider: "anthropic"
  model_name: "claude-3-5-sonnet-20241022"
  api_key: "${ANTHROPIC_API_KEY}"
  structured_format: "auto"  # Options: "auto", "json", "xml"
```

Set `structured_format` to:
- `"auto"` - Automatically choose best format for provider (default)
- `"json"` - Force JSON format
- `"xml"` - Force XML format

**Error Recovery:**

When structured output parsing fails, the system:
1. Shows the parsing error to the user
2. Asks the LLM to correct the format with specific instructions
3. Retries up to 3 times with corrective prompts
4. Gradually increases temperature for variety on retries

**Example Model with Examples:**

```python
from pydantic import BaseModel, Field
from typing import List

class ChangeSummary(BaseModel):
    """Summary of code changes."""
    
    files_changed: List[str] = Field(description="List of files that were modified")
    summary: str = Field(description="Brief summary of changes")
    impact: str = Field(description="Impact level: low, medium, high")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "files_changed": ["src/main.py", "tests/test_main.py"],
                    "summary": "Added user authentication feature",
                    "impact": "high"
                }
            ]
        }
    }
```

## System Prompt Structure

All agents now follow a standardized system prompt structure:

### Order of Priority (Skills First)

1. **SKILLS** (highest priority - loaded first)
   - Language expertise (python-expert, cpp-expert)
   - Domain expertise (doc-coauthoring)
   - These provide foundational knowledge

2. **BASE SYSTEM PROMPT**
   - Core instructions for the agent
   - Task-specific guidelines

3. **USER GUIDANCE** (marked as "VERY IMPORTANT")
   - User context (focus areas, audience, purpose)
   - Explicitly marked as mandatory requirements
   - Overrides any default behaviors

Example structure:
```
=== LANGUAGE EXPERTISE ===
[skill content]
=== END LANGUAGE EXPERTISE ===

[base system prompt]

╔══════════════════════════════════════════════════════════════════╗
║                    ⚠️  VERY IMPORTANT  ⚠️                        ║
║              USER REQUIREMENTS (MUST FOLLOW)                   ║
╚══════════════════════════════════════════════════════════════════╝

[user context]

YOU MUST ADHERE TO ALL USER REQUIREMENTS ABOVE.
THESE OVERRIDE ANY DEFAULT BEHAVIORS.
```

## Code Reference Validation

The system validates all code references in LLM outputs to prevent hallucinations:

### What is Validated
- **File paths**: Must exist in the git diff or repository
- **Function names**: Must exist in the parsed AST
- **Class names**: Must exist in the parsed AST
- **Code snippets**: Must match content from the diff

### How It Works
1. After LLM generates output with code references
2. The `CodeReferenceValidator` extracts all code references
3. Each reference is checked against:
   - Changed files in the git diff
   - Code elements from AST parsing
   - Diff content for snippet verification
4. Invalid references trigger a correction request to the LLM

### Correction Flow
```python
from ggdes.validation import CodeReferenceValidator

validator = CodeReferenceValidator(
    repo_path=repo_path,
    changed_files=["src/main.py", "src/utils.py"],
    code_elements={"function_name": {...}, "ClassName": {...}},
    diff_content=git_diff,
)

# Validate and auto-correct if needed
validated_output = validator.validate_and_correct(
    llm_output=output_text,
    llm_provider=llm,
    max_corrections=2
)
```

### Validation Results
- Valid references: silently accepted
- Invalid references: warning displayed, correction requested
- After max corrections: warning appended to output

## Diagram Generation

The project includes a PlantUML-based diagram generation module:

### Location
- `ggdes/diagrams/` - Diagram generation module
  - `__init__.py` - Generator classes and helper functions
  - `plantuml.jar` - PlantUML executable (auto-downloaded)

### Supported Diagram Types

| Diagram Type | Use Case | Function |
|--------------|----------|----------|
| Architecture | System components & relationships | `generate_architecture_diagram()` |
| Class | OOP class hierarchies | `generate_class_diagram()` |
| Flow/Process | Step-by-step workflows | `generate_flow_diagram()` |
| Sequence | Interactions between objects | `generate_sequence_diagram()` |

### Usage Example

```python
from ggdes.diagrams import (
    PlantUMLGenerator,
    generate_architecture_diagram,
    generate_class_diagram,
)
from pathlib import Path

# Generate architecture diagram
plantuml_code = generate_architecture_diagram(
    components=[
        {"name": "Frontend", "type": "service", "label": "Web Frontend"},
        {"name": "API", "type": "service", "label": "REST API"},
        {"name": "Database", "type": "database"},
    ],
    relationships=[
        ("Frontend", "API", "HTTP requests"),
        ("API", "Database", "SQL queries"),
    ],
    title="System Architecture",
)

# Generate PNG diagram
generator = PlantUMLGenerator()
diagram_path = generator.generate(
    plantuml_code,
    output_path=Path("output/architecture.png"),
    format="png",  # Options: png, svg, pdf
)
```

### Output Format Skills

Each output format skill includes medium-specific guidelines:

**PPTX (Presentations)**:
- Maximum 6 bullet points per slide, 6 words per bullet
- Every slide requires a visual element (diagram, chart, or image)
- Use architecture diagrams for system changes
- Transform text descriptions into visual diagrams

**DOCX (Word Documents)**:
- Include table of contents for documents > 5 pages
- Paragraph length: 3-5 sentences maximum
- Include diagrams for architecture, data flow, and class relationships
- Use tables for API endpoint comparisons

**PDF Documents**:
- Start with title page and executive summary
- Use page numbers for all cross-references
- High-resolution diagrams (300 DPI minimum)
- Include bookmarks for major sections

**Markdown**:
- Use YAML front matter for metadata
- Include diagrams using relative paths
- Code blocks with language specification
- Navigation links for multi-page docs

## Current Status

Output agents implemented with skill-based architecture. Agents load skill documentation at initialization and use the documented patterns for document generation. Diagram generation module integrated with all output formats.

## New Features

### 1. Semantic Diff Analysis

GGDes now includes a semantic diff module that analyzes code changes beyond simple text diffs:

**Change Types Detected:**
- API changes (added, removed, modified, deprecated)
- Behavior changes (logic, algorithms, control flow)
- Refactoring (extraction, inlining, renaming)
- Documentation changes
- Error handling improvements
- Performance optimizations

**Usage:**
```bash
# Enable semantic diff (default)
ggdes analyze --feature X --commits "HEAD~5..HEAD"

# Disable for faster analysis
ggdes analyze --feature X --commits "HEAD~5..HEAD" --no-semantic-diff
```

**When Disabled:**
- Base AST parsing stage is skipped
- Semantic diff stage is skipped
- Only HEAD AST parsing runs
- Analysis completes faster with less detail

### 2. Analysis Comparison

Compare two analyses side-by-side to understand differences:

```bash
# Compare two analyses
ggdes compare analysis1 analysis2

# Export comparison to JSON
ggdes compare analysis1 analysis2 --output comparison.json
```

**Comparison includes:**
- Commit range differences
- File change metrics
- Technical facts (added/removed/modified)
- Breaking changes
- Semantic analysis differences (when available)
- Similarity score (0-100%)

### 3. Web Interface

Access GGDes through a modern web UI:

```bash
# Start web server
ggdes web

# Custom host/port
ggdes web --host 0.0.0.0 --port 8080

# Development mode with auto-reload
ggdes web --reload
```

**Features:**
- Real-time updates via WebSocket
- View all analyses with progress bars
- Resume analyses with one click
- Download generated documents
- Preview and cleanup old worktrees
- System statistics dashboard

**Dependencies:** Install web extras: `uv pip install -e ".[web]"`

### 4. TUI Improvements

The terminal UI now has full functionality:

- **Resume Analysis:** Click "Resume" button or press Enter on analysis
- **Delete Analysis:** Confirmation dialog with worktree cleanup
- **New Analysis:** Create analyses directly from TUI with commit selection
- **Git Log Integration:** Select commits visually before creating analysis

### 5. Worktree Retention Cleanup

Automatic cleanup of old worktrees to save disk space:

```bash
# Preview what would be cleaned up
ggdes status  # Shows worktree ages

# Via web UI: Preview Cleanup button
```

**Configuration:**
- `worktree_retention_days` in config (default: 7 days)
- Accessible through `WorktreeManager.cleanup_old_worktrees()`

### 6. Import/Export/Archive

Manage analysis lifecycle:

```bash
# Export analysis to JSON or ZIP
ggdes export analysis-id output.zip --include-diagrams

# Archive old analyses
ggdes archive analysis-id --keep-days 30

# All data preserved for future reference
```

### 7. Doctor Command

System health checks and automatic fixes:

```bash
# Check system health
ggdes doctor

# Auto-fix issues
ggdes doctor --fix
```

**Checks:**
- Repository configuration
- LLM provider connectivity
- PlantUML availability
- Knowledge base integrity

## Architecture Overview

### Pipeline Stages

1. **worktree_setup** - Create base and head worktrees
2. **git_analysis** - Analyze git commits and changes
3. **ast_parsing_base** - Parse base commit AST (skipped if no semantic diff)
4. **ast_parsing_head** - Parse head commit AST
5. **semantic_diff** - Analyze semantic changes (optional)
6. **technical_author** - Synthesize technical facts
7. **coordinator_plan** - Create document plans
8. **output_generation** - Generate documents in all formats

### Data Flow

```
Git Commits → Git Analysis → AST Parsing → Semantic Diff →
Technical Facts → Document Plans → Output Generation
                ↓
            Comparison → Web UI / TUI / CLI
```

### Output Formats

- **Markdown** - Source format with embedded diagrams
- **DOCX** - Word documents (requires Node.js + docx or pandoc)
- **PDF** - Portable documents (uses reportlab)
- **PPTX** - PowerPoint presentations (requires Node.js + pptxgenjs)

All formats support diagram integration and follow medium-specific best practices.
