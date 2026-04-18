## Project Purpose
- GGDes analyzes Git changes with AI agents to produce design documentation (Markdown, DOCX, PPTX, PDF).
- Supports automated pipelines for summarizing intent, extracting technical facts, planning documents, and generating outputs from multiple providers (Anthropic, OpenAI, Ollama, custom).

## Tech Stack
- Python 3.10+ with Typer CLI, Rich/Textual TUI, FastAPI-based web UI (optional web extra), Pydantic schemas, Tree-sitter parsers.
- Document generation: reportlab/Pillow for PDF, docx (via Node.js or pandoc), pptxgenjs, PlantUML diagram generation.
- LLM integrations: anthropic, openai, ollama, opencodezen, generic OpenAI-compatible endpoints.

## High-Level Architecture
- `ggdes/agents`: LLM agents orchestrating analysis stages (git analyzer, technical author, coordinator, output agents).
- `ggdes/pipeline`: Pipeline definitions and stage execution logic.
- `ggdes/diagrams`: PlantUML diagram generation helpers.
- `ggdes/rendering` & `ggdes/output_agents`: format-specific document builders.
- `ggdes/config`, `ggdes/utils`, `ggdes/worktree`: configuration handling and Git worktree management.
- CLI entry point at `main.py`/`ggdes/cli.py`; knowledge base in `.ggdes/`.
- Tests under `tests/`; documentation assets in `docs/`; configuration example `ggdes.yaml`.

## Notable Features
- Semantic diff module (Tree-sitter) for intent-aware comparisons.
- Web UI (`ggdes web`) and TUI (`ggdes tui`) for managing analyses.
- Automatic diagram generation embedded in outputs.
- Worktree management with retention cleanup and analysis comparison utilities.
