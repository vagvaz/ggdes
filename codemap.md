# Repository Atlas: GGDes

## Project Responsibility

GGDes (Get from Git Design Documentation) is a multi-stage pipeline that analyzes git commits and generates comprehensive design documentation in Markdown, DOCX, PDF, and PPTX formats with embedded diagrams. The system uses LLM-powered agents, tree-sitter AST parsing, semantic diff analysis, and PlantUML diagram generation to produce release-quality technical documentation from code changes.

## System Entry Points

| Path | Purpose |
|------|---------|
| `main.py` | CLI entry point — delegates to `ggdes.cli` |
| `ggdes/pipeline.py` | Pipeline orchestrator — runs 9 analysis stages in sequence |
| `ggdes/cli/__init__.py` | Typer app definition, command registration |
| `ggdes/config/loader.py` | Configuration loading and resolution |
| `pyproject.toml` | Project metadata, dependencies, build config |
| `ggdes.yaml` | User-facing configuration defaults |

## Repository Directory Map

| Directory | Responsibility Summary | Detailed Map |
|-----------|------------------------|--------------|
| `ggdes/agents/` | LLM-powered agents (GitAnalyzer, TechnicalAuthor) + programmatic Coordinator + ChangeFilter. Anti-hallucination via tool-augmented LLM + source code injection. | [View Map](ggdes/agents/codemap.md) |
| `ggdes/agents/output_agents/` | Format-specific document generators (Markdown, DOCX, PDF, PPTX) using Template Method pattern. Shared base class with `_convert()` seam for each format. | [View Map](ggdes/agents/output_agents/codemap.md) |
| `ggdes/cli/` | Typer CLI app with 12 commands across 9 modules. Entry point for user interaction. | [View Map](ggdes/cli/codemap.md) |
| `ggdes/cli/commands/` | CLI command implementations: analyze, compare, config, doctor, export, archive, resume, status, server, tui, web, debug. | [View Map](ggdes/cli/commands/codemap.md) |
| `ggdes/config/` | Configuration hierarchy (GGDesConfig → 7 sub-configs). 4-tier resolution (CLI > project yaml > user yaml > defaults). Env var resolution. | [View Map](ggdes/config/codemap.md) |
| `ggdes/stages/` | Stage abstraction: `Stage` ABC with `async run()` interface, `StageResult`, `STAGE_REGISTRY`, stage name constants, shared utilities, and `WorktreeSetupStage` reference implementation. | [View Map](ggdes/stages/codemap.md) |
| `ggdes/pipeline.py` | `AnalysisPipeline` orchestrator — runs 9 stages in sequence, parallel group execution (ast_parsing_base + head), stage registry integration, interactive review, resume support. | [View Map](ggdes/codemap.md) |
| `ggdes/parsing/` | Tree-sitter AST parser for Python and C++. Full/incremental modes. Element extraction (functions, classes). | [View Map](ggdes/parsing/codemap.md) |
| `ggdes/schemas/` | Canonical Pydantic models (ChangeSummary, TechnicalFact, DocumentPlan, etc.) and enums flowing through the pipeline. Stage I/O contracts. | [View Map](ggdes/schemas/codemap.md) |
| `ggdes/llm/` | LLM provider abstraction (Anthropic, OpenAI, Ollama, Custom). Retry logic with exponential backoff. Structured output generation (JSON/XML). | [View Map](ggdes/llm/codemap.md) |
| `ggdes/tools/` | Tool system for grounded LLM calls. 6 tools (read_file, search_code, validate_reference, etc.). Multi-turn tool-calling loop. Anti-hallucination. | [View Map](ggdes/tools/codemap.md) |
| `ggdes/validation/` | Three-layer validation: code references, AST facts, pipeline inputs. Auto-correction with LLM retry. | [View Map](ggdes/validation/codemap.md) |
| `ggdes/kb/` | File-system persistence layer. Analysis metadata, stage tracking, artifacts, review sessions, feedback. | [View Map](ggdes/kb/codemap.md) |
| `ggdes/worktree/` | Git worktree creation/cleanup for isolated base/head inspection. Retention policy. Standalone module. | [View Map](ggdes/worktree/codemap.md) |
| `ggdes/diagrams/` | PlantUML diagram generation (architecture, flow, class, sequence). LLM-driven + template fallback. Diagram caching. | [View Map](ggdes/diagrams/codemap.md) |
| `ggdes/rendering/` | Playwright-based Markdown→PNG renderer with cached browser instance. Section splitting. Light/dark themes. | [View Map](ggdes/rendering/codemap.md) |
| `ggdes/prompts/` | Versioned YAML prompt files for each agent. PromptLoader with caching. | [View Map](ggdes/prompts/codemap.md) |
| `ggdes/skills/` | SKILL.md files with language expertise, domain expertise, and format-specific guidelines. Injected into LLM system prompts. | [View Map](ggdes/skills/codemap.md) |
| `ggdes/review/` | Interactive stage review system. Preview generation per stage. Accept/regenerate/skip decisions. CLI-tight coupling (rich). | [View Map](ggdes/review/codemap.md) |
| `ggdes/tui/` | Textual-based terminal UI with 5 tabs, 10+ widgets, keyboard shortcuts. Analysis browsing, git log, worktree management. | [View Map](ggdes/tui/codemap.md) |
| `ggdes/web/` | FastAPI web interface with dashboard, feedback UI, analysis detail. WebSocket real-time updates. ConnectionManager. | [View Map](ggdes/web/codemap.md) |
| `ggdes/web/routes/` | 24 API routes across 5 modules: analyses CRUD (13), feedback (3), pages (3), worktrees/stats (3), WebSocket (1). APIRouter pattern. | [View Map](ggdes/web/routes/codemap.md) |
| `ggdes/utils/` | Analysis locking (LockContext) for preventing concurrent runs. | [View Map](ggdes/utils/codemap.md) |

## Data Flow

```
Git Commits
    │
    ▼
┌─────────────────────┐
│ Worktree Setup      │  Creates isolated base/head git worktrees
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Git Analysis        │  GitAnalyzer agent: diff + commit log → ChangeSummary
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Change Filter (opt) │  LLM relevance filter → filtered ChangeSummary
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ AST Parsing         │  tree-sitter: Python + C++ element extraction
│ (base + head)       │  Full or incremental mode
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Semantic Diff       │  Rule-based detection: signatures, docs, control flow,
│                     │  error handling (Python: ast, C++: tree-sitter)
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Technical Author    │  LLM agent: synthesizes TechnicalFact objects
│                     │  4-layer anti-hallucination (tools, source, validation)
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Coordinator         │  Programmatic orchestrator: saves
│                     │  shared_context/context.json
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Output Generation   │  Each agent plans its own content per medium.
│                     │  MarkdownAgent self-plans sections via LLM,
│                     │  PptxAgent self-generates slide-native content.
│                     │  DOCX/PDF consume shared markdown or plan.
│                     │  PlantUML diagrams embedded in all formats.
└─────────────────────┘
          │
          ▼
    ggdes-output/{analysis_id}/
```

## Key Architectural Decisions

- **Stage extraction**: `Stage` ABC with async `run()` interface, STAGE_REGISTRY dispatch, extracted one stage at a time from the original pipeline god object.
- **Template Method**: Output agents share a common `generate()` template with `_convert()` seam for format-specific logic.
- **Browser caching**: Playwright browser cached across section renders (was: one browser per section).
- **C++ detection**: Tree-sitter queries for semantic diff on C++ files (was: Python-only via `ast.parse()`).
- **Diff caching**: Git diff cached to KB after git analysis; change_filter reads cache.
- **Stage name constants**: Canonical source in `ggdes/stages/__init__.py`; callers import from there.
- **Web module**: Split from 2198-line monolith into 9 files with APIRouter per concern.
- **Doctor command**: Extended `ggdes doctor` with comprehensive system-level dependency checks (Java, Graphviz, Node.js, npm packages, LibreOffice, Poppler, Tesseract, Pandoc) organized by subsystem.
