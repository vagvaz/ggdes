# Output Agents — Codemap

## Responsibility

Format-specific document generators that consume document plans (produced by the
Coordinator) and produce final output files in Markdown, DOCX, PDF, and PPTX formats.
All output agents share a common base class that implements the **Template Method pattern**
for document generation.

```
                              ┌──────────────────────────────┐
                              │  Coordinator (optional)      │
                              │  Shared context + facts      │
                              └──────────┬───────────────────┘
                                         │
                  ┌──────────────────────┼──────────────────────┐
                  │                      │                      │
          MarkdownAgent            PptxAgent          DocxAgent/PdfAgent
          (self-plans via          (self-generates       (consume markdown
           LLM, no coordinator)     slide content)        from agent above)
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                  OutputAgent (abstract base)                     │
│                                                                  │
│  generate() ← template method                                   │
│    ├─ 0. _ensure_plan()        — load or LLM-generate plan      │
│    │                             (MarkdownAgent only)            │
│    ├─ 1. _get_content()        — load markdown from file,       │
│    │                             build from plan, or generate   │
│    │                             via LLM (PptxAgent override)    │
│    ├─ 2. _append_feedback()    — inject review/section          │
│    │                             feedback                        │
│    ├─ 3. _prepare_content()    — optional preprocessing         │
│    │                             (pptx: slides+palette)          │
│    ├─ 4. _generate_and_log_   — generate architecture,         │
│    │     diagrams()              flow, class diagrams            │
│    └─ 5. _convert()            — format-specific output         │
│                                  (abstract)                     │
├───────────────────┬───────────────────┬──────────────────────┐  │
│                   │                   │                      │  │
│  MarkdownAgent    │  DocxAgent        │  PdfAgent            │  PptxAgent
│  (self-plans,     │  (docx-js/        │  (reportlab/         │  (pptxgenjs/
│   LLM section     │   pandoc)         │   pandoc)            │   pandoc)
│   gen, cache,     │                   │                      │
│   code valid.)    │                   │                      │
│                   │                   │                      │
│  _convert() is    │  _convert() is    │  _convert() is       │  _convert() is
│  not needed —     │  Node.js script   │  reportlab           │  pptxgenjs script
│  generate() is    │  generation       │  Flowables           │  generation
│  overridden       │                   │                      │
└───────────────────┴───────────────────┴──────────────────────┘
```

---

## Base Class: `OutputAgent` — `base.py` (1131 lines)

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
| `_load_user_context()` | User context dict (audience, purpose, focus) | `shared_context/context.json` → format-specific plan (backward compat) → pipeline metadata |

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

### MarkdownAgent — `markdown_agent.py` (1134 lines)

**Overrides `generate()`** (not just `_convert()`). This is the only agent that does
not use the template method's `_convert()` hook because markdown is the "native" format —
there's no conversion step. The agent generates its own document plan via LLM when no
pre-saved plan exists, making it **self-planning** — it does not depend on the Coordinator.

#### Self-Planning (`_ensure_plan()` / `_generate_plan()`)

1. `_ensure_plan()` (line 126) tries `_load_plan()` first; if no `plan_markdown.json`
   exists, calls `_generate_plan()`.
2. `_generate_plan()` (line 139) loads shared context (technical facts, user context,
   semantic diff) and asks the LLM to propose a section structure via the
   `"output"` / `"markdown_plan"` prompt template.
3. The LLM response is extracted as JSON (via `_extract_json()` with 3 strategies:
   raw parse, ` ```json ` fence, outermost `{…}` braces).
4. If parsing fails, `_build_fallback_plan()` creates a category-based plan from facts.
5. The generated `DocumentPlan` is saved to `kb/plans/plan_markdown.json` so downstream
   code (diagram generation, etc.) can load it.

#### Section Generation Pipeline (`_generate_section()` at line 595)

Each section is an independent parallel LLM call via `asyncio.gather()`:

1. **Load facts** — loads `TechnicalFact` objects referenced by the section plan.
2. **Build structured prompt blocks:**
   - `_build_source_code_block()` — actual source code snippets (budget: 2500 chars).
   - `_build_before_after_block()` — before/after code comparisons (budget: 2000 chars).
   - `_build_usage_examples_block()` — real call-site usages (budget: 1500 chars).
   - Section feedback block (if per-section feedback exists).
   - All blocks are rendered via the `"output"` / `"markdown_section"` YAML template.
3. **Content caching** — a SHA-256 hash of `(section_title + fact_ids + code_references)`
   serves as the cache key. Cached sections are stored in `kb/cache/sections/{hash}.txt`
   via `_cache_dir()`, `_load_cached_section()`, `_save_cached_section()`.
4. **Token estimation & chunking** — if `estimated_tokens > max_section_tokens` (from config)
   and there are more than 3 facts, `_generate_section_chunked()` splits facts into
   batches of 4, generating each batch as an independent LLM call, then concatenates
   with `\n\n---\n\n` separators.
5. **LLM call with retry** — `_call_llm_with_remediation()` (line 705) wraps the LLM call:
   - Uses `async_chat()` if available, else `chat()`.
   - Retries once on empty response or exception (2 attempts total).
   - On double failure, returns a minimal fallback (`_This section could not be generated...`).
6. **Code reference validation** — `_validate_section_output()` (line 772) runs the
   generated section through `CodeReferenceValidator` with the section's `code_references`
   as the expected file list. On validation failure, the validator auto-corrects the
   output (up to 1 correction pass). If the validator is unavailable, validation is
   silently skipped.
7. **Cache save** — the validated response is persisted for reuse.

#### Final Assembly (`_build_markdown()` at line 981)

1. **YAML front matter** — `title`, `audience`, `analysis_id`, `generated` timestamp.
2. **Executive summary** — from user context (purpose + focus areas).
3. **Table of contents** — auto-generated from section titles with anchor links;
   includes diagram section if any diagrams exist.
4. **Sections** — each section rendered with `## {title}` followed by LLM-generated content.
5. **Diagrams section:**
   - Auto-generated diagrams (PNG via `_generate_diagrams_for_facts`) embedded as image links.
   - Plan-specified diagrams rendered as PlantUML code blocks.
   - Failed diagrams saved as `failed_*.puml` with fix instructions.
6. **Footer** — generation metadata.

#### Diagram Handling

Both auto-generated diagrams (from facts via `_generate_diagrams_for_facts`) and
plan-specified diagrams (PlantUML code) are embedded. Auto-generated diagrams appear
as markdown image links; plan diagrams appear as PlantUML code blocks. Failed diagrams
are noted with `failed_*.puml` files and fix instructions.

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
2. Writes script to temp `.js` file and runs `node <script>` with
   `env={**os.environ, "NODE_PATH": str(self.repo_path / "node_modules")}` so
   Node.js can resolve the `docx` module from the project's `node_modules`
   regardless of the working directory (`import os` added at module top).
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

### PptxAgent — `pptx_agent.py` (1062 lines)

**Technology:** [pptxgenjs](https://github.com/gitbrent/PptxGenJS) (Node.js) with
pandoc fallback. Skill documentation loaded from `ggdes/skills/pptx/SKILL.md`.

**This is the most feature-rich output agent**, with a sophisticated slide layout system.

**`_get_content()` override (line 123):** PptxAgent overrides `_get_content()` to always
generate **slide-native** content via LLM instead of falling back to shared markdown.
The method calls `_generate_slide_content()` which:
1. Loads shared context (technical facts, user context) via `Coordinator.load_shared_context()`.
2. Builds a prompt using the `"output"` / `"pptx_slides"` template with fact summaries,
   audience, purpose, and example bullets drawn from actual facts.
3. Calls the LLM (2 retries with fallback) to produce markdown where each `##` heading
   is a slide, following the 6x6 rule (max 6 bullets, ~6 words per bullet).
4. Every slide is expected to have a visual element (diagram reference, architecture
   description, or data callout).
5. On LLM failure, returns placeholder content with a warning.

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
2. Writes script to temp `.js` file and runs `node <script>` with
   `env={**os.environ, "NODE_PATH": str(self.repo_path / "node_modules")}` so
   Node.js can resolve the `pptxgenjs` module from the project's `node_modules`
   regardless of the working directory (`import os` added at module top).
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
                   MarkdownAgent.generate()
                        │
            ┌───────────┴───────────────┐
            │                           │
     _ensure_plan()             plan_diagrams (PlantUML)
            │                           │
     _generate_sections_parallel()      │
     (LLM per section, cached)          │
            │                           │
     _build_markdown()                  │
            │                           │
            ▼                           │
     {analysis_id}-*.md  ◄──────────────┘
     (pre-rendered markdown)
            │
            │
 ├──────────┼──────────┐              ┌─────────────────────┐
 │          │          │              │  PptxAgent._get_content()
 ▼          ▼          ▼              │  (always generates fresh
DocxAgent  PdfAgent  PptxAgent        │   slide-native content
._get()    ._get()   ._get()          │   via LLM — does NOT
  │          │          │             │   consume pre-rendered
  │          │          │             │   markdown)
  │          │          │             └─────────────────────┘
  └──────────┴──────────┘
            │
            ▼
       _append_feedback()
            │
            ▼
       _prepare_content()    ← PptxAgent: parses into slides
            │                           (from its own LLM content)
            ▼
       _convert()            ← Each format's conversion
            │
            ▼
       Output file (.docx / .pdf / .pptx)
```

When pre-rendered markdown is not available, `_build_content_from_plan()` reconstructs
markdown from the `DocumentPlan`'s sections (title, audience, section titles/descriptions, diagram list).
However, this path is rarely used now — MarkdownAgent generates rich content via LLM,
and PptxAgent bypasses markdown entirely in favor of self-generated slide content.

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
