"""Structured output schemas for GGDes."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    """Type of code change."""

    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    DOCS = "docs"
    TEST = "test"
    CHORE = "chore"
    PERFORMANCE = "performance"
    SECURITY = "security"


class ImpactLevel(str, Enum):
    """Impact level of a change."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FileChange(BaseModel):
    """Change information for a single file."""

    path: str = Field(description="File path relative to repo root")
    change_type: str = Field(
        description="Type of change: added, modified, deleted, renamed"
    )
    lines_added: int = Field(default=0, description="Number of lines added")
    lines_deleted: int = Field(default=0, description="Number of lines deleted")
    summary: str = Field(description="Brief summary of what changed in this file")
    relevant_line_ranges: list[tuple[int, int]] | None = Field(
        default=None,
        description="Line ranges relevant to the feature (1-based, inclusive). "
        "Only set when semantic filtering is enabled. None means all lines are relevant.",
    )


class ChangeSummary(BaseModel):
    """Summary of a git change (commit or range)."""

    commit_hash: str | None = Field(None, description="Commit hash if single commit")
    commit_range: str | None = Field(
        None, description="Commit range if multiple commits"
    )
    change_type: ChangeType = Field(description="Primary type of change")
    description: str = Field(description="Brief description of what changed")
    intent: str = Field(description="Why this change was made (developer intent)")
    impact: str = Field(description="What systems/behaviors are affected")
    impact_level: ImpactLevel = Field(
        default=ImpactLevel.LOW, description="Impact severity"
    )
    files_changed: list[FileChange] = Field(
        default_factory=list, description="Files that changed"
    )
    breaking_changes: list[str] = Field(
        default_factory=list, description="Any breaking changes"
    )
    dependencies_changed: list[str] = Field(
        default_factory=list, description="New/modified dependencies"
    )
    feature_description: str | None = Field(
        default=None,
        description="Feature description used for semantic filtering. "
        "None means no filtering was applied.",
    )
    is_filtered: bool = Field(
        default=False,
        description="Whether semantic filtering was applied to this change summary. "
        "When True, files_changed only contains files relevant to the feature.",
    )


class CodeElementType(str, Enum):
    """Type of code element extracted from AST."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    DECORATOR = "decorator"


class CodeElement(BaseModel):
    """A code element extracted from AST."""

    name: str = Field(
        description="Name of the element (function name, class name, etc.)"
    )
    element_type: CodeElementType = Field(description="Type of code element")
    signature: str | None = Field(None, description="Function/method signature")
    docstring: str | None = Field(None, description="Docstring if available")
    start_line: int = Field(description="Start line in source file")
    end_line: int = Field(description="End line in source file")
    file_path: str = Field(description="Path to source file")
    parent: str | None = Field(None, description="Parent class/module if applicable")
    children: list[str] = Field(
        default_factory=list, description="Child elements (methods in class)"
    )
    decorators: list[str] = Field(
        default_factory=list, description="Decorators applied"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Elements this depends on"
    )
    source_code: str | None = Field(
        None,
        description="Actual source code of this element (lines start_line to end_line)",
    )


class CodeChangeDetail(BaseModel):
    """Detailed change information with AST context."""

    element: CodeElement = Field(description="The code element")
    change_category: str = Field(description="added, modified, deleted, unchanged")
    before_state: CodeElement | None = Field(
        None, description="State before change (if modified)"
    )
    behavioral_change: bool = Field(
        default=False, description="Whether behavior changed (not just structure)"
    )
    description: str = Field(description="Description of what changed in this element")


class TechnicalFact(BaseModel):
    """A technical fact extracted from code analysis."""

    fact_id: str = Field(description="Unique identifier for this fact")
    category: str = Field(
        description="Category: api, behavior, architecture, data_flow, dependency"
    )
    source_elements: list[str] = Field(description="Code elements this fact relates to")
    description: str = Field(description="Factual description")
    source_file: str = Field(description="Primary source file")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence level 0-1"
    )
    verified: bool = Field(
        default=False, description="Whether fact was validated against AST"
    )
    code_snippets: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of element names to their actual source code. "
        "Used to ground LLM output in real code and prevent hallucination.",
    )
    before_after_code: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Mapping of element names to before/after code comparisons. "
        "Each value has 'before', 'after', and 'diff' keys with source code "
        "from base and head commits. Used to show actual code changes.",
    )
    usages: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description="Mapping of element names to usage examples. "
        "Each value has 'before_usages' and 'after_usages' keys with code snippets "
        "showing how the element was called before and after the change. "
        "Examples are extracted from real call sites in the codebase.",
    )
    created_at: datetime = Field(default_factory=datetime.now)


class DiagramSpec(BaseModel):
    """Specification for a diagram to generate."""

    diagram_type: str = Field(description="Type: architecture, flow, sequence, class")
    title: str = Field(description="Diagram title")
    description: str = Field(description="What the diagram should show")
    elements_to_include: list[str] = Field(description="Code elements to include")
    format: str = Field(default="plantuml", description="Diagram format")


class SectionPlan(BaseModel):
    """Plan for a document section."""

    title: str = Field(description="Section title")
    description: str = Field(description="What this section covers")
    technical_facts: list[str] = Field(description="Fact IDs to include")
    code_references: list[str] = Field(description="Code elements to reference")
    diagrams: list[str] = Field(
        default_factory=list, description="Diagram IDs to embed"
    )
    source_code: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of element names to their actual source code. "
        "Used to ground LLM output in real code and prevent hallucination.",
    )
    before_after_code: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Mapping of element names to before/after code comparisons. "
        "Each value has 'before', 'after', and 'diff' keys. "
        "Used to show actual code changes in documentation.",
    )
    usages: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description="Mapping of element names to usage examples. "
        "Each value has 'before_usages' and 'after_usages' keys with code snippets "
        "showing how the element was called before and after the change.",
    )


class DocumentPlan(BaseModel):
    """Plan for generating a document."""

    analysis_id: str = Field(description="Analysis this plan belongs to")
    format: str = Field(description="Output format: markdown, docx, pptx, pdf")
    title: str = Field(description="Document title")
    audience: str = Field(description="Target audience")
    sections: list[SectionPlan] = Field(description="Document sections")
    diagrams: list[DiagramSpec] = Field(description="Diagrams to generate")
    template: str | None = Field(None, description="Template to use if any")
    created_at: datetime = Field(default_factory=datetime.now)
    user_context: dict[str, Any] | None = Field(
        None, description="User-provided context for output generation"
    )


class AnalysisResult(BaseModel):
    """Complete result of an analysis."""

    analysis_id: str = Field(description="Analysis identifier")
    name: str = Field(description="User-provided name")
    change_summaries: list[ChangeSummary] = Field(description="Git change summaries")
    code_elements: list[CodeElement] = Field(description="All extracted code elements")
    change_details: list[CodeChangeDetail] = Field(
        description="Detailed change info with AST"
    )
    technical_facts: list[TechnicalFact] = Field(
        description="Synthesized technical facts"
    )
    document_plans: list[DocumentPlan] = Field(
        default_factory=list, description="Document generation plans"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
