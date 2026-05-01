# Pipeline Improvements — Deepening Opportunities

This document captures architectural improvements for the GGDes documentation generation pipeline (stages 6–9: semantic_diff → technical_author → coordinator_plan → output_generation). Each candidate uses vocabulary from `LANGUAGE.md`: module depth, seams, adapters, leverage, locality.

---

## 1. Shared Fact Cache (Deferred)

Technical facts are loaded from disk independently by four consumers (coordinator, markdown_agent, docx_agent, pdf_agent, pptx_agent). No cross-stage cache exists. Each format agent re-reads the same JSON files.

**Status:** Deferred — not the biggest bottleneck.

---

## 2. AST Over-Loading: Load for Changed Files Only

**Files:** `ggdes/agents/technical_author.py:674–680`

**Problem:** Technical author loads ALL AST elements from both base and head worktrees, then immediately discards elements for files that didn't change. The `_load_ast_data()` interface says "load everything for this variant" but the implementation only needs changed files. The module is **shallow** — the caller must know to filter the result, meaning the interface is nearly as complex as the implementation (you can't call it correctly without also knowing about `_find_changed_elements`).

**Deletion test:** Delete the filtering code in technical_author. AST data for all files would flow into prompts, blowing context limits. The filtering is essential work — but lives in the wrong module (the consumer instead of the loader).

**Solution:** Add a `_load_changed_ast_data(changed_files, variant)` method that reads only the AST JSON files matching the changed file list. Skip the "load all → filter" pattern entirely.

**Benefits:**
- **Leverage:** Interface shrinks from "load everything and figure out what changed" to "load these specific files."
- **Locality:** The "which files are relevant" filter lives in the AST loader, not scattered in the consumer.
- **Performance:** Eliminates irrelevant file I/O and reduces prompt token count.

---

## 3. Serial LLM Calls Blocking Parallel Work

**Files:** `ggdes/agents/technical_author.py` (3 analysis turns), `ggdes/agents/output_agents/markdown_agent.py` (per-section LLM calls)

**Problem:** Three levels of serial LLM calls create a deep sequential bottleneck:
1. Technical author runs 3 analysis turns (API, behavioral, architecture). The parallel path uses `asyncio.gather` but the sequential path still runs them one at a time.
2. Coordinator runs 1 LLM call per format sequentially.
3. Markdown agent runs 1 LLM call per section sequentially (5–10 calls).

The markdown agent alone makes 5–10 LLM calls for a typical document, each with overlapping context (same facts, same code snippets injected per-section).

**Deletion test:** Delete one section's `_generate_section()` call. That section's content vanishes but the rest of the document survives. Sections are independent — a strong signal for parallelization.

**Solution:** 
- Technical author: use the parallel path (already exists in the code).
- Markdown agent: generate all sections in a single structured LLM call, or parallelize via `asyncio.gather()`.
- Coordinator: run format plans in parallel (already done via `asyncio.gather`).

**Benefits:**
- **Leverage:** 5–10 serial calls become ~1–2. Document generation time drops from minutes to tens of seconds.
- **Locality:** The full document structure is visible in one prompt rather than distributed across N calls.

---

## 4. Diagram Generation Once Instead of Per-Format

**Files:** `ggdes/agents/output_agents/base.py:1057–1064` (called by every output agent)

**Problem:** Each output agent calls `_generate_diagrams_for_facts()` independently. Markdown generates diagrams, docx generates the same diagrams again, pdf, pptx. The diagram cache only helps across separate `generate()` calls with the same analysis ID — not within a single pipeline run where each agent has its own cache instance.

**Deletion test:** Delete diagram generation from docx_agent. Word has no diagrams but PDF does. The work is real but repeated unnecessarily.

**Solution:** Generate diagrams once (in the markdown agent or a dedicated early stage) and store paths in the KB `diagrams/` directory. Output agents read references from there instead of regenerating.

**Benefits:**
- **Leverage:** One diagram generation → four consumers share the result.
- **Locality:** Diagram generation logic lives in one place, not duplicated across four adapters.
- **Seam:** The `diagrams/` directory becomes an **interface** between generator and consumers.

---

## 5. Pipeline as Dependency DAG Instead of Serial Chain

**Files:** `ggdes/pipeline.py` (stage ordering), `ggdes/stages/__init__.py` (registry)

**Problem:** The pipeline enforces strict serial ordering even when stages don't truly depend on each other. Currently only `ast_parsing_base` and `ast_parsing_head` run in parallel. Other stages that could overlap:
- `semantic_diff` could overlap with `ast_parsing` (semantic diff has its own AST parsing)
- `coordinator` could start planning once some facts are ready
- Format-specific output could start once its plan is ready (instead of waiting for all plans)

Adding a new stage requires finding its position in the serial order list and modifying the dispatch chain.

**Solution:** Model stages as a **directed acyclic graph (DAG)** where each stage declares its data dependencies. A scheduler resolves which stages are ready to run based on what data has been produced. This is a standard pattern (Airflow, Prefect, Dagster).

**Benefits:**
- **Leverage:** Adding a new stage means registering it + declaring its deps. No ordering decisions needed.
- **Locality:** Data dependency knowledge is in each stage's declaration, not implicit in pipeline ordering.
- **Seam:** The scheduler is an **adapter** — swap eager → lazy → parallel execution without changing stages.

---

## Priority Guide

| # | Opportunity | Effort | Leverage | Risk |
|---|-------------|--------|----------|------|
| 2 | AST over-loading | Small | Medium | Low |
| 3 | Parallel LLM calls | Medium | High | Medium (prompt design) |
| 4 | Single diagram generation | Small | Medium | Low |
| 5 | DAG pipeline model | Large | High | High |
