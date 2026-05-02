# GGDes Benchmark Suite

Reproducible benchmarks for evaluating GGDes against real-world C++ and Python codebases.

## Benchmarks

### C++ (or C) — Databases

| ID | Name | Commits | Size | What it tests |
|----|------|---------|------|---------------|
| `duckdb-asof-join` | DuckDB AsOf Join | v1.4.0..v1.5.0 | ~300k LOC C++ | Feature-focused semantic diff on a complex query engine feature spanning binder, optimizer, execution, threading |
| `duckdb-geometry` | DuckDB GEOMETRY Rework | v1.4.0..v1.5.0 | ~300k LOC C++ | Spatial type system changes: logical type, statistics, filter pushdown, Parquet/Arrow |
| `duckdb-binder-refactor` | DuckDB Binder Refactoring | v1.4.0..v1.5.0 | ~300k LOC C++ | Architectural refactoring detection — internal restructuring with no user-facing SQL diff |
| `postgres-json-sql` | PostgreSQL SQL/JSON | REL_17_0..REL_18_0 | ~1M LOC C | Major SQL standard feature addition in a C codebase |
| `postgres-incremental-backup` | PostgreSQL Incremental Backup | REL_17_0..REL_18_0 | ~1M LOC C | Storage engine and recovery subsystem changes |

### C++ — Libraries

| ID | Name | Commits | Size | What it tests |
|----|------|---------|------|---------------|
| `fmtlib-11-to-12` | fmtlib v11→v12 | 11.0.0..12.0.0 | ~15k LOC headers | Template-heavy C++, constexpr, C++20 modules, API deprecation |

### Python

| ID | Name | Commits | Size | What it tests |
|----|------|---------|------|---------------|
| `fastapi-streaming` | FastAPI streaming/SSE | 0.133.0..0.136.0 | ~8k LOC Python | API surface changes: decorators, routes, type annotations, Starlette upgrade |
| `pydantic-v2-13` | Pydantic v2.12→v2.13 | v2.12.0..v2.13.0 | ~15k LOC Python | pydantic-core merge (Rust), polymorphic serialization, schema/validation type system |

## Prerequisites

1. **GGDes** installed (`uv sync` in project root)
2. **LLM provider** configured in `ggdes.yaml` (see `ggdes/llm/` for options)
3. **~10GB disk space** for cloned repos
4. Optional: **Java** (for PlantUML diagrams in output)

## Usage

```bash
# 1. Clone all benchmark repos
./setup.sh

# 2. List available benchmarks
./run.sh --list

# 3. Run a single benchmark
./run.sh duckdb-asof-join

# 4. Run all benchmarks
./run.sh

# 5. Quick setup + run on a single benchmark
./setup.sh fmtlib-11-to-12 && ./run.sh fmtlib-11-to-12
```

## Output

- GGDes saves analyses to `~/.ggdes/analyses/` (the Knowledge Base)
- A summary CSV is written to `results/results.csv`
- Log files for parallel runs are at `results/<benchmark-id>.log`

## Adding a Benchmark

Add an entry to `benchmarks.yaml`. Each test requires a unique `id`, a human-readable `name`, a `description`, the repo details, and a `ggdes` block with per-test CLI configuration:

```yaml
- id: my-benchmark
  name: "My Benchmark"
  description: >
    What this benchmark tests and why. This description is shown in the
    run output and helps evaluate whether the generated docs capture
    the right changes.
  repo: "https://github.com/owner/repo.git"
  dir: "my-benchmark"            # Directory under repos/
  base_tag: "v1.0"               # Base commit (older)
  head_tag: "v2.0"               # Head commit (newer)
  type: feature-focused           # or full-release
  ggdes:
    feature: "Natural language description passed to --feature"
    formats: "markdown"           # Output formats
    storage: "summary"            # Conversation storage level
    auto: true                    # Non-interactive mode
    semantic_diff: true           # Enable/disable semantic diff
    # Optional LLM overrides — omit to use ggdes.yaml defaults
    # provider: "anthropic"
    # model_name: "claude-3-5-sonnet-20241022"
    # api_key: "${ANTHROPIC_API_KEY}"
```

## Metrics to Evaluate

After running, check each analysis in the GGDes KB:

- **Quality**: Are the technical facts accurate? Do they capture the right changes?
- **Coverage**: Does the semantic diff find meaningful changes? Are API changes detected?
- **Performance**: How long does each stage take (git analysis, AST parsing, semantic diff, LLM calls)?
- **Scale**: How does it handle DuckDB vs PostgreSQL vs fmtlib? (300k LOC vs 1M LOC vs 15k LOC)
