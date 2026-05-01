# ggdes/skills/pptx/scripts/

## Responsibility

Python helper scripts for PowerPoint (PPTX) file manipulation. These scripts support slide operations (add, duplicate, clean orphaned resources) and visual inspection (thumbnail grid generation). The `office/` subdirectory provides the unpack/pack workflow for XML-level editing of Office files.

## Key Files

- `add_slide.py`: Adds a new slide to an unpacked PPTX directory. Supports duplicating an existing slide or creating from a slide layout template. Handles all XML bookkeeping: content types, presentation relationships, slide ID generation. Exports `create_slide_from_layout()` and `duplicate_slide()`.
- `clean.py`: Removes unreferenced files from an unpacked PPTX directory. Cleans orphaned slides, trash directories, orphaned .rels files, unreferenced media/embeddings/charts/diagrams/themes/notes, and updates [Content_Types].xml. Exports `clean_unused_files(unpacked_dir) -> list[str]`.
- `thumbnail.py`: Creates JPEG thumbnail grids from PowerPoint slides. Converts PPTX → PDF via LibreOffice, then PDF → images via pdftoppm. Arranges thumbnails in a configurable grid (default 3 columns, max 6), labels each with its slide filename, and marks hidden slides with a crossed-out placeholder pattern. Exports `main()` via argparse.
- `__init__.py`: Empty init file making the scripts directory a Python package.
- `office/`: Subpackage providing Office file unpack/pack/validation utilities (documented in `office/codemap.md`).

## Integration

- **Invoked by**: The PPTX skill editing workflow (`ggdes/skills/pptx/editing.md`) — `thumbnail.py` is used for initial slide analysis, `add_slide.py` for creating slides during editing, and `clean.py` for cleanup before packing.
- **Invocation**: Run as Python subprocesses: `python add_slide.py <dir> <source>`, `python clean.py <dir>`, `python thumbnail.py <input.pptx> [output_prefix]`.
- **Dependencies**: defusedxml, Pillow, python-pptx (for the office subpackage).
