# GGDes — Domain Glossary

## Domain

GGDes (Get from Git Design Documentation) is a multi-stage pipeline that analyzes git commits and generates design documentation in multiple formats (Markdown, DOCX, PDF, PPTX).

## Core Concepts

### Pipeline
The top-level orchestrator that sequences stages and manages shared state (metadata, KB, worktrees).

### Stage
A unit of pipeline work with a common async interface:

```
Stage.run(metadata, config, kb, console, feedback?) -> StageResult
```

Each stage is responsible for:
- Reading its inputs from the knowledge base (KB)
- Executing its analysis (possibly via LLM agents)
- Writing its outputs to the KB
- Returning success/failure/skip

Stages live in `ggdes/stages/` and are registered by name in the `STAGE_REGISTRY`.

### StageResult
Dataclass returned by every stage:
- `success: bool` — did the stage complete its work?
- `error: str | None` — why it failed (if it did)
- `skipped: bool` — nothing to do (not a failure)

### Stage Registry
A dict `{stage_name: StageClass}` in `ggdes/stages/__init__.py`. The pipeline dispatches stage execution by looking up the name in this registry. Non-extracted stages fall through to the legacy if/elif chain.

### Stage I/O Contract
The implicit contract of what artifacts a stage reads from and writes to the KB. Currently enforced at read-time via Pydantic models. Target: write-time validation + contract tests per stage.

### Orchestration
The pipeline's role: sequencing stages, managing parallel groups, updating metadata state, and handling review feedback. Distinct from stage implementation (the actual work).

### Knowledge Base (KB)
File-system backed persistence for analysis artifacts. Organized as `{kb_base}/analyses/{analysis_id}/{stage_name}/`. Currently tightly coupled to stage names.

### Worktree
Isolated git checkout at a specific commit, created via `git worktree add`. Used to give analysis tools access to the actual file system state of base and head commits.

## Architecture Vocabulary

Use these terms (from LANGUAGE.md conventions):

| Term | Definition |
|------|------------|
| Module | Anything with an interface and an implementation |
| Interface | Everything a caller must know to use the module |
| Depth | Behaviour / interface-size ratio |
| Seam | Where an interface lives; a place behaviour can be altered |
| Adapter | A concrete thing satisfying an interface at a seam |
| Leverage | What callers get from depth |
| Locality | What maintainers get from depth |

## Pipeline Stages (in order)

1. **worktree_setup** — Create base/head git worktrees
2. **git_analysis** — Analyze commits, produce `ChangeSummary`
3. **change_filter** — (Optional) Filter changes by feature relevance
4. **ast_parsing_base** — Parse base commit AST
5. **ast_parsing_head** — Parse head commit AST
6. **semantic_diff** — Detect semantic changes beyond text diffs
7. **technical_author** — Synthesize technical facts
8. **coordinator_plan** — Create document generation plans
9. **output_generation** — Generate documents in target formats
