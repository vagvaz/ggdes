# ggdes/diagrams/

## Responsibility

Generate diagrams from technical facts for embedding in output documentation. Supports both **LLM-driven generation** (primary) and **template-based formatting** (fallback) across four diagram types. Caches results to avoid regeneration when facts haven't changed.

## Files

| File | Role |
|------|------|
| `__init__.py` | `PlantUMLGenerator` class, private format functions (`_generate_*_plantuml`), `save_failed_plantuml()` helper |
| `cache.py` | `DiagramCache` — persisted hash-based cache keyed on `(analysis_id, diagram_type, facts_hash)` |
| `llm_generator.py` | `LLMDiagramGenerator` — orchestrates LLM calls with structured output, validation, self-repair, and template fallback |
| `plantuml.jar` | PlantUML Java binary (auto-downloaded, searched in default locations) |

## Design

### PlantUMLGenerator (`__init__.py`)

Java-based rendering pipeline that wraps the PlantUML CLI jar.

**Initialization:**
- Searches for `plantuml.jar` in: package directory → project `diagrams/` → CWD → CWD `ggdes/diagrams/`
- Raises `FileNotFoundError` if jar not found

**Rendering (`generate` method):**
1. Writes PlantUML DSL to a temp `*.puml` file
2. Runs `java -jar plantuml.jar -t{format} -o {outdir} {puml_file}`
3. Renames PlantUML output (matches temp filename) to desired output path
4. Cleans up temp files in `finally` block
5. Supports `png`, `svg`, and `pdf` formats

**Validation & Repair:**
- `validate()` runs PlantUML in `-checkonly` mode
- `validate_and_repair()` loops up to `max_attempts` times calling `_repair_plantuml()`
- `_repair_plantuml()` applies heuristics:
  1. Adds missing `@startuml`/`@enduml` delimiters
  2. Quotes identifiers with spaces in `as` declarations
  3. Normalizes arrow syntax spacing (`-->`, `->`)
  4. Strips empty parentheses from `class Foo()` definitions
  5. Wraps unquoted relationship labels in quotes
  6. Simplifies invalid color/style syntax

### Template-Based Formatters (private functions)

Each is a pure PlantUML DSL generator — no rendering, just string construction:

| Function | Diagram Type | PlantUML Syntax |
|----------|-------------|-----------------|
| `_generate_architecture_plantuml()` | Architecture | C4-like: `component`, `database`, `interface`, `actor`, `queue` |
| `_generate_flow_plantuml()` | Flow/Process | Activity diagram: `start`, `:action;`, `stop`, `note right` |
| `_generate_class_plantuml()` | Class | Class definition: `class Foo { +method(): Type }`, relationship arrows (`--\|>`, `..\|>`, `--o`, `--*`, `..>`) |
| `_generate_sequence_plantuml()` | Sequence | `participant "Name" as Name`, message arrows, `activate`/`deactivate` |

### save_failed_plantuml() (module-level)

Saves invalid PlantUML code to `<output_dir>/diagrams/failed_[analysis_id_][type].puml` for manual debugging. Used by both `PlantUMLGenerator.generate()` and `LLMDiagramGenerator`.

### DiagramCache (`cache.py`)

Persistent JSON-backed cache at `<kb_path>/diagram_cache/`.

**Cache key:** SHA-256 hash of sorted serialized `TechnicalFact` objects (first 16 hex chars), combined with `{analysis_id}_{diagram_type}`.

**Operations:**
- `get_cached_diagram()` — returns cached `Path` if hash matches and file exists; auto-cleans stale index entries
- `cache_diagram()` — writes entry with current timestamp
- `invalidate_cache(analysis_id)` — removes all entries for an analysis + deletes files
- `get_cache_stats()` — counts valid/invalid entries
- `cleanup(max_age_days)` — evicts entries older than threshold

### LLMDiagramGenerator (`llm_generator.py`)

Two-stage generation pipeline: **LLM → validation → fallback**.

**Spec objects** (Pydantic models):
- `ArchitectureDiagramSpec` — components, relationships, changed_elements, context
- `FlowDiagramSpec` — steps, changed_elements, context
- `ClassDiagramSpec` — classes, changed_classes, relationships, context
- `SequenceDiagramSpec` — participants, interactions, changed_elements, context

**Generation flow for each diagram type:**
1. Check `DiagramCache` (if `use_cache=True`)
2. Build spec from facts if not provided (`_build_*_spec()` methods)
3. Generate PlantUML code via `_generate_plantuml()`:
   a. If LLM available → `_generate_with_llm()` → structured output (`PlantUMLDiagram` model) → validation/repair
   b. If LLM unavailable → `_generate_with_template()` → calls `_generate_*_plantuml()` formatters
4. Render to PNG via `_render_plantuml()` → `PlantUMLGenerator.generate()`
5. Cache the result

**Spec derivation from facts:**
- **Architecture**: Filters facts by `architecture` and `api` categories; builds component names from `source_elements`
- **Flow**: Filters by `behavior` and `data_flow` categories; uses fact descriptions as steps
- **Class**: Loads AST data from `<kb_path>/ast_head/*.json` and semantic diff data; infers methods from `__init__` parameters; detects inheritance from source regex; identifies dependency via type hints in method signatures
- **Sequence**: Filters by `api`, `behavior`, `data_flow` categories with ≥2 source elements

**LLM prompt construction:**
- System prompt: rules for valid PlantUML (delimiters, syntax, highlighting changed elements with `<<new>>` stereotype or `#Green`)
- User prompt: facts listed with descriptions + spec details (components, relationships, changed markers)

## Flow

```
Technical Facts
      │
      ▼
LLMDiagramGenerator.generate_*_diagram()
      │
      ├── DiagramCache check ──── hit ──► return cached path
      │
      ▼ (cache miss)
  _build_*_spec(facts)
      │
      ▼
  _generate_plantuml()
      │
      ├── LLM available ──► _generate_with_llm() ──► PlantUMLDiagram (structured)
      │                           │
      │                           ▼
      │                     validate_and_repair() ──► PlantUMLGenerator
      │
      └── LLM unavailable ──► _generate_with_template() ──► _generate_*_plantuml()
                                                                   │
                                                                   ▼
                                                             PlantUML DSL (str)
      │
      ▼
  _render_plantuml()
      │
      ▼
  PlantUMLGenerator.generate()
      │
      ├── validate_and_repair() (optional)
      ├── java -jar plantuml.jar -t{png} ...
      │
      ▼
  DiagramCache.cache_diagram()
      │
      ▼
  (title, diagram_path, diagram_type)
```

## Integration

- **Consumed by:** `BaseOutputAgent._generate_diagrams_for_facts()` in `ggdes/agents/output_agents/base.py` — calls all diagram types with LLM-driven generation and caching
- **LLM dependency:** `LLMFactory.from_config(config)` for structured output; graceful fallback to templates when unavailable
- **Cache storage:** In knowledge base path (`get_kb_path(config, analysis_id) / "diagram_cache"`)
- **Output agents** (docx, pdf, pptx) embed the generated PNG/SVG paths into their respective document formats
