# ggdes/schemas/

## Responsibility

Defines the canonical data types that flow through the entire GGDes analysis pipeline. Every pipeline stage produces or consumes these Pydantic models and enums. The schemas serve as the contract between stages — they are imported by the AST parser, git analyzer, semantic diff engine, technical author, coordinator, output agents, validators, and comparison tool.

This module has zero business logic: it is a pure schema definition layer.

## Design

### Two files, one public API

| File | Contents |
|---|---|
| `enums.py` | Simple `str` `Enum` definitions (`StoragePolicy`). |
| `models.py` | All Pydantic `BaseModel` classes plus two enums (`ChangeType`, `ImpactLevel`, `CodeElementType`) that are co-located with their primary model. |

The `__init__.py` re-exports every public symbol, so consumers write `from ggdes.schemas import ChangeSummary, TechnicalFact, ...` and never need to know which file a symbol lives in.

---

### Enumerations

| Enum | Values | Where used |
|---|---|---|
| `ChangeType` | `feature`, `bugfix`, `refactor`, `docs`, `test`, `chore`, `performance`, `security` | `ChangeSummary.change_type` — categorises the overall git change. |
| `ImpactLevel` | `none`, `low`, `medium`, `high`, `critical` | `ChangeSummary.impact_level` — severity rating. Ordinal semantics: `critical > high > medium > low > none`. |
| `CodeElementType` | `function`, `method`, `class`, `variable`, `constant`, `import`, `decorator` | `CodeElement.element_type` — classifies AST-extracted code symbols. Only `function`, `method`, and `class` are currently emitted by the AST parser. |
| `StoragePolicy` | `raw`, `summary`, `none` | `KnowledgeBaseManager` and conversation persistence. Controls how agent<->LLM conversations are saved. Lives in its own file because it is used by the KB module and CLI, not by pipeline models. |

---

### Core data models (in pipeline order)

#### 1. `FileChange` — single-file diff metadata

```
FileChange
├── path: str                        # relative to repo root
├── change_type: str                 # "added" | "modified" | "deleted" | "renamed"
├── lines_added: int
├── lines_deleted: int
├── summary: str                     # what changed in this file
└── relevant_line_ranges: list[tuple[int,int]] | None  # semantic-filtered; None = all lines
```

**Produced by**: `GitAnalyzer` (git_analysis stage).
**Consumed by**: `ChangeSummary.files_changed`, semantic filter (`ChangeFilterAgent`).

#### 2. `ChangeSummary` — top-level git change description

```
ChangeSummary
├── commit_hash / commit_range       # identifier
├── change_type: ChangeType          # feature/bugfix/refactor/...
├── description: str                 # what changed
├── intent: str                      # why (developer intent)
├── impact: str                      # what systems/behaviors affected
├── impact_level: ImpactLevel
├── files_changed: list[FileChange]
├── breaking_changes: list[str]
├── dependencies_changed: list[str]
├── feature_description: str | None  # semantic filtering context
└── is_filtered: bool                # was semantic filtering applied?
```

**Produced by**: `GitAnalyzer` (git_analysis stage), optionally filtered by `ChangeFilterAgent`.
**Consumed by**: `AnalysisResult.change_summaries`, `AnalysisComparator`, output agents.

#### 3. `CodeElement` — AST-extracted symbol

```
CodeElement
├── name: str                        # symbol name
├── element_type: CodeElementType    # function/method/class/...
├── signature: str | None            # parameter list for callables
├── docstring: str | None
├── start_line / end_line: int       # 1-based line range
├── file_path: str
├── parent: str | None               # enclosing class/module
├── children: list[str]              # method names (for classes)
├── decorators: list[str]            # @decorator texts
├── dependencies: list[str]          # (unused in current code)
└── source_code: str | None          # literal source for grounding
```

**Produced by**: `ASTParser` (ast_parsing stages).
**Consumed by**: `AnalysisResult.code_elements`, `CodeChangeDetail.element`, technical facts, validators.

#### 4. `CodeChangeDetail` — element-level diff with AST context

```
CodeChangeDetail
├── element: CodeElement             # the element after change
├── change_category: str             # "added" | "modified" | "deleted" | "unchanged"
├── before_state: CodeElement | None # element before change
├── behavioral_change: bool          # did behavior change (not just structure)?
└── description: str                 # what changed
```

**Produced by**: (Currently declared but not populated by any pipeline stage — reserved for future use by semantic diff.)
**Consumed by**: `AnalysisResult.change_details`.

#### 5. `TechnicalFact` — synthesised observation about the code

```
TechnicalFact
├── fact_id: str                     # "fact_{uuid8}"
├── category: str                    # api | behavior | architecture | data_flow | dependency
├── source_elements: list[str]       # related code element names
├── description: str                 # factual statement
├── source_file: str
├── confidence: float [0..1]
├── verified: bool                   # validated against AST?
├── code_snippets: dict[str, str]    # element_name → source code (grounding)
├── before_after_code: dict[str, dict]  # element → {before, after, diff}
├── usages: dict[str, dict]          # element → {before_usages, after_usages}
└── created_at: datetime
```

**Produced by**: `TechnicalAuthorAgent` (technical_author stage).
**Consumed by**: `CoordinatorAgent` (coordinator_plan stage), `AnalysisResult.technical_facts`, `AnalysisComparator`.

#### 6. `DiagramSpec` — blueprint for a diagram

```
DiagramSpec
├── diagram_type: str                # architecture | flow | sequence | class
├── title: str
├── description: str                 # what to show
├── elements_to_include: list[str]   # code element names
└── format: str                      # "plantuml" (only supported format)
```

**Produced by**: `CoordinatorAgent`.
**Consumed by**: `DocumentPlan.diagrams`, diagram generator modules.

#### 7. `SectionPlan` — outline for one document section

```
SectionPlan
├── title: str
├── description: str
├── technical_facts: list[str]       # fact IDs
├── code_references: list[str]       # element names
├── diagrams: list[str]              # diagram IDs
├── source_code: dict[str, str]      # element → source (grounding)
├── before_after_code: dict[str, dict]
└── usages: dict[str, dict]
```

**Produced by**: `CoordinatorAgent` (one per section).
**Consumed by**: `DocumentPlan.sections`, output agents.

#### 8. `DocumentPlan` — complete document generation plan

```
DocumentPlan
├── analysis_id: str
├── format: str                      # markdown | docx | pptx | pdf
├── title: str
├── audience: str
├── sections: list[SectionPlan]
├── diagrams: list[DiagramSpec]
├── template: str | None
├── created_at: datetime
└── user_context: dict | None        # user-provided guidance
```

**Produced by**: `CoordinatorAgent` (one per output format).
**Consumed by**: Output agents (`MarkdownAgent`, `DocxAgent`, `PptxAgent`, `PdfAgent`).

#### 9. `AnalysisResult` — pipeline output, the final artifact

```
AnalysisResult
├── analysis_id: str
├── name: str
├── change_summaries: list[ChangeSummary]
├── code_elements: list[CodeElement]
├── change_details: list[CodeChangeDetail]
├── technical_facts: list[TechnicalFact]
├── document_plans: list[DocumentPlan]
└── metadata: dict
```

**Produced by**: The pipeline's `run()` method (populated incrementally across stages).
**Consumed by**: CLI commands (`ggdes analyze` output, `ggdes compare`), web UI, TUI, export/archive.

---

## Flow

```
Pipeline stage                          Schema produced              Schema consumed
─────────────────                      ──────────────              ────────────────
git_analysis ──────────────────────→   ChangeSummary (with FileChange)
                                            │
ast_parsing_base (opt) ─────────────→   CodeElement                  CodeElementType
ast_parsing_head ──────────────────→   CodeElement
                                            │
semantic_diff (opt) ───────────────→   (internal SemanticChange)     CodeElement, ParseResult
                                            │
technical_author ──────────────────→   TechnicalFact                 CodeElement, ChangeSummary
                                            │
coordinator_plan ──────────────────→   DocumentPlan                  TechnicalFact
                                       ├── SectionPlan
                                       └── DiagramSpec

comparison ─────────────────────────                              ChangeSummary, TechnicalFact
```

## Integration

### Import map (who imports what from schemas)

| Consumer | Imports |
|---|---|
| `ggdes.parsing.ast_parser` | `CodeElement`, `CodeElementType` |
| `ggdes.agents.git_analyzer` | `ChangeSummary`, `StoragePolicy`, `FileChange` |
| `ggdes.agents.change_filter` | `ChangeSummary`, `FileChange` |
| `ggdes.agents.technical_author` | `TechnicalFact`, `CodeElement`, `CodeChangeDetail`, `ChangeSummary`, `StoragePolicy` |
| `ggdes.agents.coordinator` | `DocumentPlan`, `SectionPlan`, `DiagramSpec`, `TechnicalFact`, `StoragePolicy` |
| `ggdes.agents.output_agents.*` | `TechnicalFact`, `SectionPlan`, `DocumentPlan`, `CodeElement`, `ChangeSummary` |
| `ggdes.comparison` | `ChangeSummary`, `TechnicalFact` |
| `ggdes.validation.validators` | `CodeElement`, `TechnicalFact` |
| `ggdes.kb.manager` | `StoragePolicy` |
| `ggdes.llm.conversation` | `StoragePolicy` |
| `ggdes.cli.utils` | `StoragePolicy` |
| `ggdes.diagrams.llm_generator` | `TechnicalFact` |
| `ggdes.diagrams.cache` | `TechnicalFact` |
| `ggdes.pipeline` | `ChangeSummary`, `CodeElement` |

### Schema design principles

1. **Pydantic v2 BaseModel** — All models get automatic validation, serialisation (`model_dump_json()`), and deserialisation (`model_validate`). This is critical because every stage persists its output as JSON via the KnowledgeBase, and downstream stages reload them.

2. **No business logic** — These are pure data containers. Methods are limited to field defaults. The only "logic" is the `model_config` (not shown) which will be added in the future for `json_schema_extra` examples.

3. **Grounding fields** — `TechnicalFact.code_snippets` and `SectionPlan.source_code` are explicitly designed to carry verbatim source code extracted by the AST parser. This is the mechanism that prevents LLM hallucination in output generation: every code reference in a generated document is backed by actual source text.

4. **Optional fields with meaning** — `None` is used deliberately:
   - `ChangeSummary.feature_description=None` means "no semantic filtering was applied."
   - `FileChange.relevant_line_ranges=None` means "all lines are relevant" (unfiltered).
   - `CodeElement.source_code=None` means "source was not captured" (e.g., during full-directory parse without verbose mode).
