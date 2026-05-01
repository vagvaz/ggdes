# Output Agents — Codemap

## Responsibility

Format-specific document generators that consume document plans (produced by the
Coordinator) and produce final output files in Markdown, DOCX, PDF, and PPTX formats.
All output agents share a common base class that implements the **Template Method pattern**
for document generation.

```
Coordinator plans
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                  OutputAgent (abstract base)                 │
│                                                             │
│  generate() ← template method                               │
│    ├─ 1. _get_content()        — load markdown or build     │
│    │                             from plan sections           │
│    ├─ 2. _append_feedback()    — inject review/section      │
│    │                             feedback                    │
│    ├─ 3. _prepare_content()    — optional preprocessing     │
│    │                             (pptx: slides+palette)      │
│    ├─ 4. _generate_and_log_   — generate architecture,     │
│    │     diagrams()              flow, class diagrams        │
│    └─ 5. _convert()            — format-specific output     │
│                                  (abstract)                 │
├───────────────────┬───────────────────┬──────────────────┐  │
│                   │                   │                  │  │
│  MarkdownAgent    │  DocxAgent        │  PdfAgent        │  PptxAgent
│  (direct LLM      │  (docx-js/        │  (reportlab/     │  (pptxgenjs/
│   section gen)    │   pandoc)         │   pandoc)        │   pandoc)
│                   │                   │                  │
│  _convert() is    │  _convert() is    │  _convert() is   │  _convert() is
│  not needed —     │  Node.js script   │  reportlab       │  pptxgenjs script
│  generate() is    │  generation       │  Flowables       │  generation
│  overridden       │                   │                  │
└───────────────────┴───────────────────┴──────────────────┘
```

---

## Base Class: `OutputAgent` — `base.py` (1109 lines)

### Class Hierarchy

```
OutputAgent (ABC)
├── MarkdownAgent  (markdown_agent.py)
├── DocxAgent      (docx_agent.py)
├── PdfAgent       (pdf_agent.py)
└── PptxAgent      (pptx_agent.py)
```

### Template Method: `generate(**kwargs) -> Path`

The `generate()` method (line 941) orchestrates a fixed pipeline, calling hooks that
subclasses override. Subclasses never override `generate()` itself — they override
`_prepare_content()` and `_convert()` (and `_load_plan()` as required by the ABC).

**Pipeline steps:**

```
generate()
  │
  ├─ 1. _get_content()
  │      ├─ Tries: output_dir/{analysis_id}-*.md (pre-rendered markdown)
  │      └─ Falls back: _build_content_from_plan(plan) — builds markdown from
  │                      plan sections/title/audience/diagrams
  │
  ├─ 2. _append_feedback(content)
  │      ├─ Injects _build_section_feedback_block() if per-section feedback exists
  │      └─ Injects _build_review_feedback_block() if review_feedback is set
  │
  ├─ 3. _prepare_content(content)
  │      └─ Hook for format-specific preprocessing.
  │         Default: returns content unchanged.
  │         PptxAgent: parses markdown into slides, selects color palette.
  │
  ├─ 4. _generate_and_log_diagrams(diagrams_dir)
  │      ├─ Loads plan + technical facts from KB
  │      ├─ Calls _generate_diagrams_for_facts(facts, ...)
  │      │    ├─ Tries LLMDiagramGenerator (preferred)
  │      │    └─ Falls back to PlantUMLGenerator (template-based)
  │      └─ Produces architecture, flow, class diagrams as PNG images
  │
  └─ 5. _convert(prepared_content, output_file, diagrams_dir)  ← ABSTRACT
         └─ Implemented by each subclass for format-specific output
```

### Abstract Methods

| Method | Line | Purpose |
|--------|------|---------|
| `_load_plan()` | 1084 | Load the format-specific `DocumentPlan` from KB (e.g. `plan_docx.json`) |
| `_convert(content, output_file, diagrams_dir)` | 1095 | Perform format-specific conversion and write output file |

### Shared Data Loading

| Method | What it loads | Source |
|--------|---------------|--------|
| `_load_validated_elements()` | Set of valid code element names | `kb/ast_head/*.json` |
| `_load_technical_facts()` | `list[TechnicalFact]` | `kb/technical_facts/*.json` |
| `_load_ast_classes()` | Class metadata (name, methods, attributes, bases) | `kb/ast_head/*.json` |
| `_load_changed_classes()` | Set of class names with changes | `kb/semantic_diff/*.json` |
| `_load_section_feedback()` | Dict of section_title→feedback_text | KB metadata (via `KnowledgeBaseManager`) |
| `_load_skill(skill_name)` | Content of `SKILL.md` for format-specific docs | `ggdes/skills/{skill_name}/SKILL.md` |

### Diagram Generation

`_generate_diagrams_for_facts()` (line 500) is the main entry point:

1. **Primary path:** `LLMDiagramGenerator` — uses LLM to generate PlantUML from facts
   (architecture, flow, class diagrams).
2. **Fallback path:** `PlantUMLGenerator` — template-based generation using
   `_generate_architecture_diagram()`, `_generate_flow_diagram()`, `_generate_class_diagram()`.

All diagram generation has **caching** support via `DiagramCache` (keyed by analysis_id
+ diagram type + fact content hash).

**Element name validation:** `_validate_element_name()` cross-references element names
against AST data before generating PlantUML, preventing hallucinated references.

### Other Shared Infrastructure

- `_build_review_feedback_block()` — Formats review feedback in a boxed block.
- `_build_section_feedback_block()` — Formats all per-section feedback.
- `_extract_attributes_from_source()` — Regex-based attribute extraction from source code.
- `output_dir` property — Computes path as `~/ggdes-output/{analysis_id}[/{revision}]`.

---

## Format-Specific Agents

### MarkdownAgent — `markdown_agent.py` (588 lines)

**Overrides `generate()`** (not just `_convert()`). This is the only agent that does
not use the template method's `_convert()` hook because markdown is the "native" format —
there's no conversion step.

**Generation pipeline:**
1. Loads `plan_markdown.json` from KB.
2. For each section in the plan, calls `_generate_section()`:
   - Loads relevant facts for that section.
   - Builds a prompt with fact descriptions, source code snippets, before/after code
     comparisons, usage examples, and section-specific feedback.
   - Passes `code_snippets`, `before_after_code`, and `usages` (populated by
     TechnicalAuthor) through to the LLM as **ground truth** — the LLM is instructed
     to ONLY reference the provided actual source code.
   - Calls LLM via `self.llm.chat()` with temperature 0.4.
3. `_build_markdown()` assembles the final document:
   - YAML front matter (`title`, `audience`, `analysis_id`, `generated`)
   - Executive summary (from user context)
   - Table of contents (auto-generated from sections)
   - Sections with body content
   - Diagrams section: auto-generated images (PNG via PlantUML) + plan diagrams
     (PlantUML code blocks) + failed diagram debugging notes
   - Footer with generation metadata
4. `_save_markdown()` writes to `{analysis_id}-{safe_title}.md`.
5. Optionally renders to PNG images via `MarkdownToPngRenderer` (Playwright).

**Diagram handling:** Both auto-generated diagrams (from facts via
`_generate_diagrams_for_facts`) and plan-specified diagrams (PlantUML code) are
embedded. Auto-generated diagrams appear as markdown image links; plan diagrams
appear as PlantUML code blocks. Failed diagrams are noted with fix instructions.

**Key difference:** MarkdownAgent does NOT use `_convert()`. It overrides `generate()`
entirely because the generation is an LLM-driven write, not a format conversion.

---

### DocxAgent — `docx_agent.py` (365 lines)

**Technology:** [docx-js](https://github.com/dolanmedia/docx) (Node.js) with pandoc
fallback. Skill documentation loaded from `ggdes/skills/docx/SKILL.md`.

**`_convert()` pipeline:**
1. `_generate_docx_script()` — Generates a Node.js script that uses the `docx` library
   to create a Word document:
   - Document styles: Arial 12pt default, heading levels with proper spacing.
   - Numbering: bullet list and numbered list configurations.
   - Page setup: letter size, 1-inch margins.
   - Section parsing: `_parse_content_to_sections()` converts markdown lines to
     docx-js `Paragraph` objects handling H1/H2/H3, bullets, numbered lists, and
     body text.
   - Diagram embedding: up to 3 PNG images embedded via `ImageRun`.
2. Writes script to temp `.js` file and runs `node <script>`.
3. On success, validates with optional skill validation script.
4. On failure (missing Node.js, script error, or non-zero exit), falls back to pandoc.

**Markdown→DOCX conversion via `_parse_content_to_sections()`:**
- `# title` → `HeadingLevel.HEADING_1`
- `## title` → `HeadingLevel.HEADING_2`
- `### title` → `HeadingLevel.HEADING_3`
- `- item` / `* item` → bullet list (reference "bullets")
- `1. item` → numbered list (reference "numbers")
- Plain text → body paragraph

**Fallback (`_fallback_to_pandoc`):**
```python
pandoc temp.md -o output.docx
```

---

### PdfAgent — `pdf_agent.py` (297 lines)

**Technology:** [reportlab](https://www.reportlab.com/) (Python) with pandoc fallback.
Skill documentation loaded from `ggdes/skills/pdf/SKILL.md`.

**`_convert()` pipeline:**
1. Tries `_generate_with_reportlab(content, output_file, diagrams_dir)`.
2. On ImportError or any Exception, falls back to pandoc.

**Reportlab generation (`_generate_with_reportlab`):**
- `SimpleDocTemplate` with letter page, 72pt margins.
- Custom paragraph styles:
  - `CustomTitle` — H1 equivalent, 24pt, centered.
  - `CustomHeading2` — 16pt with spacing.
  - `CustomHeading3` — 14pt with spacing.
  - `CustomBody` — 11pt, 14pt leading.
  - `BulletList` — with left indent.
  - `DiagramCaption` — 10pt, centered, gray.
- Markdown→PDF parsing (same pattern as DocxAgent):
  - `# title` → `CustomTitle`
  - `## title` → `CustomHeading2`
  - `### title` → `CustomHeading3`
  - `- item` → bullet paragraph with `•` prefix
  - Plain text → `CustomBody`
- Diagram section: up to 3 PNG images embedded at 6×4 inches with captions.
- XML escaping via `_escape_xml()` for safe text rendering.

**Fallback (`_fallback_to_pandoc`):**
```python
pandoc temp.md -o output.pdf --pdf-engine=xelatex
# Falls back to: pandoc temp.md -o output.pdf  (without xelatex)
```

---

### PptxAgent — `pptx_agent.py` (899 lines)

**Technology:** [pptxgenjs](https://github.com/gitbrent/PptxGenJS) (Node.js) with
pandoc fallback. Skill documentation loaded from `ggdes/skills/pptx/SKILL.md`.

**This is the most feature-rich output agent**, with a sophisticated slide layout system.

**`_prepare_content()` — preprocessing:**
1. `_select_palette(content)` — keyword-based color palette selection:
   - `security/auth/encrypt` → "ocean" (blue)
   - `performance/speed` → "coral" (warm)
   - `refactor/cleanup` → "forest" (green)
   - `ui/frontend/ux` → "berry" (purple)
   - `data/database/storage` → "teal"
   - Default → "midnight" (dark blue)
2. `_parse_content_to_slides(content)` — Parses markdown into a list of slide dicts
   with fields: `type`, `title`, `bullets[]`, `content[]`, `subheadings[]`.
3. `_classify_slide_layouts(slides)` — Assigns a layout to each slide:

| Layout | When used | Visual style |
|--------|-----------|-------------|
| `title_dark` | First slide (type=title) | Dark background, large Georgia title, accent bar |
| `icon_text_rows` | ≥4 bullets | Colored circles + text rows, header bar |
| `two_column` | Mixed bullets + content | Left accent bar, divider, right column card |
| `grid_cards` | ≥2 subheadings | 2-column card grid with left accent strip |
| `stat_callouts` | Few short bullets | Large stat numbers on dark cards |
| `bullets_with_accent` | Default / few bullets | Clean bullets with left accent bar |

**`_convert()` — PPTX generation:**
1. Calls `_generate_pptx_script()` which builds a Node.js script:
   - Creates pptxgenjs presentation (16:9, metadata).
   - Iterates through slides, generating JavaScript for each based on layout type.
   - Rotates diagram images: every 3rd content slide gets a diagram overlay.
   - Remaining diagrams get dedicated full-slide dark-background slides.
2. Writes script to temp `.js` file and runs `node <script>`.
3. On failure, falls back to pandoc.

**Slide layout generators (all in `pptx_agent.py`):**

| Method | Layout | Visual elements |
|--------|--------|----------------|
| `_title_slide()` | title_dark | Dark background, Georgia title, accent bar, subtitle |
| `_icon_text_rows_slide()` | icon_text_rows | Header bar, oval icons, text rows |
| `_two_column_slide()` | two_column | Left accent bar, bullet list, right card |
| `_grid_cards_slide()` | grid_cards | 2-column cards with left accent strip |
| `_stat_callouts_slide()` | stat_callouts | Dark stat cards with accent labels |
| `_bullets_with_accent_slide()` | bullets_with_accent | Left accent bars per bullet |
| `_diagram_overlay_slide()` | diagram | Image with header |
| `_full_diagram_slide()` | full diagram | Dark background, centered image |

**Color palettes (8 built-in):**

| Name | Primary | Vibe |
|------|---------|------|
| midnight | `#1E2761` | Executive default |
| forest | `#2C5F2D` | Refactoring/cleanup |
| coral | `#F96167` | Performance |
| terracotta | `#B85042` | General |
| ocean | `#065A82` | Security/auth |
| charcoal | `#36454F` | Neutral |
| teal | `#028090` | Data/storage |
| berry | `#6D2E46` | UI/frontend |

**Fallback (`_fallback_to_pandoc`):**
1. `_create_slide_markdown()` — Flattens content into slide-friendly format
   (groups content with `---` separators).
2. `pandoc temp.md -o output.pptx`

---

## Content Source Flow

```
Pre-rendered Markdown (if exists)
    │
    ├── DocxAgent._get_content()
    ├── PdfAgent._get_content()
    └── PptxAgent._get_content()
              │
              ▼
         Markdown string
              │
              ▼
         _append_feedback()
              │
              ▼
         _prepare_content()    ← PptxAgent: parses into slides
              │
              ▼
         _convert()            ← Each format's conversion
              │
              ▼
         Output file (.docx / .pdf / .pptx / .md)
```

When pre-rendered markdown is not available, `_build_content_from_plan()` reconstructs
markdown from the `DocumentPlan`'s sections (title, audience, section titles/descriptions, diagram list).

---

## Skill Architecture

Each output agent loads its format-specific skill at init time:

| Agent | Skill path | Content |
|-------|-----------|---------|
| DocxAgent | `ggdes/skills/docx/SKILL.md` | docx-js patterns, styling, tables, formatting |
| PdfAgent | `ggdes/skills/pdf/SKILL.md` | reportlab patterns, page layout, images |
| PptxAgent | `ggdes/skills/pptx/SKILL.md` | pptxgenjs patterns, slide design, 6x6 rule |

Skills are loaded via `OutputAgent._load_skill()` → `skill_utils.load_skill()` which
searches 4 filesystem paths for `ggdes/skills/{name}/SKILL.md`.

The skill content is stored as `self.skill_content` on each agent. Currently, skills
serve as passive documentation — the Node.js scripts and reportlab code are hardcoded
in the agents themselves, with skills available as reference.

---

## Package Init — `__init__.py`

Exports all output agents:
```python
__all__ = ["OutputAgent", "MarkdownAgent", "DocxAgent", "PptxAgent", "PdfAgent"]
```

---

## Invocation Pattern

```python
agent = DocxAgent(repo_path, config, analysis_id, review_feedback)
output_path = agent.generate(auto_generate_diagrams=True)
# Output: ~/ggdes-output/{analysis_id}/{analysis_id}-document.docx
```

Each agent creates its output in a versioned directory:
- Base: `~/ggdes-output/{analysis_id}/`
- With revision: `~/ggdes-output/{analysis_id}/{revision}/`

---

## Key Design Decisions

1. **Template Method** — The fixed `generate()` pipeline ensures consistency across all
   four formats. Subclasses only implement the conversion step, plus optional preprocessing.

2. **Markdown as pivot format** — All non-markdown agents consume markdown content
   (pre-rendered or built from plan), then convert it to their target format.

3. **Dual-path diagram generation** — LLM-driven (richer, context-aware) first, with
   template-based PlantUML fallback. Both paths cache results.

4. **Feedback injection** — Both overall review feedback and per-section feedback are
   appended to the content before conversion. This means feedback can drive changes
   without re-running the LLM (docx/pdf/pptx just include it as text; the format-specific
   code renders it).

5. **Node.js dependency** — Both DOCX and PPTX agents require Node.js with `docx` and
   `pptxgenjs` packages. Both gracefully fall back to pandoc when Node.js is unavailable.
