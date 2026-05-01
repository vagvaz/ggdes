# ggdes/parsing/

## Responsibility

Provides tree-sitter-based AST parsing for Python and C++ source files. Extracts structured `CodeElement` representations (functions, methods, classes) from source code, supporting both full-directory scans and incremental parsing of only changed files plus their transitive dependents. The parsed elements feed into semantic diff analysis, technical fact synthesis, code reference validation, and document generation.

## Design

### Single module: `ast_parser.py`

| Class / Function | Role |
|---|---|
| `ParseResult` | Dataclass holding one file's parse outcome: file path, language, extracted `CodeElement` list, the tree-sitter `Tree` (used for downstream queries), success flag, and optional error message. |
| `ASTParser` | Main parser class. Manages lazy-loaded tree-sitter `Language` and `Parser` instances per supported language. Provides four parse entry points and a reference-finder. |

### Supported languages and extensions

| Extension | Language ID | Notes |
|---|---|---|
| `.py` | `python` | Uses `tree_sitter_python` |
| `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h` | `cpp` | Uses `tree_sitter_cpp`; `.h` is ambiguously C/C++ — the C++ parser is tried. |

Languages are loaded lazily in `_init_languages()` and `_get_parser()`. If a grammar package is not installed, the parser degrades gracefully (prints a warning, returns `ParseResult(success=False)`). This allows the rest of the pipeline to proceed even when one language's grammar is missing.

### Element extraction strategy

Both `_extract_python_elements` and `_extract_cpp_elements` recursively walk the tree-sitter CST via a nested `extract_from_node` closure:

- **Python**: Recognises `function_definition` and `class_definition` nodes. For each:
  - Extracts name, parameters (signature), docstring, decorators, and line range.
  - Nested functions inside a class become `CodeElementType.METHOD` with `parent` set to the class name; top-level functions become `CodeElementType.FUNCTION`.
  - Class elements record their child method names in `children`.
  - Source code for each element is optionally captured via `_get_element_source()` for grounding LLM output.

- **C++**: Recognises `function_definition` with `function_declarator` (extracting name from the inner declarator and parameters from the parameter list), and `class_specifier` / `struct_specifier` for class extraction. C++ docstrings are not extracted (always `None`). Child-method tracking is a stub (`pass` on member declarations).

### Key design decisions

1. **Lazy language loading** — Grammars are loaded on first use, not at construction. This means the parser can be instantiated even when `tree-sitter-python` or `tree-sitter-cpp` is absent from the environment.

2. **Graceful degradation** — Every failure path (unsupported extension, missing parser, I/O error, parse crash) returns a `ParseResult(success=False, error_message=...)` rather than raising. Callers inspect the `success` flag.

3. **Relative path support** — The `relative_to` parameter normalises file paths in all output. This is essential for making diagnostics, facts, and documents use paths relative to the repository root.

4. **Element source capture** — `source_code` on each `CodeElement` is the literal source lines from disk. This enables downstream validators (`CodeReferenceValidator`) and output agents to embed real code snippets, preventing hallucination.

## Flow

```
Pipeline entry points
        │
        ├── parse_file(file_path) ──────→ detect_language()
        │                                    │
        │                              ┌─────┴──────┐
        │                              │  python     │ cpp
        │                              ▼             ▼
        │                         _extract_    _extract_
        │                         python_      cpp_
        │                         elements     elements
        │                              │             │
        │                              ▼             ▼
        │                         ParseResult (elements, tree)
        │
        ├── parse_directory(dir) ───── rglob → parse_file (each supported file)
        │
        ├── parse_files(list) ──────── explicit list → parse_file (each)
        │
        └── parse_incremental(dir, changed_files)
                  │
                  ├── convert relative paths → absolute Path objects
                  ├── parse changed files (set)
                  ├── find_referenced_files(changed, dir, max_depth)
                  │       └── text-based import/include search (regex)
                  │           Python: "from X import" / "import X"
                  │           C++:    #include "X" / #include <X>
                  └── parse changed + referenced files
```

### `parse_incremental` detail

Used by the pipeline stage `ast_parsing_head` (and `ast_parsing_base` when semantic diff is enabled). Given the list of files changed in a commit range:

1. Validates each path exists under the worktree directory.
2. Optionally (default: `include_referenced=True`) discovers files that `import` or `#include` the changed files via `find_referenced_files()`.
3. Parses the merged set — changed files plus their transitive dependents up to `max_referenced_depth` (default: 1).

This avoids re-parsing the entire repository on every analysis, which is critical for large codebases.

### `find_referenced_files` detail

Text-based reference detection using regex:
- **Python**: Matches `from <module> import` and `import <module>` patterns from the seed file's module path and bare filename.
- **C++**: Matches `#include "filename"` and `#include <filename>` with `.h`/`.hpp` fallback.
- Iterates up to `max_depth` levels, each level searching the entire directory tree.

This is intentionally simpler than full import-resolution — it's a heuristic for "files likely affected by this change."

## Integration

### Consumed by (imports `ggdes.parsing`)

| Module | How it uses `ASTParser` |
|---|---|
| `ggdes.pipeline` | Creates an `ASTParser` instance. Calls `parse_directory()` for base+head worktrees (full mode) or `parse_incremental()` for changed-only mode. Results flow into `CodeElement` lists stored on `AnalysisResult`. |
| `ggdes.semantic_diff` (`SemanticDiffAnalyzer`) | Lazily loads `ASTParser` via `_get_ast_parser()` for C++ tree-sitter queries in `_parse_cpp_elements()` and `_get_cpp_tree()`. Also uses stdlib `ast` for Python. |

### Produces (schemas consumed downstream)

| Output | Schema type | Consumers |
|---|---|---|
| `ParseResult.tree` | `tree_sitter.Tree` | `SemanticDiffAnalyzer` (C++ Queries), `CodeReferenceValidator` |
| `ParseResult.elements` | `list[CodeElement]` | `AnalysisResult.code_elements` → technical author → document plans |
| `CodeElement.source_code` | `str` or `None` | `CodeReferenceValidator`, output agents (fact grounding) |

### Pipeline stage mapping

| Pipeline stage | Parser method called | Purpose |
|---|---|---|
| `ast_parsing_base` | `parse_directory()` (full) or `parse_files()` (incremental) | Parse base commit for semantic diff |
| `ast_parsing_head` | `parse_incremental()` or `parse_directory()` | Parse HEAD commit; elements feed technical author |

### Schema dependency

`ASTParser` imports `CodeElement` and `CodeElementType` from `ggdes.schemas` — this is the only external dependency. All output is expressed in terms of these schema types, making the parser interchangeable as long as the same schema types are produced.
