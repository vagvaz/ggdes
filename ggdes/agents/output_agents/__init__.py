"""Output agents for document generation."""

from ggdes.agents.output_agents.base import OutputAgent
from ggdes.agents.output_agents.docx_agent import DocxAgent
from ggdes.agents.output_agents.markdown_agent import MarkdownAgent
from ggdes.agents.output_agents.pdf_agent import PdfAgent
from ggdes.agents.output_agents.pptx_agent import PptxAgent

__all__ = [
    "OutputAgent",
    "MarkdownAgent",
    "DocxAgent",
    "PptxAgent",
    "PdfAgent",
]"
