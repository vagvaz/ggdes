# ggdes/skills/docx/scripts/office/helpers/

## Responsibility

Helper utilities for DOCX XML normalization, used by the unpack workflow to simplify the XML before editing. These reduce complexity by merging redundant XML elements, making the document structure easier for LLMs to edit.

## Key Files

- `merge_runs.py`: Merges adjacent `<w:r>` elements that have identical `<w:rPr>` formatting properties in DOCX `document.xml`. Also strips `rsid` attributes from runs (revision metadata) and removes `<w:proofErr>` elements (spell/grammar markers) that block merging. Exports `merge_runs(input_dir: str) -> tuple[int, str]`. Works on runs inside paragraphs and tracked changes (`<w:ins>`, `<w:del>`).
- `simplify_redlines.py`: Merges adjacent tracked changes (`<w:ins>` or `<w:del>`) from the same author into single elements. Only merges same-type elements that are truly adjacent (only whitespace between them). Also provides `get_tracked_change_authors(doc_xml_path) -> dict[str, int]` and `infer_author(modified_dir, original_docx, default="Claude") -> str` for detecting which author made changes. Exports `simplify_redlines(input_dir: str) -> tuple[int, str]`.
- `__init__.py`: Empty init file.

## Integration

- **Used by**: `unpack.py` in the parent `office/` directory — `merge_runs()` and `simplify_redlines()` are called during unpacking when `suffix == ".docx"`.
- **Dependencies**: defusedxml (for safe minidom parsing), xml.etree.ElementTree (for `get_tracked_change_authors`).
