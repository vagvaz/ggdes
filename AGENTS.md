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

Each output agent now loads its corresponding skill from the skills directory:

### DocxAgent
- Loads skill from `ggdes/skills/docx/SKILL.md`
- Uses docx-js (Node.js) for professional Word document generation
- Falls back to pandoc if Node.js is unavailable
- Supports proper styling, tables, lists, and formatting

### PdfAgent
- Loads skill from `ggdes/skills/pdf/SKILL.md`
- Uses reportlab library for PDF generation
- No external dependencies required
- Supports text, headings, and bullet lists

### PptxAgent
- Loads skill from `ggdes/skills/pptx/SKILL.md`
- Uses pptxgenjs (Node.js) for PowerPoint generation
- Falls back to pandoc if Node.js is unavailable
- Creates professional slides with consistent styling

## Current Status

Output agents implemented with skill-based architecture. Agents load skill documentation at initialization and use the documented patterns for document generation.
