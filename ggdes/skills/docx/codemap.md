# ggdes/skills/docx/

## Responsibility

DOCX format skill for the DocxAgent. Provides the LLM system prompt content for generating Word documents using docx-js (Node.js) or editing existing documents at the XML level. Includes document structure guidelines, content density rules, and XML manipulation patterns for tracked changes and comments.

## Key Files

- `SKILL.md`: Primary skill content — document structure guidelines (TOC, headings, executive summary), content density rules, visual element requirements, PlantUML diagram integration, docx-js JavaScript API, and extensive XML editing patterns for tracked changes, comments, and formatting (660 lines). Loaded by DocxAgent for system prompt injection.
- `LICENSE.txt`: License terms for the skill content.
- `scripts/`: Python helper scripts for tracked change acceptance, comment manipulation, and Office file pack/unpack/validation (documented in `scripts/codemap.md`).

## Integration

- **Consumed by**: `DocxAgent` (`ggdes/agents/output_agents/docx_agent.py`) — loaded via `_load_skill("docx")` during init and injected into the LLM system prompt for document generation.
- **Scripts invoked via Python subprocess**: Tracked change acceptance (`accept_changes.py`), comment management (`comment.py`), and Office file operations (`scripts/office/`) are invoked as Python subprocesses.
