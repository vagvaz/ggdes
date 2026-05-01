# ggdes/skills/docx/scripts/office/

## Responsibility

Core Office file manipulation utilities shared by both the DOCX and PPTX skill workflows. Provides the unpack-edit-pack cycle: extract Office XML from ZIP, provide XML-level editing helpers, validate against OOXML XSD schemas, and repack into a valid Office file.

## Key Files

- `unpack.py`: Extracts an Office file (DOCX/PPTX/XLSX) to a directory for editing. Pretty-prints XML files, optionally merges adjacent runs and simplifies tracked changes (DOCX only), and escapes smart quotes to XML entities. Exports `unpack(input_file, output_directory, merge_runs=True, simplify_redlines=True)`.
- `pack.py`: Packs an edited directory back into an Office file (DOCX/PPTX/XLSX). Runs validation with auto-repair before packing, condenses XML formatting (removes whitespace/comments from non-`w:t` elements). Exports `pack(input_directory, output_file, original_file=None, validate=True, infer_author_func=None)`.
- `validate.py`: CLI tool for validating Office document XML against XSD schemas and tracked change integrity. Accepts either an unpacked directory or a packed Office file. Supports `--auto-repair` and `--original` for differential validation. Exports `main()` via argparse.
- `soffice.py`: LibreOffice integration helper for environments where AF_UNIX sockets may be blocked (e.g., sandboxed VMs). Detects the restriction at runtime and applies an LD_PRELOAD C shim. Exports `get_soffice_env() -> dict` and `run_soffice(args, **kwargs) -> CompletedProcess`.
- `helpers/`: Subpackage with DOCX-specific helpers — `merge_runs.py` (merge adjacent formatting-identical runs) and `simplify_redlines.py` (merge adjacent tracked changes from same author).
- `validators/`: Subpackage with OOXML validation classes — `BaseSchemaValidator`, `DOCXSchemaValidator`, `PPTXSchemaValidator`, `RedliningValidator`.
- `schemas/`: OOXML XSD schema files from ISO/IEC 29500-4:2016, ECMA, and Microsoft extensions, used by the validators for XSD validation.

## Integration

- **Invoked by**: Both `docx/scripts` and `pptx/scripts` workflows. `unpack.py` and `pack.py` are the entry points for the XML editing workflow described in `ggdes/skills/docx/SKILL.md` and `ggdes/skills/pptx/editing.md`.
- **Shared code**: These files are identical copies in both `docx/scripts/office/` and `pptx/scripts/office/`. The `office/` package is referenced via `from office.soffice import ...` and `from validators import ...` in the scripts, relying on the package layout within each format's `scripts/` directory.
- **Dependencies**: defusedxml, lxml (for XSD validation), python-pptx.
