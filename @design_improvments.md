## GGDes Design Improvement Opportunities

### 1. Modularize the `analyze` Entry Point
- **Current state:** `ggdes/cli.py::analyze` handles configuration, git validation, knowledge-base setup, worktree orchestration, and pipeline execution in one 350+ line function.
- **Issue:** Hard to unit test, difficult to reuse for TUI/web flows, and expensive to extend (e.g., dry-run, async execution).
- **Recommendation:** Extract dedicated services (e.g., `AnalysisService.validate_range`, `AnalysisService.run_pipeline`) and wire Typer to thin orchestration functions. Add dependency-injection friendly helpers so web/TUI endpoints can call the same services without shelling out.
- **Impact:** Improves maintainability and testability; unlocks reuse across CLI, TUI, and web; reduces branching complexity.

### 2. Consolidate Technical Fact Loading for Output Agents
- **Current state:** `DocxAgent.generate` and `PdfAgent.generate` re-hydrate `technical_facts/*.json` independently before diagram creation.
- **Issue:** Duplicated disk I/O and divergent filtering risk inconsistent diagrams across formats.
- **Recommendation:** Add `_load_facts()` and caching in `OutputAgent` so all subclasses share memoized `TechnicalFact` data. Allow dependency injection for testing.
- **Impact:** Faster runs, consistent diagram inputs, easier to maintain when fact schema evolves.

### 3. Reuse Playwright Browser Instances in PNG Rendering
- **Current state:** `MarkdownToPngRenderer.render` launches Chromium for every section via `asyncio.run`.
- **Issue:** Heavy process churn, problematic when invoked from async code, and potential `RuntimeError` nesting issues.
- **Recommendation:** Maintain a persistent async event loop and cached Playwright browser/context, or adopt the sync Playwright API with global browser reuse.
- **Impact:** Substantially lower rendering latency, fewer flaky runs, better resource usage during batch exports.

### 4. Generate Richer Class Diagrams from AST Metadata
- **Current state:** `_generate_class_diagram` infers class names by searching descriptions for the word "class" and emits empty attribute/method lists.
- **Issue:** Weak diagrams that miss real structure; duplicates when descriptions mention "class" casually.
- **Recommendation:** Pull method/attribute info from stored AST artifacts (`ast_head/*.json`), match against fact `source_elements`, and include inheritance/relationships.
- **Impact:** Produces diagrams that reflect actual code, increasing documentation quality and audit usefulness.

### 5. Strengthen Semantic Diff Classification
- **Current state:** `SemanticDiffAnalyzer` computes `SemanticDiffResult` buckets heuristically from AST comparisons.
- **Issue:** Lacks weighting per change type, limited confidence signals, and minimal linkage to downstream fact synthesis.
- **Recommendation:** Incorporate commit metadata (author, tags) and change heuristics (e.g., parameter rename vs. type change) when scoring. Persist reasons alongside `confidence` to help TechnicalAuthor triage facts.
- **Impact:** More reliable change categorization, better signals for breaking-change detection, and richer context for document plans.
