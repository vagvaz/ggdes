# Future Work: Phase 3 & Phase 4

This document outlines planned improvements for GGDes that go beyond the Phase 1 (quick fixes) and Phase 2 (core architecture) work already completed.

## Phase 3: Algorithmic Depth

### 3.1 Multi-Language Semantic Diff Adapters

**Current state:** Semantic diff uses Python `ast` module for all detection methods. C++ files are now routed to tree-sitter via `_parse_cpp_elements()`, but detection methods (`_detect_control_flow_changes`, `_detect_error_handling_changes`, `_detect_documentation_changes`) still use Python `ast` and return empty/zero for non-Python files.

**Planned improvements:**

- **C++ adapter:** Implement `_detect_cpp_control_flow_changes()` using tree-sitter queries for `if_statement`, `for_statement`, `while_statement`, `switch_statement` nodes
- **C++ adapter:** Implement `_detect_cpp_error_handling_changes()` by counting `try_statement` / `catch_clause` nodes
- **C++ adapter:** Implement `_detect_cpp_documentation_changes()` by counting `//` and `/* */` comment nodes
- **Generic fallback adapter:** For languages without tree-sitter support, use diff-pattern heuristics:
  - Count `if`/`for`/`while` keywords in the diff for control flow estimation
  - Count `try`/`catch`/`throw` keywords for error handling estimation
  - Count comment-line patterns for documentation estimation
- **Language detection routing:** `_analyze_file_changes()` should route to the appropriate adapter based on file extension, with a clean strategy pattern

**Estimated effort:** 3-5 days

### 3.2 Per-Change Stable IDs for Comparison

**Current state:** `SemanticChange` now has `change_id` fields generated via `_generate_change_id()`, and `comparison.py` uses them for per-change identity comparison.

**Planned improvements:**

- **Deterministic ID generation:** Ensure `change_id` is fully deterministic across re-runs of the same commit range by incorporating content hashes of the changed elements
- **ID stability across commit ranges:** When comparing analyses of different commit ranges, changes that are semantically the same (same file, same symbol, same type) should produce matching `change_id` prefixes even if the hash suffix differs
- **Comparison enrichment:** Add `change_id`-based diffing to the export output (`export_comparison`) so external consumers can track changes across analyses

**Estimated effort:** 1-2 days

### 3.3 Richer Comparison Metrics

**Current state:** `comparison.py` compares summary-level counts and per-change identity. Similarity score is a simple ratio.

**Planned improvements:**

- **Weighted similarity:** Weight changes by `impact_score` and `confidence` rather than simple count
- **Category-level drift detection:** Detect when the distribution of change types shifts between analyses (e.g., more behavioral changes, fewer refactoring changes)
- **Impact score aggregation:** Compare total impact scores per category, not just counts
- **Semantic similarity:** For changes without matching `change_id`, compute text similarity on descriptions to detect near-matches

**Estimated effort:** 2-3 days

### 3.4 Semantic Diff Scoring

**Current state:** Impact scores are static per change type with minor adjustments for element type and parameter count. Confidence scores are heuristic-based.

**Planned improvements:**

- **API surface scoring:** Weight changes by the public API surface area affected (public methods > private methods > internal functions)
- **Call-site reach:** Use AST analysis to estimate how many callers a changed function has
- **File criticality:** Weight changes in core modules higher than changes in tests/utilities
- **Combined scoring formula:** `impact = base_score * api_surface_weight * call_reach_weight * file_criticality`
- **Configurable scoring weights:** Allow users to tune scoring via `ggdes.yaml` configuration

**Estimated effort:** 3-4 days

## Phase 4: Quality Gates

### 4.1 Regression Test Fixtures

**Current state:** No automated regression tests for semantic diff or pipeline stages.

**Planned improvements:**

- **Python commit range fixture:** A test repo with Python changes covering API additions/removals/modifications, doc-only changes, control flow changes, error handling changes
- **C++ commit range fixture:** A test repo with C++ changes covering class/function additions, header changes, template modifications
- **Docs-only fixture:** A commit range that only modifies documentation/comments, verifying `is_doc_only` flag and precision guards
- **Refactor-only fixture:** A commit range with pure refactoring (renames, extractions, inlines) to verify `SemanticChangeType.REFACTORING` detection
- **Mixed fixture:** A realistic commit range with multiple change types to test end-to-end pipeline

**Estimated effort:** 3-4 days

### 4.2 Pipeline Contract Tests

**Current state:** Stage contracts are implicit (file paths and JSON shapes). No automated verification that producers and consumers agree on schemas.

**Planned improvements:**

- **Schema version tests:** Verify that `save_semantic_diff` output matches what `_load_changed_classes` and `_compare_semantic_diff` expect
- **Artifact path tests:** Verify that each stage reads from and writes to the expected paths
- **Round-trip tests:** Write a `SemanticDiffResult`, save it, load it, verify all fields survive
- **Breaking change detection:** Add CI checks that fail when stage output schemas change without version bumps
- **Consumer contract tests:** Each consumer of a stage output should have a test that verifies it can parse the current schema version

**Estimated effort:** 2-3 days

### 4.3 Change Filter Granularity Improvements

**Current state:** Change filter classifies files as relevant/irrelevant at the file level with optional line ranges.

**Planned improvements:**

- **Hunk-level weighting:** Weight hunks by complexity (added control flow, signature edits, public API paths)
- **Confidence and rationale storage:** Store why each file was included (confidence score + LLM rationale) in the filtered output, not just inclusion decision
- **Symbol-level filtering:** Use AST data to filter at the symbol level rather than just file level
- **Configurable relevance threshold:** Allow users to set how aggressive the filter should be

**Estimated effort:** 2-3 days

### 4.4 Stage I/O Validation Framework

**Current state:** Write-time validation exists for `save_semantic_diff`. Other stages use Pydantic `model_dump()` which provides some validation.

**Planned improvements:**

- **Universal validation hook:** Add a `validate_and_write()` utility that all stage outputs use, which:
  1. Validates the data against its Pydantic model
  2. Writes to the expected path
  3. Reads back and verifies the write succeeded
  4. Logs the write with schema version
- **Schema migration support:** When reading stage outputs, check `schema_version` and apply migrations if needed
- **Corruption detection:** On read, verify file integrity (valid JSON, required fields present)

**Estimated effort:** 2-3 days

---

## Priority Order

1. **4.1 Regression fixtures** - Highest priority, enables all other testing
2. **4.2 Pipeline contract tests** - Prevents future contract mismatches
3. **3.1 Multi-language adapters** - Largest user-facing improvement
4. **3.2 Per-change IDs** - Already partially done, needs polish
5. **3.4 Semantic diff scoring** - High value for output quality
6. **3.3 Richer comparison** - Nice-to-have for power users
7. **4.3 Change filter granularity** - Incremental improvement
8. **4.4 Stage I/O validation** - Infrastructure improvement