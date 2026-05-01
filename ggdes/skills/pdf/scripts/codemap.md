# ggdes/skills/pdf/scripts/

## Responsibility

Python helper scripts for PDF form analysis, extraction, filling, and validation. These scripts are invoked as subprocesses by the workflow documented in `ggdes/skills/pdf/forms.md` and referenced in the PDF skill for programmatic PDF manipulation.

## Key Files

- `check_bounding_boxes.py`: Validates bounding boxes in extracted form field JSON for overlaps and insufficient height. Exports `get_bounding_box_messages(fields_json_stream) -> list[str]`. Used to catch layout errors before field filling.
- `check_fillable_fields.py`: Checks if a PDF has AcroForm fillable fields using pypdf's `PdfReader.get_fields()`. Outputs a simple status message. Used as the first step in the form filling workflow.
- `convert_pdf_to_images.py`: Converts PDF pages to PNG images using pdf2image (`convert_from_path`). Resizes large images to `max_dim` (default 1000px). Exports `convert(pdf_path, output_dir, max_dim=1000)`.
- `create_validation_image.py`: Overlays bounding boxes on a page image for visual validation — red for entry boxes, blue for label boxes. Exports `create_validation_image(page_number, fields_json_path, input_path, output_path)`.
- `extract_form_field_info.py`: Extracts fillable form field metadata from a PDF (field IDs, types, pages, rects, choice options, radio button groups). Exports `get_field_info(reader) -> list[dict]` and `write_field_info(pdf_path, json_output_path)`. Used for fillable PDF forms.
- `extract_form_structure.py`: Analyzes non-fillable PDFs to detect text labels, horizontal lines, checkboxes (small rectangles), and row boundaries using pdfplumber. Exports `extract_form_structure(pdf_path) -> dict`. Used for non-fillable forms.
- `fill_fillable_fields.py`: Fills AcroForm fields in a PDF from a JSON values file using pypdf's `PdfWriter.update_page_form_field_values()`. Includes field value validation and a monkeypatch for pypdf choice handling. Exports `fill_pdf_fields(input_pdf_path, fields_json_path, output_pdf_path)`.
- `fill_pdf_form_with_annotations.py`: Fills non-fillable PDF forms by adding FreeText annotations at specified bounding box coordinates. Handles both image-coordinate and PDF-coordinate transformations. Exports `fill_pdf_form(input_pdf_path, fields_json_path, output_pdf_path)`.

## Integration

- **Invoked by**: The PDF skill workflow (`ggdes/skills/pdf/forms.md`) instructs the LLM to run these scripts as Python subprocesses in a specific order: check fillable → extract fields → validate → fill.
- **Dependencies**: pypdf, pdfplumber, pdf2image, Pillow, defusedxml.
