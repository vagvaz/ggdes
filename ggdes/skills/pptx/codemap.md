# ggdes/skills/pptx/

## Responsibility

PPTX format skill for the PptxAgent. Provides the LLM system prompt content for generating PowerPoint presentations using pptxgenjs (Node.js) or editing existing templates. Includes design guidelines, visual engagement rules, and the template-based editing workflow.

## Key Files

- `SKILL.md`: Primary skill content — slide structure rules (6x6 rule), visual engagement requirements, PlantUML diagram integration, design guidelines, and detailed pptxgenjs API reference (292 lines). Loaded by PptxAgent for system prompt injection.
- `pptxgenjs.md`: Comprehensive pptxgenjs tutorial — setup, layout dimensions, text/formatting, tables, charts, images, shapes, speaker notes, and advanced features (420 lines).
- `editing.md`: Template-based editing workflow — slide analysis via thumbnails and markitdown, planning slide mapping, unpacking/packing workflow, and XML-level slide editing via the Python scripts.
- `LICENSE.txt`: License terms for the skill content.
- `scripts/`: Python helper scripts for slide manipulation, thumbnail generation, unpack/pack/validation of PPTX files (documented in `scripts/codemap.md`).

## Integration

- **Consumed by**: `PptxAgent` (`ggdes/agents/output_agents/pptx_agent.py`) — loaded via `_load_skill("pptx")` during init and injected into the LLM system prompt for presentation generation.
- **Scripts invoked via Python subprocess**: Slide manipulation (`add_slide.py`, `clean.py`), thumbnail generation (`thumbnail.py`), and Office file operations (`scripts/office/`) are invoked as Python subprocesses.
