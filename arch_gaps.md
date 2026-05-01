# Architecture Gaps — Deepening Opportunities

This document captures architectural friction points in GGDes, framed as **deepening opportunities** using the vocabulary of module depth, seams, adapters, leverage, and locality.

See [LANGUAGE.md](LANGUAGE.md) for full definitions (to be created).

---

## 1. Pipeline God Module vs. Stage Runners

**Files:** `ggdes/pipeline.py` (1234 lines)

**Problem:** The `AnalysisPipeline` module bundles three distinct responsibilities behind a single interface, violating locality:
- **Orchestration** — sequencing, parallel group logic, stage state tracking (lines 78–383)
- **Stage implementation** — nine `_run_*` methods (lines 385–1234), each up to ~180 lines
- **Tool/service building** — `_build_tool_executor()`, `_get_changed_files_detailed()`, etc.

**Deletion test:** Delete `pipeline.py`. The orchestration vanishes, but each `_run_*` method does real work (instantiate agents, read artifacts, manage KB state). That work would reappear in nine callers. The module earns its keep, but the interface is nearly as wide as the implementation — adding a new stage means modifying this one file.

**Solution:** Extract each stage runner into its own module under `ggdes/pipeline/stages/` (e.g., `stages/worktree_setup.py`, `stages/git_analysis.py`), leaving `pipeline.py` as a pure orchestrator that iterates over stage objects with a common interface (`run(metadata, kb) -> bool`).

**Benefits:**
- **Locality:** Changing how `technical_author` runs means editing one focused module instead of scrolling through 1234 lines. Bugs in stage X stay in stage X's file.
- **Leverage:** The orchestration interface shrinks from "know all 9 stage signatures" to "know stage ordering and `run()` signature." A `ParallelStage`/`SequentialStage` wrapper handles threading.
- **Seam:** Each stage becomes independently testable: inject a `KnowledgeBaseManager` with known artifacts, call `run()`, assert output. Currently, testing a single stage requires the full pipeline.

---

## 2. Web Monolith: Unpack `web/__init__.py`

**Files:** `ggdes/web/__init__.py` (~2200 lines)

**Problem:** This single module mixes four distinct concerns:
- FastAPI route definitions (~20 routes)
- Inline HTML templates (~460 lines as a Python string constant)
- WebSocket broadcast logic
- All handler implementations

**Deletion test:** Delete this file and the web UI disappears entirely — real work. But adding a new page requires the same diffuse pattern: find the right spot, add a decorator, write the handler, append to a giant HTML string.

**Solution:** Split into a router package where each route module declares its own handlers, and templates live in Jinja2 files or static assets. The main `__init__.py` becomes only an app factory + middleware.

**Benefits:**
- **Leverage:** Adding `/api/analyses/{id}/foo` means adding `routes/foo.py`, not inserting into a 2200-line file.
- **Locality:** HTML bugs live in template files with IDE support, not in a Python string constant invisible to linters.
- **Seam:** The app factory becomes an adapter seam — mount routers under a prefix, test with `TestClient`, swap templates without touching API logic.

---

## 3. Output Agent Duplication: Shallow Format Adapters

**Files:**
- `ggdes/agents/output_agents/docx_agent.py` (421 lines)
- `ggdes/agents/output_agents/pdf_agent.py` (346 lines)
- `ggdes/agents/output_agents/pptx_agent.py` (417 lines)
- `ggdes/agents/output_agents/base.py` (695 lines)

**Problem:** The three format-specific agents share ~70% of their `generate()` method logic: load plan → load technical facts → generate diagrams → load feedback → convert to format. Each re-reads facts from disk independently. PptxAgent duplicates fact-loading code instead of calling `_load_technical_facts()` from the base. The base class interface is wide (18+ public methods) and subclasses are shallow — the unique part per agent is just the conversion step.

**Deletion test:** Delete DocxAgent. PDF and PPTX still work. Each agent stands alone, but that's the problem — they're independent when they should share expensive preparation (fact loading, diagram generation).

**Solution:** Consolidate the preparation phase into a single `DocumentRenderer` module behind a seam like `render_plan_to_markdown(plan_id) -> MarkdownDocument`. All three format agents consume the rendered markdown. OR: keep the agents but move fact loading and diagram generation into the base with memoization so each diagram is generated once per analysis.

**Benefits:**
- **Locality:** The decision "what facts go into a diagram" lives in one place, not four.
- **Leverage:** Adding a new format (e.g., HTML) means writing only the conversion step.
- **Seam:** `MarkdownDocument` becomes an interface that format-specific adapters satisfy. One adapter (markdown) is hypothetical; two (docx, pdf) make it real; three (pptx) confirm it.

---

## 4. Playwright Browser: Expensive Resource with No Reuse

**Files:** `ggdes/rendering/markdown_to_png.py`

**Problem:** `_render_html_to_png_async` launches a new Chromium instance per call. When rendering a multi-section document with `sections=True`, each section gets its own browser process (~3-6s startup + ~50MB per instance). The interface (`render(path, sections=False)`) looks simple but hides expensive resource management — a **shallow module**.

**Solution:** Maintain a cached browser instance (module-level singleton or connection pool). Add `async def start() / close()` lifecycle methods.

**Benefits:**
- **Leverage:** Same interface but 5-10x faster for multi-section renders and 10x less memory churn.
- **Locality:** Resource management concentrated in one place rather than implicitly per-call.

---

## 5. Semantic Diff: Python-Only Nodes Masquerading as Cross-Language Analysis

**Files:** `ggdes/semantic_diff.py` (983 lines)
**Related:** `ggdes/parsing/ast_parser.py` (756 lines — has tree-sitter for Python + C++, unused here)

**Problem:** All four `_detect_*` methods use Python stdlib `ast.parse()`. For any non-Python file, `SyntaxError` is caught silently, returning empty results. The four methods are **shallow** — each is a simple node counter (count functions, docstrings, if/for/while, try/except) with the same structure wrapped in different names.

**Deletion test:** Delete any single `_detect_*` method. Its analysis is lost entirely — no caller recomputes it. But deleting all four and replacing with a language-routed adapter pattern would produce *more* coverage.

**Solution:** Introduce a **language adapter** seam. Each method should accept a parsed AST from the appropriate parser for the language. `ASTParser` already does tree-sitter parsing for Python and C++ — route through it.

**Benefits:**
- **Leverage:** Adding JS/TS support means writing one new adapter, not duplicating all four detection methods.
- **Seam:** A `LanguageAdapter` interface becomes real with two implementations (Python, C++). Currently: zero adapters — detection calls `ast.parse()` directly.
- **Locality:** Language-specific quirks stay in their adapter file. C++ detection bugs don't affect Python results.

---

## 6. Diagram Generation: Fact-Relationship Fabrication

**Files:**
- `ggdes/diagrams/__init__.py` (523 lines)
- `ggdes/agents/output_agents/base.py` (lines 595–923)

**Problem:** Two layers of diagram generation. `diagrams/__init__.py` provides `generate_class_diagram()` etc., but these are string templating functions (format PlantUML from pre-structured dicts). The *real* work is in `base.py`, where `_generate_diagrams_for_facts()` extracts components from technical facts and **fabricates relationships** (e.g., connecting components sequentially: `comp[0] → comp[1] → comp[2]`). Class diagrams generate empty method/attribute lists because AST data isn't correlated with fact entries.

**Deletion test:** Delete `diagrams/__init__.py` and inline PlantUML strings in `base.py`. Nothing meaningful lost — it was string formatting. The extraction work is entirely in `base.py`.

**Solution:** Merge both layers into one module that both extracts data *and* formats it, or make `diagrams/__init__.py` the extraction engine with access to AST data and facts. The current split is a **false seam** — two modules that look independent but are tightly coupled through the fact schema.

**Benefits:**
- **Locality:** All diagram logic (extraction + formatting) in one module, eliminating "which file do I edit?" overhead.
- **Leverage:** A consolidated module could produce richer class diagrams (actual methods/attributes from AST) and architecture diagrams with real dependency data.

---

## 7. Schema Mismatch: Broken Consumer Contract

**Files:**
- `ggdes/semantic_diff.py` — produces `"removed"` in `change_category`
- `ggdes/agents/output_agents/base.py:328` — checks for `"deleted"`

**Problem:** `_load_changed_classes()` checks `change_category in ("added", "modified", "deleted")`, but `SemanticChangeElement` uses `"removed"`. The "removed" class detection is **dead code** — never matches. No test asserts this path.

This is a **shallow mistake**: both sides describe "what changed," but a one-character enum mismatch breaks the contract silently. The producer interface and consumer interface have diverged with zero verification.

**Solution:** Align the enum value (pick one, update the other) and add a test that verifies round-trip: produce a `SemanticDiffResult` with a removed class → feed to `_load_changed_classes()` → assert it's in the result.

**Benefits:**
- **Leverage:** One test covers a contract with zero verification that silently degrades output.
- **Locality:** A string change in one file. The test localizes the contract so future refactors can't break it again.

---

## 8. Change Filter: Redundant Diff Computation

**Files:**
- `ggdes/pipeline.py:584–590` (change_filter stage)
- `ggdes/agents/change_filter.py` (387 lines)

**Problem:** The change filter stage creates a new `GitAnalyzer` instance and calls `get_diff()` to recompute the git diff already computed in `_run_git_analysis`. The earlier result was never persisted. Diff is deterministic for a given (repo, commit_range), so this is a **shallow inefficiency**.

**Solution:** Store the computed diff in the KB during git_analysis (e.g., `git_analysis/diff.txt`), and have change_filter read it from there instead of calling git again.

**Benefits:**
- **Locality:** The diff is computed once and cached. The cost of reading git (subprocess + possibly remote fetch) is paid once per analysis.
- **Leverage:** Downstream debugging or review features could also read the cached diff without running git again.

---

## 9. KB Module: Tightly Coupled to Stage Names

**Files:** `ggdes/kb/manager.py` (575 lines)

**Problem:** `KnowledgeBaseManager` hard-codes stage names as constants that mirror the pipeline's internal naming. The KB directory structure (`git_analysis/`, `ast_base/`, `semantic_diff/`) is locked to pipeline stage names. Renaming a stage requires changing two modules.

**Deletion test:** Delete the KB manager. The pipeline loses all persistence — but the KB manager isn't doing complex logic; it's file-path templating with constants. The "which file do I write to?" complexity would reappear in every stage.

**Solution:** Parameterize stage names. The pipeline passes a `stage_name → artifact_path` mapping, or each stage resolves its own paths from the analysis ID. The KB manager becomes a flat key-value store: `save(analysis_id, key, data)` / `load(analysis_id, key)`.

**Benefits:**
- **Leverage:** Adding a new stage doesn't require adding a constant to the KB manager. The interface shrinks.
- **Locality:** If a stage changes its output format/location, it changes its own path resolution, not a shared constants file.

---

## Priority Guide

| # | Opportunity | Effort | Leverage | Risk |
|---|-------------|--------|----------|------|
| 1 | Pipeline stage extraction | ✅ **Done** | — | — |
| 2 | Web module split | Medium | High | Low — route organization |
| 3 | Output agent consolidation | ✅ **Done** | — | — |
| 4 | Playwright browser reuse | Small | Medium | Low — singleton pattern |
| 5 | Semantic diff language adapters | Medium | High | Medium — changes detection |
| 6 | Diagram generation merge | Medium | Medium | Low — internal refactor |
| 7 | Schema mismatch fix | ✅ **Done** | — | — |
| 8 | Diff caching | ✅ **Done** | — | — |
| 9 | KB stage name decoupling | Small | Low | Low — path abstraction |
