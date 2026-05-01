# ggdes/rendering/

## Responsibility

Render Markdown content to PNG images for visual embedding in documents. Used when output agents need to include rendered markdown sections (e.g., executive summaries, changelogs) as image assets inside DOCX, PDF, or PPTX files.

## Files

| File | Role |
|------|------|
| `__init__.py` | Package marker |
| `markdown_to_png.py` | `MarkdownToPngRenderer` class — Playwright-based HTML→PNG pipeline |

## Design

### MarkdownToPngRenderer

A context-managed renderer that converts Markdown into styled HTML and screenshots it with headless Chromium (Playwright).

**Constructor:**
```python
MarkdownToPngRenderer(output_dir, theme="light", width=1200)
```
- `output_dir`: Where generated PNGs are saved
- `theme`: `"light"` or `"dark"` — controls CSS color palette
- `width`: Viewport width in pixels (also sets HTML max-width)

**Cached Browser Instance:**
- `_get_browser()` lazily creates a Playwright `async_playwright` context and launches headless Chromium
- Reused across multiple `_render_html_to_png_async()` calls within a single `render()` invocation
- `close()` tears down both browser and Playwright context; safe to call multiple times
- Context manager support (`__aenter__`/`__aexit__`) for `async with` usage

**Entry Point — `render()` method:**
```python
render(markdown_path: Path, sections: bool = False) -> list[Path]
```
- Reads markdown file content
- If `sections=True`: splits by `##` headings (H2) and renders each as a separate PNG named `{safe_title}_{index:03d}.png` or `section_{index:03d}.png`
- If `sections=False`: renders entire document as one PNG named `{markdown_stem}.png`
- Always closes the browser in a `finally` block to prevent resource leaks
- Uses `asyncio.run()` as a sync wrapper around the async Playwright calls

**Markdown→HTML Pipeline — `render_to_html()`:**

1. Converts markdown to HTML using `markdown` library with extensions:
   - `fenced_code` — triple-backtick code blocks
   - `codehilite` — Pygments syntax highlighting
   - `tables` — markdown table support
   - `toc` — table of contents generation

2. Generates Pygments CSS for syntax highlighting

3. Builds a complete HTML document with CSS styling:

| CSS Concern | Light Theme | Dark Theme |
|-------------|-------------|------------|
| Background | `#ffffff` | `#1e1e1e` |
| Text | `#333333` | `#e0e0e0` |
| Headings | `#1a1a1a` | `#ffffff` |
| Code BG | `#f5f5f5` | `#2d2d2d` |
| Borders | `#e0e0e0` | `#444444` |
| Links | `#0066cc` | `#66b3ff` |

- Monospace font (`Courier New`) for code blocks to preserve ASCII art alignment
- `white-space: pre` on code blocks to prevent wrapping
- `box-sizing: border-box` throughout
- Responsive max-width matching configured viewport width
- Proper table styling with collapsed borders and header shading

**Async Playwright Rendering — `_render_html_to_png_async()`:**

1. Writes HTML to a temporary file
2. Opens a new browser context with configured viewport and `device_scale_factor=2` (high-DPI output)
3. Navigates to `file://{temp_path}`
4. Waits for `networkidle` (fonts loaded, page stable)
5. Takes a full-page screenshot (no clipping)
6. Cleans up temp file in `finally` block

**Sync Wrapper — `_render_html_to_png()`:**
```python
return asyncio.run(self._render_html_to_png_async(html, output_path))
```

**Section Splitting — `_split_by_sections()`:**

Splits markdown content on `## ` headings (but not `### ` or deeper), returning `[(title, content)]` tuples. Content before the first `## ` gets `title=""`. If no headings are found, returns the entire content as a single section.

## Flow

```
Markdown File Path
      │
      ▼
MarkdownToPngRenderer.render()
      │
      ├── sections=True
      │     │
      │     ▼
      │   _split_by_sections(content)
      │     │
      │     ▼  for each (title, content)
      │   render_to_html(content) ──► markdown + Pygments ──► full HTML doc
      │     │
      │     ▼
      │   asyncio.run(_render_html_to_png_async(html, path))
      │         │
      │         ├── _get_browser() ──► lazy Playwright/Chromium init
      │         ├── write temp .html
      │         ├── page.goto(file://)
      │         ├── page.wait_for_load_state("networkidle")
      │         ├── page.screenshot(full_page=True)
      │         └── cleanup temp file
      │
      ├── sections=False
      │     └── same pipeline, single output
      │
      └── finally: asyncio.run(self.close())
```

## Integration

- **Consumed by:** Output agents (docx, pdf, pptx) that need to embed rendered markdown as images
- **Required dependencies:** `pip install ggdes[render]` + `playwright install chromium`
- **Not cached** — each call re-renders; callers should manage their own caching if needed
- **Context manager** recommended: `async with MarkdownToPngRenderer(...) as renderer:` for proper cleanup
