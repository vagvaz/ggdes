# GGDes Architecture and Semantic Diff Analysis

## Key Problems — Verified Assessment

### ✅ CONFIRMED: Contract mismatch between semantic_diff producer and output_agents consumer

**Severity: HIGH — functional bug, silently degrades output**

`semantic_diff.py:save_semantic_diff` writes JSON with top-level key `semantic_changes` containing flat objects (`change_type`, `file_path`, `related_symbols`, etc.). `output_agents/base.py:_load_changed_classes` reads expecting top-level key `changes` with nested `element` objects (`element_type`, `name`, `parent`, `change_category`). The consumer will **always return an empty set** because:
1. `data.get("changes", [])` → `[]` (key doesn't exist)
2. Even if the key matched, `change.get("element", {})` → `{}` (no nested structure)
3. Field names don't align (`change_type` vs `change_category`, no `element_type`)

This is a complete schema mismatch — the output agent enrichment path for changed classes is dead code.

### ✅ CONFIRMED: Sequential technical-author path omits semantic_diff for behavioral analysis

**Severity: MEDIUM — inconsistent output quality between modes**

In `technical_author.py`:
- **Sequential path** (line ~758): `_analyze_behavioral_changes` is called **without** `semantic_diff` parameter
- **Parallel path** (line ~1257): `_analyze_behavioral_changes` is called **with** `semantic_diff=semantic_diff`

This is a bug, not a design choice. Behavioral analysis in sequential mode lacks semantic diff context that parallel mode has, producing less accurate results.

### ⚠️ PARTIALLY CONFIRMED: Pipeline dispatcher is "large" with "implicit and brittle" contracts

**Severity: LOW-MEDIUM — overstated but real gaps exist**

- `run_stage` is 97 lines with 9 elif branches — moderate, not exceptional
- Pydantic models (`ChangeSummary`, `CodeElement`, `TechnicalFact`, etc.) **already exist** and validate on read
- Real gaps: no write-time validation, no formal stage I/O interface, hardcoded artifact paths as strings, `getattr` fallbacks on `self.metadata`
- The "implicit and brittle" characterization overstates the problem — contracts are partially explicit via Pydantic

### ⚠️ PARTIALLY CONFIRMED: Change filter mutates git_analysis/summary.json in place

**Severity: LOW — nuance matters**

- Change filter **does** overwrite `git_analysis/summary.json` with filtered data
- It **does** save the original as `summary_unfiltered.json` backup
- The `ChangeSummary.is_filtered=True` flag is set on the filtered version
- Downstream stages read filtered data from `summary.json` and cannot easily access raw data
- Provenance is partially preserved but not convenient — no downstream stage reads `summary_unfiltered.json`

### ✅ CONFIRMED: Semantic diff is Python-ast only; non-Python files get zero semantics

**Severity: MEDIUM — significant coverage gap**

All detection methods (`_detect_signature_changes`, `_detect_control_flow_changes`, `_detect_error_handling_changes`, `_detect_documentation_changes`) use Python stdlib `ast.parse()`. Non-Python files trigger `SyntaxError` → caught → returns empty/zero. The project has tree-sitter support in `ggdes/parsing/ast_parser.py` (Python + C++), but `semantic_diff.py` does **not** import or use it.

### ⚠️ PARTIALLY CONFIRMED: Cross-stage handoff is file-path/JSON without typed boundary

**Severity: LOW-MEDIUM — Pydantic models exist but aren't enforced at boundaries**

Stages load data via `json.loads(path.read_text())` then validate through Pydantic (`ChangeSummary(**data)`, `CodeElement(**elem_data)`). This provides read-time validation. The gap is:
- No write-time validation (raw `model_dump()` → `write_text()`)
- No formal interface declaring what each stage must produce/consume
- Hardcoded path strings scattered across pipeline methods

---

## Problems the Analysis Missed

### 1. Parallel group dependency issue

`run_all_pending` groups `ast_parsing_base`, `ast_parsing_head`, and `semantic_diff` as a parallel group. But `semantic_diff` depends on `changed_files` from git analysis (not on AST parsing). The parallel group logic only runs in parallel when **all three** are pending — if any one is already complete, they all run sequentially. This limits parallelization benefit and doesn't express the actual dependency graph.

### 2. Redundant diff computation in change_filter

`change_filter` calls `GitAnalyzer.get_diff(...)` to recompute the unified diff, even though `git_analysis` already computed it. The diff content could be passed from the git analysis stage instead of recomputed.

### 3. No per-file AST loading optimization

`technical_author` loads AST data by reading individual JSON files from `ast_head/` and `ast_base/` directories. For large codebases with many changed files, this creates many small file I/O operations without batching or lazy loading.

---

## Evaluation of Suggested Solutions

### ✅ Good: Fix semantic diff schema mismatch (Phase 1)

**Efficient? Yes — this is a bug fix, not an architectural change.** The consumer (`_load_changed_classes`) should be updated to read the actual `semantic_changes` format, or the producer should be adjusted. Either way, this is a small, targeted fix with high impact.

**Question:** Should we update the consumer to match the producer's schema, or redesign the schema to serve both consumers (output_agents and comparison)? The current `SemanticChange` flat structure may not carry enough information for class-level extraction — `related_symbols` is a string list, not a structured element reference.

### ✅ Good: Fix sequential technical-author semantic_diff omission (Phase 1)

**Efficient? Yes — one-line fix.** Add `semantic_diff=semantic_diff_data` to the `_analyze_behavioral_changes` call in the sequential path.

### ⚠️ Over-engineered: "Typed stage artifact contract" with Pydantic validation on write/read

**Efficient? Partially.** Pydantic models already exist and validate on read. Adding write validation is trivial (`model.model_dump()` → validate round-trip). But creating a full "stage I/O registry" with formal interfaces per stage is significant infrastructure for a pipeline with 9 stages. The current hardcoded paths are discoverable via grep and the KB manager.

**Question:** What specific failure mode are we preventing? If it's "stage writes corrupt JSON," read-time Pydantic validation already catches this. If it's "stage writes schema-incompatible data," write validation adds marginal safety. Is the complexity of a registry worth it for 9 stages?

### ⚠️ Over-engineered: `StageContext` object with typed inputs/outputs and deterministic paths

**Efficient? Not at current scale.** This is essentially a dependency injection framework for 9 stages. The current `self.metadata` + KB path pattern works, and stages already know their inputs. A `StageContext` would add abstraction without reducing complexity — you'd still need to define the contract per stage, just in a different place.

**Question:** Would this pay off if the pipeline grows to 15+ stages or supports plugin stages? If so, when is the right time to invest?

### ⚠️ Mixed: Split raw and derived artifacts

**Efficient? The problem is real but the solution may be simpler.** Rather than creating `change_filter/summary.json` as a new path (which requires updating all downstream readers), we could:
- Keep `git_analysis/summary.json` as the **filtered** version (current behavior, since downstream stages expect filtered data)
- Keep `git_analysis/summary_unfiltered.json` as the raw version (already exists)
- Add a `git_analysis/metadata.json` or flag in `metadata.yaml` recording which version is active

This avoids path migration while preserving provenance.

### ✅ Good: Semantic diff schema versioning

**Efficient? Yes — low cost, high value.** Adding `schema_version: "1.0"` to `semantic_diff/result.json` enables future evolution without breaking consumers. Should be combined with the schema mismatch fix.

### ✅ Good: Multi-language semantic diff via tree-sitter reuse

**Efficient? Yes — leverages existing infrastructure.** `ggdes/parsing/ast_parser.py` already has tree-sitter support for Python and C++. The semantic diff should import and use `ASTParser` instead of Python `ast` directly. This is the highest-value algorithmic improvement.

**Question:** Should we start with C++ (tree-sitter already supported) or add JavaScript/TypeScript support first (likely higher impact for web projects)?

### ⚠️ Premature: Incremental invalidation via hashing

**Efficient? Not yet.** The pipeline already has stage state tracking in `metadata.yaml` with `start_stage`/`complete_stage`/`fail_stage`/`skip_stage`. Adding content hashing for incremental invalidation adds complexity (hash computation, cache management, partial invalidation) for marginal speed gains. This would only pay off for repeated analyses of the same commit range — an uncommon workflow.

**Question:** Is there evidence that users frequently re-run analyses on unchanged commits? If not, this is YAGNI.

### ⚠️ Over-scoped: Change-filter granularity improvements (hunk complexity weighting, confidence scores)

**Efficient? The LLM already makes relevance decisions.** Adding hunk complexity weighting and confidence scores means either:
1. More LLM calls (expensive, slow), or
2. Heuristic scoring (which the LLM could override anyway)

The current approach of file-level classification with optional line ranges is simple and the fallback guard keeps all files if the LLM filters everything. Adding complexity here has diminishing returns.

### ⚠️ Ambitious: Semantic diff scoring (API surface + call-site reach + file criticality)

**Efficient? High value but high effort.** Computing call-site reach requires cross-file call graph analysis, which is a significant new capability. File criticality requires heuristics or configuration. This is Phase 3+ material and should be scoped carefully.

**Question:** How would call-site reach be computed? Static analysis (tree-sitter call graph)? LLM-based? What about dynamic dispatch in Python?

### ✅ Good: Per-change stable IDs for comparison

**Efficient? Yes — enables meaningful diff-of-diffs.** Currently `comparison.py` compares aggregate metrics only. Stable IDs (`file:symbol:type:hash`) would enable tracking individual changes across analyses. Low implementation cost, high value for the comparison feature.

### ✅ Good: Precision guards (suppress low-confidence, distinguish doc-only changes)

**Efficient? Yes — reduces noise.** Currently, whitespace-only or comment-only changes can generate semantic change entries with low confidence. Suppressing these or tagging them as `documentation_only` would improve signal-to-noise ratio. Simple heuristic: if diff is only whitespace/comments, skip or downgrade.

**Question:** What confidence threshold? Too aggressive suppression loses real changes; too lenient keeps noise. Should this be configurable?

---

## Revised Execution Roadmap

### Phase 1 — Bug Fixes (immediate, low risk)

| Item | Effort | Impact |
|------|--------|--------|
| Fix semantic diff schema mismatch (`semantic_changes` vs `changes`) | Small | High — unblocks output agent enrichment |
| Add `semantic_diff` to sequential `_analyze_behavioral_changes` call | Trivial | Medium — consistent output quality |
| Add `schema_version` to semantic diff output | Small | Medium — future-proofs schema evolution |

### Phase 2 — Targeted Improvements (short-term, moderate risk)

| Item | Effort | Impact |
|------|--------|--------|
| Integrate tree-sitter into semantic diff for C++ support | Medium | High — covers second language |
| Add per-change stable IDs to `SemanticChange` | Small | Medium — enables meaningful comparison |
| Add precision guards (whitespace/comment suppression, doc-only tagging) | Small | Medium — reduces noise |
| Add write-time Pydantic validation to stage outputs | Small | Medium — catches corruption early |

### Phase 3 — Architecture Improvements (medium-term)

| Item | Effort | Impact |
|------|--------|--------|
| Formalize stage I/O contracts (interface per stage declaring inputs/outputs) | Medium | Medium — improves maintainability |
| Fix parallel group to express actual dependencies | Small | Medium — enables better parallelization |
| Eliminate redundant diff computation in change_filter | Small | Low — minor performance gain |
| Add generic language adapter framework for semantic diff | Medium | High — extensibility |

### Phase 4 — Advanced Features (long-term)

| Item | Effort | Impact |
|------|--------|--------|
| Call-site reach analysis for impact scoring | High | High — but requires call graph infrastructure |
| Stage content hashing for incremental invalidation | Medium | Low — unless re-run workflow is common |
| Pipeline contract tests with schema drift detection | Medium | Medium — prevents future mismatches |
| Regression fixtures for semantic diff | Medium | High — prevents regressions |

---

## Open Questions

1. **Schema mismatch fix direction:** Should `_load_changed_classes` be updated to read the `semantic_changes` format, or should `SemanticChange` be restructured to include an `element` sub-object? The latter serves both output agents and comparison but is a bigger change.

2. **Multi-language priority:** C++ (tree-sitter already supported) or JavaScript/TypeScript (likely higher impact for web projects)? This affects Phase 2 scope.

3. **Confidence threshold for precision guards:** What's the acceptable precision/recall tradeoff? Should low-confidence suppression be configurable per analysis?

4. **Stage I/O registry ROI:** Is a formal registry worth the complexity for 9 stages, or should we just add write validation + path constants and revisit if the pipeline grows?

5. **Incremental invalidation demand:** Is there evidence that users frequently re-run analyses on unchanged commits? If not, content hashing is YAGNI.

6. **Change filter redundancy:** Should change_filter receive the diff from git_analysis instead of recomputing it? This requires passing data between stages rather than re-fetching.

7. **Parallel group semantics:** Should `semantic_diff` be in the parallel group at all? It depends on git_analysis output but not on AST parsing. The current grouping forces sequential fallback when any one stage is already complete.