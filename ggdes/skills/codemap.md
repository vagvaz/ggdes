# ggdes/skills/

## Responsibility

Skill documentation system for GGDes agents. Each skill is a `SKILL.md` file that provides domain expertise, language expertise, or output-format-specific guidelines. Skills are loaded by agents and injected into LLM system prompts at runtime, giving the LLM contextual knowledge for better code understanding and document generation.

## Directory Structure

```
ggdes/skills/
├── codemap.md                    ← This file
├── python-expert/
│   └── SKILL.md                  ← Python programming expertise
├── cpp-expert/
│   └── SKILL.md                  ← C++ programming expertise
├── doc-coauthoring/
│   └── SKILL.md                  ← Collaborative document authoring workflow
├── markdown/
│   └── SKILL.md                  ← Markdown output format guidelines
├── docx/
│   ├── SKILL.md                  ← DOCX creation/editing/analysis guide (large — 660 lines)
│   ├── codemap.md
│   ├── LICENSE.txt
│   └── scripts/                  ← Python helpers for docx operations
│       ├── __init__.py
│       ├── accept_changes.py     ← Accept tracked changes via LibreOffice
│       ├── comment.py            ← Add/manage comments in docx XML
│       └── office/               ← Office file utilities (unpack, pack, validate, schemas)
├── pdf/
│   ├── SKILL.md                  ← PDF processing guide (pypdf, pdfplumber, reportlab)
│   ├── codemap.md
│   ├── LICENSE.txt
│   ├── forms.md                  ← PDF form filling guide
│   ├── reference.md              ← Advanced reference (pypdfium2, pdf-lib)
│   └── scripts/                  ← PDF scripts (extraction, OCR, form filling)
├── pptx/
│   ├── SKILL.md                  ← PPTX creation guide with design ideas
│   ├── codemap.md
│   ├── LICENSE.txt
│   ├── editing.md                ← Template-based editing workflow
│   ├── pptxgenjs.md              ← Creating from scratch with pptxgenjs
│   └── scripts/                  ← PPTX scripts (thumbnail, add_slide, clean, office utils)
```

## Design

### Skill Categories

| Category | Skills | Purpose | Loaded By |
|----------|--------|---------|-----------|
| **Language Expertise** | `python-expert`, `cpp-expert` | Best practices, idioms, performance guidance for a programming language | `GitAnalyzer`, `TechnicalAuthor` |
| **Domain Expertise** | `doc-coauthoring` | Structured workflow for co-authoring documentation with users | `TechnicalAuthor` |
| **Format Skills** | `markdown`, `docx`, `pdf`, `pptx` | Medium-specific content guidelines, formatting rules, and technical references | `DocxAgent`, `PdfAgent`, `PptxAgent`, `MarkdownAgent` |

### Skill Loading Mechanism

**Entry point:** `ggdes/agents/skill_utils.py` → `load_skill(skill_name, repo_path)`

Resolution order (first match wins):
```
1. ggdes/skills/{skill_name}/SKILL.md    (relative to skill_utils.py)
2. <parent>/skills/{skill_name}/SKILL.md (one level up)
3. ./ggdes/skills/{skill_name}/SKILL.md  (from CWD)
4. ./skills/{skill_name}/SKILL.md        (from CWD)
```

Each skill directory contains a `SKILL.md` file with YAML front matter (`name`, `description`, optional `license`) followed by Markdown content.

### System Prompt Injection

Skills are injected into agent system prompts using `SystemPromptBuilder` (`ggdes/agents/skill_utils.py`). The builder enforces a strict priority order:

```
1. SKILLS (highest priority)
   ├── Language expertise (python-expert, cpp-expert)
   └── Domain expertise (doc-coauthoring)

2. BASE SYSTEM PROMPT (core instructions)

3. CUSTOM SECTIONS (additional context)

4. USER GUIDANCE (marked as "VERY IMPORTANT")
   ╔══════════════════════════════════════════╗
   ║  ⚠️  VERY IMPORTANT  ⚠️                 ║
   ║  USER REQUIREMENTS (MUST FOLLOW)        ║
   ╚══════════════════════════════════════════╝
```

Format skills (docx, pdf, pptx) are loaded by their respective output agents in `ggdes/agents/output_agents/`:
- `DocxAgent._load_skill("docx")` — 660-line guide with docx-js JavaScript API, XML editing, tracked changes, comments
- `PdfAgent._load_skill("pdf")` — pypdf/pdfplumber/reportlab API reference, form filling, OCR guidance
- `PptxAgent._load_skill("pptx")` — pptxgenjs API, design ideas, color palettes, visual QA workflow

Language skills are detected automatically via `detect_primary_language(repo_path)` which counts file extensions and maps to skill names via `get_expert_skill_for_language()`.

## Flow

```
Agent initialization
      │
      ▼
  _load_skill(skill_name)
      │
      └── load_skill(skill_name, repo_path)
              │
              ├── Search possible SKILL.md locations
              │
              └── Return content or None
                      │
                      ▼
  SystemPromptBuilder()
      │
      ├── .add_skill("LANGUAGE EXPERTISE", skill_content)
      ├── .set_base_prompt(agent_system_prompt)
      ├── .add_section(title, content)
      ├── .set_user_guidance(user_context)
      │
      └── .build()
              │
              └── Combined system prompt sent to LLM
```

## Integration

- **Language skills** (`python-expert`, `cpp-expert`): Loaded by `GitAnalyzer` (at line 116) and `TechnicalAuthor` (at line 96) via auto-detection or explicit config
- **Domain skill** (`doc-coauthoring`): Loaded by `TechnicalAuthor` (at line 83) for collaborative doc writing workflows
- **Format skills** (`docx`, `pdf`, `pptx`): Loaded by their respective output agents during `__init__` and stored as `self.skill_content`; later injected into the LLM prompt during document generation
- **Markdown skill**: Used by `MarkdownAgent` for content guidelines and syntax reference
- Each skill directory may also contain scripts, templates, schemas, and supplemental documentation (e.g., `editing.md`, `forms.md`, `reference.md`, `LICENSE.txt`)
