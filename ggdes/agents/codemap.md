# Agents Pipeline — Codemap

## Responsibility

Defines the four-agent analysis pipeline that transforms raw git history into structured
documentation plans. Each agent is an LLM-powered stage that consumes the output of the
previous stage and persists its results to the knowledge base (KB). The pipeline is
coordinated by the orchestrator (`main.py` / pipeline runner), not by the agents themselves.

```
Git History
    │
    ▼
┌─────────────────────┐
│   GitAnalyzer       │  ← analyzes git diff, produces ChangeSummary
│   (ggdes/agents/    │
│    git_analyzer.py) │
└─────────┬───────────┘
          │ ChangeSummary (JSON)
          ▼
┌─────────────────────┐
│   TechnicalAuthor   │  ← synthesizes technical facts from ChangeSummary + AST
│   (ggdes/agents/    │
│    technical_author │
│    .py)             │
└─────────┬───────────┘
          │ list[TechnicalFact] (JSON)
          ▼
┌─────────────────────┐
│   Coordinator       │  ← creates per-format DocumentPlan
│   (ggdes/agents/    │
│    coordinator.py)  │
└─────────┬───────────┘
          │ list[DocumentPlan] (JSON)
          ▼
   Output Agents*
   (ggdes/agents/output_agents/)

* Optional: ChangeFilter may run between GitAnalyzer and TechnicalAuthor
* Output agents that invoke Node.js (DocxAgent, PptxAgent) set `NODE_PATH` in the subprocess
  environment so that npm modules (`docx`, `pptxgenjs`) resolve correctly regardless of
  working directory.
```

---

## Agent Definitions

### 1. GitAnalyzer — `git_analyzer.py` (1099 lines)

**Role:** First pipeline stage. Reads raw git data and produces a structured
`ChangeSummary` via LLM analysis.

**Produces:** `ChangeSummary` (Pydantic model with `change_type`, `description`,
`intent`, `impact`, `impact_level`, `breaking_changes[]`, `dependencies_changed[]`,
`files_changed[]`)

**Key features:**
- **Multi-turn conversation:** Maintains a `ConversationContext` that can be persisted
  to KB for resume support.
- **Chunked analysis:** Large diffs are split into chunks (`_chunk_diff()`), each
  analyzed independently or accumulated. Supports two modes:
  - `independent` — each chunk processed in parallel (fast).
  - `accumulated` — each chunk sees all previous context (coherent).
- **Focus commits:** Analyzes only a subset of commits when `focus_commits` is provided.
  Gets diff from parent of first focus commit to last focus commit.
- **Resume support:** Chunk summaries saved to KB (`chunk_summaries.json`), reloaded
  on resume to skip re-analysis.
- **Language expert skill loading:** Detects primary language via file extension counting
  (`skill_utils.detect_primary_language`), loads `python-expert` or `cpp-expert` skills.
- **Code reference validation:** After generation, `_validate_code_references()` uses
  `CodeReferenceValidator` to check file paths and function names in the output against
  the actual git diff and AST, requesting LLM corrections when hallucinations are detected.
- **Fallback with thinking mode:** On `generate_structured` failure, retries with
  `enable_thinking=True` (useful for reasoning models).

**Invocation:**
```python
analyzer = GitAnalyzer(repo_path, config, analysis_id, user_context)
summary = await analyzer.analyze(commit_range, focus_commits, storage_policy)
```

**Integration points:**
- Input: git commands (`diff`, `log`, `diff-tree --numstat`)
- Output: saved to `kb/git_analysis/summary.json` and `kb/conversations/git_analyzer/`
- Uses: `skill_utils` (language detection, system prompt building), `prompts.get_prompt("git_analyzer", "system")`

---

### 2. TechnicalAuthor — `technical_author.py` (1527 lines)

**Role:** Second pipeline stage. Combines the `ChangeSummary` with AST parse data
(base and head commits) to produce structured `TechnicalFact` objects. This is the
most complex agent with the most robust anti-hallucination machinery.

**Produces:** `list[TechnicalFact]` — each fact has `fact_id`, `category` (api/behavior/architecture),
`description`, `source_elements[]`, `source_file`, `confidence`, `code_snippets{}`,
`before_after_code{}`, `usages{}`.

**Three analysis dimensions (parallel by default):**

| Dimension | Method | What it produces |
|-----------|--------|-----------------|
| API Changes | `_analyze_api_changes()` | New/deleted/modified functions, signature changes |
| Behavioral Changes | `_analyze_behavioral_changes()` | Logic changes, algorithm modifications, error handling |
| Architecture | `_analyze_architecture_changes()` | Class hierarchy changes, dependency changes |

**Anti-hallucination architecture (4 layers):**

1. **`ANTI_HALLUCINATION_INSTRUCTION`** — A constant injected into every LLM prompt
   that forces the model to use the `get_element_source` tool and not fabricate code.

2. **Source code injection** — `_build_source_code_context()` provides actual source
   code for changed elements directly in the prompt. `_compute_source_diffs()` generates
   before/after unified diffs that show exactly what changed.

3. **Tool-augmented LLM** — When a `ToolExecutor` is available:
   - `_generate_facts_response()` uses `chat_with_tools()` instead of plain chat.
   - Tools defined in `ggdes.tools.TOOL_DEFINITIONS` (e.g. `get_element_source`,
     `validate_reference`) let the LLM query actual source code during generation.
   - `_validate_facts_with_tools()` post-processes all facts, checking `source_file`
     and `source_elements` against the codebase via tool calls, removing or correcting
     invalid references.

4. **Usage search** — `_find_usages_in_worktree()` finds real call sites in the
   repository for API-change facts, providing context for how changed functions
   are actually used.

**Source diff pipeline:**
```
_base_elements + head_elements_
        │
        ▼
  _compute_source_diffs()   ← compares source by (file_path::name) key
        │                      produces {before, after, diff} dict
        ▼
  _build_diff_context()      ← formats diffs for LLM consumption
        │
        ▼
  injected into LLM prompts →
        │                      LLM writes descriptions grounded in real before/after
        ▼
  _enrich_facts_with_source_code()   ← attaches snippets + before_after + usages to facts
```

**Skill loading:**
- `doc-coauthoring` — writing/documentation expertise
- Language expert (e.g. `python-expert`, `cpp-expert`) — passed from GitAnalyzer

**Parallel execution:**
- Default: runs all three analysis dimensions concurrently via `asyncio.gather()`.
- Each dimension gets its own `ConversationContext` (cloned from the main one).
- Architecture analysis (`_analyze_architecture_changes`) is purely code-driven
  (no LLM call), so it runs alongside the two LLM-based analyses.

**Invocation:**
```python
author = TechnicalAuthor(repo_path, config, analysis_id, user_context,
                         language_expert_skill, tool_executor, review_feedback)
facts = await author.synthesize(storage_policy, parallel=True)
```

**Integration points:**
- Input: `kb/git_analysis/summary.json`, `kb/ast_base/*.json`, `kb/ast_head/*.json`,
  `kb/semantic_diff/result.json`
- Output: `kb/technical_facts/facts.json` (+ individual `kb/technical_facts/{fact_id}.json`)
- Uses: `prompts.get_prompt("technical_author", "system")`

---

### 3. Coordinator — `coordinator.py` (894 lines)

**Role:** Third pipeline stage. Creates `DocumentPlan` objects from technical facts,
tailored to each requested output format. Handles interactive user input gathering
and LLM self-review.

**Produces:** `list[DocumentPlan]` — one per format, each with `title`, `audience`,
`sections[]` (with `title`, `description`, `technical_facts[]`, `code_references[]`,
`diagrams[]`), `diagrams[]` (with `type`, `title`, `description`, `elements[]`).

**Key responsibilities:**
- **Fact categorization:** Groups facts by category (api, behavior, architecture, etc.)
  for structured planning.
- **Per-format planning:** Creates one `DocumentPlan` per target format, each with its
  own LLM conversation context. Formats run in parallel when there are multiple targets.
- **Semantic diff integration:** Loads semantic diff results and injects them into the
  planning prompt, highlighting breaking changes and high-impact items.
- **Interactive input:** `_gather_user_input()` asks the user about audience, focus areas,
  detail level, diagram preferences, and special sections (API reference, migration guide).
- **JSON extraction with fallback:** `_extract_json_from_response()` tries 4 strategies
  (raw, ```json fence, ``` fence, outermost braces). If all fail, uses correction prompt
  retry. If that also fails, `_build_fallback_plan()` creates one section per fact category.
- **LLM self-review:** When `review_feedback` is provided, `_interactive_review()` runs
  an LLM check on the generated plans to verify feedback was incorporated.

**Invocation:**
```python
coord = Coordinator(repo_path, config, analysis_id, user_context, review_feedback)
plans = await coord.create_plan(target_formats, interactive=True, storage_policy, parallel=True)
```

**Integration points:**
- Input: `kb/technical_facts/facts.json`, `kb/semantic_diff/result.json`
- Output: `kb/plans/plan_{format}.json` + `kb/plans/index.json`
- Uses: `prompts.get_prompt("coordinator", "system")`, `prompts.get_prompt("coordinator", "interactive_review")`

---

### 4. ChangeFilter (Semantic) — `change_filter.py` (387 lines)

**Role:** Optional pre-filtering stage. Classifies diff hunks by semantic relevance
to a user-specified feature description, reducing noise for feature-focused analyses.

**Produces:** A filtered `ChangeSummary` with only files relevant to the feature,
annotated with specific line ranges of interest.

**Key components:**
- `DiffHunk` — dataclass representing a single hunk with file path, line range, content.
- `FileClassification` — Pydantic model: `file_path`, `is_relevant`, `relevant_line_ranges[]`,
  `reason`.
- `ChangeFilterResult` — Pydantic wrapper for the above.
- `ChangeFilter.filter_changes()` — main entry point.

**Algorithm:**
1. `parse_diff_into_hunks()` — Parses unified diff into structured hunks with line numbers
   using regex patterns for `diff --git` and `@@ ... @@` headers.
2. `group_hunks_by_file()` — Groups hunks by file path.
3. `_classify_files()` — Sends each file's hunks to the LLM with the feature description,
   asking it to classify relevance. Uses `generate_structured` with `ChangeFilterResult`.
4. Applies classification: keeps relevant files, discards irrelevant ones.
5. **Safety valve:** If LLM marks ALL files irrelevant, keeps all changes (the feature
   description was likely too vague).

**Invocation:**
```python
filter = ChangeFilter(config, feature_description)
filtered_summary = filter.filter_changes(original_summary, raw_diff)
```

**Difference from `semantic_diff` module:** The `semantic_diff` module (in `ggdes/`)
uses AST-based automated detection (not LLM) to classify change types. `ChangeFilter`
uses an LLM to filter by _feature relevance_, which is a different concern. Both can
run in the same pipeline.

**Integration points:**
- Input: `ChangeSummary`, raw git diff string
- Output: Filtered `ChangeSummary` with `is_filtered=True` and `feature_description` set
- Uses: `prompts.get_prompt("change_filter", "classify_changes")`, `prompts.get_prompt("change_filter", "system")`

---

## Shared Utilities — `skill_utils.py` (265 lines)

**Responsibility:** Skill loading, language detection, system prompt building.

| Function | Purpose |
|----------|---------|
| `load_skill(name, repo_path)` | Loads `SKILL.md` from skills directory (4 search paths) |
| `detect_primary_language(repo_path)` | Counts file extensions to determine dominant language |
| `get_expert_skill_for_language(lang)` | Maps 'python'→'python-expert', 'cpp'→'cpp-expert' |
| `build_user_context_guidance(user_context)` | Formats user context dict into consistent guidance string |
| `SystemPromptBuilder` | Builds structured system prompts (skills → base → user guidance) |

**SystemPromptBuilder priority order:**
1. Skills (highest) — language expertise, domain expertise
2. Base system prompt — core agent instructions
3. User guidance — wrapped in a prominent "VERY IMPORTANT" box

Used by: GitAnalyzer, TechnicalAuthor, Coordinator, MarkdownAgent.

---

## Anti-Hallucination Architecture — Summary

| Layer | Where | Mechanism |
|-------|-------|-----------|
| Injection | TechnicalAuthor | `ANTI_HALLUCINATION_INSTRUCTION` forces tool usage |
| Source grounding | TechnicalAuthor | Real source code + before/after diffs in prompts |
| Tool-augmented LLM | TechnicalAuthor | `chat_with_tools()` during fact generation |
| Post-hoc validation | TechnicalAuthor | `_validate_facts_with_tools()` checks each fact |
| Code reference check | GitAnalyzer | `CodeReferenceValidator` + LLM correction |
| Safety valve | ChangeFilter | Keeps all changes when LLM is over-aggressive |

---

## Package Init — `__init__.py`

Exports the four agents:
```python
__all__ = ["ChangeFilter", "Coordinator", "GitAnalyzer", "TechnicalAuthor"]
```

---

## Data Flow Summary

```
User Input (commit range, focus commits, feature description)
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ GitAnalyzer.analyze()                                               │
│   ├─ get_diff()         ← git diff                                  │
│   ├─ get_commit_log()   ← git log                                  │
│   ├─ get_changed_files() ← git diff --numstat / git diff-tree     │
│   ├─ (optional) _analyze_chunked()  ← diff > max_diff_tokens      │
│   │                                + chunk summaries persist       │
│   │   ├─ independent mode: parallel per-chunk LLM calls            │
│   │   └─ accumulated mode: sequential growing context              │
│   ├─ (fast path) _analyze_single() ← diff fits in context          │
│   └─ _validate_code_references()   ← correction loop               │
│                                                                     │
│   Output: ChangeSummary → kb/git_analysis/summary.json              │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ (Optional) ChangeFilter.filter_changes()                            │
│   ├─ parse_diff_into_hunks()  ← regex-based                        │
│   ├─ _classify_files()        ← LLM per-file classification        │
│   └─ Safety valve on all-filtered-out                              │
│                                                                     │
│   Output: Filtered ChangeSummary                                    │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TechnicalAuthor.synthesize()                                        │
│   ├─ Load git analysis + AST data (base + head)                   │
│   ├─ _compute_source_diffs()    ← unified diff per element         │
│   ├─ _analyze_api_changes()     ← LLM + tools                     │
│   ├─ _analyze_behavioral_changes() ← LLM + tools                  │
│   ├─ _analyze_architecture_changes() ← code-only                  │
│   ├─ _validate_facts_with_tools()  ← tool post-check              │
│   └─ _enrich_facts_with_source_code() ← attach snippets + usages  │
│                                                                     │
│   Output: list[TechnicalFact] → kb/technical_facts/                 │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Coordinator.create_plan()                                           │
│   ├─ _categorize_facts()                                           │
│   ├─ (optional) _gather_user_input() ← interactive CLI             │
│   ├─ _create_format_plan()    ← per-format LLM (parallel)         │
│   │   └─ _extract_json_from_response() + fallback chain            │
│   └─ _interactive_review()     ← LLM self-check when feedback     │
│                                                                     │
│   Output: list[DocumentPlan] → kb/plans/plan_{format}.json          │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
                        Output Agents (separate codemap)
                         ggdes/agents/output_agents/
```
