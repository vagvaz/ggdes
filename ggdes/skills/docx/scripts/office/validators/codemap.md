# ggdes/skills/docx/scripts/office/validators/

## Responsibility

OOXML validation framework for Office documents. Provides XSD schema validation, structural integrity checks, tracked change validation, and auto-repair for common issues. Used by `pack.py` and `validate.py` to ensure generated Office files are spec-compliant and non-corrupt.

## Key Files

- `__init__.py`: Exports `BaseSchemaValidator`, `DOCXSchemaValidator`, `PPTXSchemaValidator`, `RedliningValidator`.
- `base.py` (852 lines): Base validator class with shared validation logic — XML well-formedness, namespace declarations, unique ID checking (per-file and global scope), file reference integrity (`.rels` target resolution, unreferenced file detection), relationship ID cross-referencing, content type declarations, XSD schema validation (differential against original file), whitespace preservation repair, and MC ignorable namespace handling. Maps XML files to OOXML XSD schemas via `SCHEMA_MAPPINGS`.
- `docx.py` (445 lines): DOCX-specific validator extending `BaseSchemaValidator`. Adds whitespace preservation checks on `w:t` elements, deletion validation (`w:t` within `w:del`), insertion validation (`w:delText` within `w:ins`), paragraph count comparison (original vs modified), ID constraints (`paraId`/`durableId` hex value limits), comment marker pairing (rangeStart/rangeEnd/reference matching), and auto-repair of `durableId` values exceeding OOXML limits.
- `pptx.py` (272 lines): PPTX-specific validator extending `BaseSchemaValidator`. Adds UUID ID format validation (hex character checks), slide layout ID cross-referencing against master relationships, duplicate slide layout detection per slide, and notes slide reference uniqueness validation.
- `redlining.py` (246 lines): Validates tracked change integrity in DOCX files. Compares text content after stripping the specified author's tracked changes — any text mismatch indicates an improperly tracked edit. Uses git word-diff for detailed difference reporting. Supports author inference for validation.

## Integration

- **Used by**: `pack.py` (runs validation with auto-repair before packing) and `validate.py` (standalone CLI validation tool) in the parent `office/` directory.
- **Validation flow**: `repair()` is called first (whitespace + durable ID fixes), then `validate()` runs all checks. For differential validation, the original file's errors are subtracted from the modified file's errors to report only new issues.
- **Dependencies**: lxml (XSD validation), defusedxml (safe XML parsing).
