# ggdes/validation/

## Responsibility

Validation layer for LLM outputs and pipeline inputs. Provides:
1. **Code reference validation** — Checks LLM-generated text against git diffs and
   AST data to detect hallucinated file paths, function names, class names, and
   code blocks. Supports auto-correction via retry with the LLM.
2. **Input validation** — Validates commit ranges, diff sizes, and file types
   before pipeline processing.
3. **Schema validation** — Validates data against Pydantic models.
4. **AST-based fact validation** — Checks technical facts against parsed code
   elements for accuracy.

## Design

### File Layout

| File | Key Exports | Responsibility |
|---|---|---|
| `code_references.py` | `CodeReferenceValidator`, `CodeReference`, `ReferenceValidationResult`, `CodeBlockValidationResult`, `ProseClaim`, `ProseClaimResult` | Post-generation code reference validation against diff + AST |
| `validators.py` | `InputValidator`, `SchemaValidator`, `ASTValidator`, `ValidationPipeline` | Pre-processing input validation, fact validation against AST |

### CodeReferenceValidator (`code_references.py`)

Initialized with:
- `repo_path: Path` — Repository root for file existence checks
- `changed_files: list[str]` — Files changed in the diff
- `code_elements: dict[str, dict]` — Parsed AST elements (name → info)
- `diff_content: str` — Git diff content for snippet matching
- `source_code: dict[str, str]` — Optional element source code for block validation

**Three-layer validation:**

#### 1. Reference Validation (`validate_references_in_text`)

Extracts and validates code references from text:

- **File paths:** Backtick-quoted or "in ..." patterns (`.py`, `.cpp`, `.h`, `.js`, etc.)
  - Checks file exists in `changed_files` set AND snippet matches diff content
  - Falls back to checking file existence on disk
- **Function calls:** Identifiers followed by `()` (with skip list for builtins)
  - Checks name exists in `code_elements`
- **Class references:** CamelCase identifiers followed by `(` or `.`
  - Checks name exists in `code_elements`

#### 2. Code Block Validation (`validate_code_blocks`)

Validates fenced code blocks (``` ... ```) against actual source code:
- Normalizes whitespace and case
- Computes similarity via Jaccard + bigram overlap (weighted 40/60)
- Default threshold: 0.6 (60%)
- Skips blocks shorter than 20 characters (too short to validate meaningfully)
- Checks against both `source_code` dict and `diff_snippets` index
- Returns `CodeBlockValidationResult` with matched element and similarity score

#### 3. Prose Claim Validation (`validate_prose_claims`)

Extracts factual claims from prose and verifies them:
- **Existence claims:** "X was removed / added / deprecated / is new"
  - Checks if element name exists in `code_elements` → validates or invalidates the claim
- **Parameter claims:** "X has Y parameters"
  - Parses signature from AST and compares parameter count
- **Modification claims:** "X now requires / no longer supports"
  - Validates element exists; deeper verification requires tool executor
- Claim patterns defined as regex rules with subject/predicate extraction

#### Correction Flow (`validate_and_correct`)

```
validate_and_correct(llm_output, llm_provider, max_corrections=2)
    ↓
For attempt 0..max_corrections:
    ↓
  Run reference validation + code block validation + prose claim validation
    ↓
  If all valid → return output
    ↓
  If invalid and attempt < max_corrections:
    ↓
    Build correction prompt (invalid refs + invalid blocks + invalid prose)
    ↓
    Call llm_provider.generate() with correction prompt
    ↓
    temperature = 0.3 + (attempt * 0.1)
    ↓
    Loop
    ↓
  If max corrections exhausted → append HTML warning comment to output
```

### InputValidator (`validators.py`)

Pre-processing validation:

| Method | Validates | Checks |
|---|---|---|
| `validate_commit_range(commit_range)` | Git commit range format | `..` separator, commits exist via `git cat-file` |
| `validate_diff_size(diff_content)` | Diff content size | Line count ≤ `MAX_DIFF_LINES` (10,000) |
| `validate_file_type(file_path)` | File type support | Binary detection (null byte check), extension whitelist (`.py`, `.cpp`, `.h`, `.md`, etc.), size ≤ 10MB |

### ASTValidator (`validators.py`)

Validates technical facts against AST elements:

| Method | Purpose |
|---|---|
| `validate_fact(fact)` | Checks `fact.source_elements` exist in parsed AST; warns on low confidence |
| `validate_facts(facts)` | Batch validation |
| `check_hallucination(text)` | Regex search for unknown `name()` patterns in generated text |

### SchemaValidator (`validators.py`)

- `validate_pydantic_model(data, model_class)` — Creates instance and catches
  `pydantic.ValidationError`, collecting field-level errors with location paths.

### ValidationPipeline (`validators.py`)

Composite validator that runs multiple checks and aggregates results:
- `add_check(name, result)` — Register a check result
- `get_summary()` — Combined `ValidationResult` with prefixed error messages
- `has_critical_errors()` — True if any errors exist

## Flow

### Pre-processing
```
Input data (commit range, files, diffs)
    ↓
InputValidator.validate_commit_range()
InputValidator.validate_diff_size()
InputValidator.validate_file_type()  (per changed file)
    ↓
ValidationPipeline.get_summary() → proceed or abort
```

### Post-generation (LLM output)
```
LLM generates technical facts / documentation
    ↓
CodeReferenceValidator.validate_and_correct(output, llm_provider)
    ↓
  validate_references_in_text() → file paths, function names, class names
  validate_code_blocks() → fenced code blocks vs. real source
  validate_prose_claims() → existence, parameter, modification claims
    ↓
  If invalid: generate correction prompt → LLM regenerates → re-validate
    ↓
  (max 2 correction rounds)
    ↓
Validated output (with warnings appended if corrections exhausted)
```

### Fact validation
```
Technical facts from LLM
    ↓
ASTValidator.validate_facts(facts)
    ↓
  Each source_element checked against parsed AST
  Confidence score checked for warnings
    ↓
ValidationResult (proceed with valid facts / surface errors)
```

## Integration

- **`CodeReferenceValidator`** is used by analysis agents (`ggdes/agents/`) in
  the technical author and coordinator stages to validate LLM output before
  storing technical facts and document plans.
- **`InputValidator`** is used at the start of `ggdes/pipeline.py` during the
  git analysis stage to validate inputs before processing.
- **`ASTValidator`** is used in the technical author stage to validate facts
  against parsed AST data.
- **`ValidationPipeline`** provides a unified interface for the pipeline to
  run all validation checks and decide whether to proceed.
- **`SchemaValidator`** is used internally during metadata deserialization.
- The correction flow in `CodeReferenceValidator.validate_and_correct()` uses
  an `LLMProvider` instance (from `ggdes.llm`) to regenerate corrected output.
