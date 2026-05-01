# ggdes/skills/docx/scripts/

## Responsibility

Python helper scripts for Word (DOCX) document manipulation. These scripts handle tracked change acceptance (via LibreOffice macros), comment addition at the XML level, and the Office file unpack/pack workflow. The `office/` subdirectory provides shared utilities for XML-level editing of Office files.

## Key Files

- `accept_changes.py`: Accepts all tracked changes in a DOCX file using a LibreOffice StarBasic macro. Sets up a headless LibreOffice profile, creates an `AcceptAllTrackedChanges` macro, and invokes it via `vnd.sun.star.script:` URI. The macro runs asynchronously (timeout triggers success). Exports `accept_changes(input_file, output_file) -> tuple[None, str]`.
- `comment.py`: Adds comments and replies to unpacked DOCX files at the XML level. Creates all required comment infrastructure files (`comments.xml`, `commentsExtended.xml`, `commentsIds.xml`, `commentsExtensible.xml`) if they don't exist, sets up relationships and content types, and generates unique hex IDs (`paraId`, `durableId`). Prints XML marker snippets for inserting into `document.xml`. Exports `add_comment(unpacked_dir, comment_id, text, author, initials, parent_id) -> tuple[str, str]`.
- `__init__.py`: Empty init file.
- `office/`: Subpackage providing Office file unpack/pack/validation utilities (documented in `office/codemap.md`).
- `templates/`: XML template files used by `comment.py` for initializing comment infrastructure — `comments.xml`, `commentsExtended.xml`, `commentsExtensible.xml`, `commentsIds.xml`, `people.xml`.

## Integration

- **Invoked by**: The DOCX skill (`ggdes/skills/docx/SKILL.md`) and the editing workflow — `accept_changes.py` for finalizing documents with tracked changes, `comment.py` for adding annotation comments.
- **Invocation**: Run as Python subprocesses: `python accept_changes.py <input.docx> <output.docx>`, `python comment.py <unpacked_dir> <comment_id> "<text>"` (optionally with `--parent` for replies).
- **Dependencies**: defusedxml, LibreOffice (for `accept_changes.py`).
