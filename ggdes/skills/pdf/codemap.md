# ggdes/skills/pdf/

## Responsibility

PDF format skill for the PdfAgent. Provides the LLM system prompt content for generating PDF documents using the reportlab library, plus reference materials for form filling (pypdf/pdfplumber) and advanced PDF processing (pypdfium2). The associated `scripts/` directory contains Python helpers for PDF form analysis and manipulation.

## Key Files

- `SKILL.md`: Primary skill content — PDF document structure guidelines, content density rules, visual element requirements, and reportlab API reference (384 lines). Loaded by PdfAgent for system prompt injection.
- `forms.md`: Form filling workflow guide — fillable vs non-fillable PDF forms, step-by-step instructions for field extraction, bounding box annotation, and field value filling using the Python scripts.
- `reference.md`: Advanced PDF processing reference — pypdfium2 for fast rendering, pdf-lib for JS-based PDF manipulation, and detailed code examples beyond the main skill.
- `LICENSE.txt`: License terms for the skill content.
- `scripts/`: Python helper scripts for PDF field extraction, form filling, bounding box validation, and image conversion (documented in `scripts/codemap.md`).

## Integration

- **Consumed by**: `PdfAgent` (`ggdes/agents/output_agents/pdf_agent.py`) — loaded via `_load_skill("pdf")` during init and injected into the LLM system prompt for document generation.
- **Scripts invoked via Python subprocess**: The LLM output may reference these scripts, and the agent or a workflow runner executes them directly as `python <script>.py <args>`.
