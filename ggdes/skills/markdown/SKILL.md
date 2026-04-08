---
name: markdown
description: Use this skill when creating or editing Markdown documentation files. Markdown is the default output format for technical documentation, README files, and project documentation. Use for generating structured technical documents with code blocks, tables, diagrams, and navigation links. Markdown works well for web-based documentation, GitHub/GitLab repositories, and static site generators.
license: Proprietary. LICENSE.txt has complete terms
---

# Markdown Documentation Guide

## Content Guidelines for Markdown Documents

When creating Markdown documents for technical documentation:

### Document Structure
- **Title**: Use a single H1 (# Title) at the top
- **Executive summary**: Brief paragraph after the title
- **Table of contents**: Use `[TOC]` or manual links for docs > 5 sections
- **Sections**: Use H2 (##) for main sections, H3 (###) for subsections

### Content Density Rules
- **Paragraph length**: 3-5 sentences maximum
- **Code blocks**: Always specify language for syntax highlighting
- **Line length**: 80-100 characters for readability in raw markdown
- **Lists**: Use bullet points for related items, numbers for sequences

### Markdown-Specific Features
- **Code blocks**: Use triple backticks with language:
  ```python
  def example():
      return "syntax highlighted"
  ```
- **Tables**: Use for structured data comparison
- **Callouts**: Use blockquotes (> ) for important notes
- **Links**: Use relative links for internal references

### Visual Elements
Embed diagrams using Mermaid or PlantUML:

```markdown
## Architecture Diagram

![System Architecture](diagrams/architecture.png)
```

**Required diagrams:**
- Architecture overview
- Data flow diagrams
- Class/ER diagrams
- Sequence diagrams for complex interactions

### Diagram Generation
```python
from ggdes.diagrams import PlantUMLGenerator, generate_architecture_diagram

# Create diagram
plantuml_code = generate_architecture_diagram(
    components=[
        {"name": "Frontend", "type": "service"},
        {"name": "Backend", "type": "service"},
        {"name": "Database", "type": "database"},
    ],
    relationships=[
        ("Frontend", "Backend", "API calls"),
        ("Backend", "Database", "queries"),
    ],
)

# Generate
generator = PlantUMLGenerator()
diagram_path = generator.generate(
    plantuml_code,
    output_path=Path("docs/diagrams/architecture.png"),
    format="png",
)
```

### Navigation and Organization
- **Links**: Add "Previous" / "Next" navigation for multi-page docs
- **Anchors**: Use explicit heading IDs for deep linking
- **Summary section**: Bullet list of key changes at the top
- **Appendix**: Move detailed API docs to the end

### Best Practices
- **Use headers consistently**: Don't skip levels (H1 -> H3)
- **Alt text**: Always include descriptive alt text for images
- **Front matter**: Use YAML front matter for metadata (title, date, author)
- **Line breaks**: Use two spaces or `<br>` for intentional line breaks
- **Horizontal rules**: Use `---` to separate major sections

### Code Documentation
- **Inline code**: Use backticks for `function_names()` and `ClassNames`
- **Code blocks**: Include language and optional filename:
  ```python
  # config.py
  DEBUG = True
  ```
- **Diffs**: Show changes with +/- markers for clarity

---

## Markdown Syntax Reference

### Headers
```markdown
# H1 Title
## H2 Section
### H3 Subsection
#### H4 Detail
```

### Emphasis
```markdown
*italic* or _italic_
**bold** or __bold__
~~strikethrough~~
`inline code`
```

### Lists
```markdown
- Bullet item
- Another item
  - Nested item
  - Another nested

1. Numbered item
2. Second item
   1. Nested numbered
   2. Another nested
```

### Links and Images
```markdown
[Link text](URL)
[Relative link](./other-file.md)
![Alt text](image.png)
```

### Tables
```markdown
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data 1   | Data 2   | Data 3   |
| Data 4   | Data 5   | Data 6   |
```

### Blockquotes
```markdown
> Important note or callout
> Multiple lines are supported
```

### Code Blocks
```markdown
```python
def example():
    return "Hello World"
```

```json
{
  "key": "value",
  "number": 42
}
```
```

### Horizontal Rule
```markdown
---
```

---

## Dependencies

No additional dependencies required - Markdown is plain text. For diagram generation:
- `pip install ggdes` (for PlantUML integration)
- Java runtime (for PlantUML)
