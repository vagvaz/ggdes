"""Comprehensive tests for GGDes schemas module."""

import pytest
from datetime import datetime
from typing import Any

from ggdes.schemas import (
    StoragePolicy,
    ChangeSummary,
    ChangeType,
    CodeChangeDetail,
    CodeElement,
    CodeElementType,
    DiagramSpec,
    DocumentPlan,
    FileChange,
    ImpactLevel,
    SectionPlan,
    TechnicalFact,
)
from ggdes.semantic_diff import SemanticDiffResult, SemanticChange, SemanticChangeType
from ggdes.kb.manager import StageStatus


class TestStoragePolicy:
    """Tests for StoragePolicy enum."""

    def test_storage_policy_values(self) -> None:
        """Test that StoragePolicy has the expected values."""
        assert StoragePolicy.RAW == "raw"
        assert StoragePolicy.SUMMARY == "summary"
        assert StoragePolicy.NONE == "none"

    def test_storage_policy_string_conversion(self) -> None:
        """Test string conversion of StoragePolicy values."""
        assert StoragePolicy.RAW.value == "raw"
        assert StoragePolicy.SUMMARY.value == "summary"
        assert StoragePolicy.NONE.value == "none"

    def test_storage_policy_from_string(self) -> None:
        """Test creating StoragePolicy from string values."""
        assert StoragePolicy("raw") == StoragePolicy.RAW
        assert StoragePolicy("summary") == StoragePolicy.SUMMARY
        assert StoragePolicy("none") == StoragePolicy.NONE

    def test_storage_policy_invalid_value(self) -> None:
        """Test that invalid StoragePolicy values raise ValueError."""
        with pytest.raises(ValueError):
            StoragePolicy("invalid")


class TestStageStatus:
    """Tests for StageStatus enum from kb.manager."""

    def test_stage_status_values(self) -> None:
        """Test that StageStatus has the expected values."""
        assert StageStatus.PENDING == "pending"
        assert StageStatus.IN_PROGRESS == "in_progress"
        assert StageStatus.COMPLETED == "completed"
        assert StageStatus.FAILED == "failed"
        assert StageStatus.SKIPPED == "skipped"

    def test_stage_status_string_conversion(self) -> None:
        """Test string conversion of StageStatus values."""
        assert StageStatus.PENDING.value == "pending"
        assert StageStatus.IN_PROGRESS.value == "in_progress"
        assert StageStatus.COMPLETED.value == "completed"
        assert StageStatus.FAILED.value == "failed"
        assert StageStatus.SKIPPED.value == "skipped"


class TestCodeElement:
    """Tests for CodeElement model."""

    def test_code_element_creation_required_fields(self) -> None:
        """Test creating CodeElement with required fields only."""
        element = CodeElement(
            name="test_function",
            element_type=CodeElementType.FUNCTION,
            start_line=10,
            end_line=20,
            file_path="src/test.py",
        )
        assert element.name == "test_function"
        assert element.element_type == CodeElementType.FUNCTION
        assert element.start_line == 10
        assert element.end_line == 20
        assert element.file_path == "src/test.py"

    def test_code_element_creation_all_fields(self) -> None:
        """Test creating CodeElement with all fields."""
        element = CodeElement(
            name="TestClass",
            element_type=CodeElementType.CLASS,
            signature="class TestClass(BaseModel):",
            docstring="A test class.",
            start_line=1,
            end_line=50,
            file_path="src/models.py",
            parent="models",
            children=["__init__", "method1", "method2"],
            decorators=["@dataclass"],
            dependencies=["BaseModel", "Field"],
        )
        assert element.name == "TestClass"
        assert element.element_type == CodeElementType.CLASS
        assert element.signature == "class TestClass(BaseModel):"
        assert element.docstring == "A test class."
        assert element.parent == "models"
        assert element.children == ["__init__", "method1", "method2"]
        assert element.decorators == ["@dataclass"]
        assert element.dependencies == ["BaseModel", "Field"]

    def test_code_element_optional_defaults(self) -> None:
        """Test that optional fields have correct defaults."""
        element = CodeElement(
            name="simple_var",
            element_type=CodeElementType.VARIABLE,
            start_line=5,
            end_line=5,
            file_path="src/vars.py",
        )
        assert element.signature is None
        assert element.docstring is None
        assert element.parent is None
        assert element.children == []
        assert element.decorators == []
        assert element.dependencies == []

    def test_code_element_types(self) -> None:
        """Test all CodeElementType values."""
        types = [
            CodeElementType.FUNCTION,
            CodeElementType.METHOD,
            CodeElementType.CLASS,
            CodeElementType.VARIABLE,
            CodeElementType.CONSTANT,
            CodeElementType.IMPORT,
            CodeElementType.DECORATOR,
        ]
        for element_type in types:
            element = CodeElement(
                name=f"test_{element_type.value}",
                element_type=element_type,
                start_line=1,
                end_line=1,
                file_path="test.py",
            )
            assert element.element_type == element_type


class TestTechnicalFact:
    """Tests for TechnicalFact model."""

    def test_technical_fact_creation_required_fields(self) -> None:
        """Test creating TechnicalFact with required fields."""
        fact = TechnicalFact(
            fact_id="fact_001",
            category="api",
            source_elements=["function_a", "function_b"],
            description="This is a test fact about API changes.",
            source_file="src/api.py",
        )
        assert fact.fact_id == "fact_001"
        assert fact.category == "api"
        assert fact.source_elements == ["function_a", "function_b"]
        assert fact.description == "This is a test fact about API changes."
        assert fact.source_file == "src/api.py"

    def test_technical_fact_fact_types(self) -> None:
        """Test creating facts with different categories."""
        categories = ["api", "behavior", "architecture", "data_flow", "dependency"]
        for i, category in enumerate(categories):
            fact = TechnicalFact(
                fact_id=f"fact_{i:03d}",
                category=category,
                source_elements=["element1"],
                description=f"Fact about {category}",
                source_file="src/test.py",
            )
            assert fact.category == category

    def test_technical_fact_optional_defaults(self) -> None:
        """Test that optional fields have correct defaults."""
        fact = TechnicalFact(
            fact_id="fact_002",
            category="behavior",
            source_elements=["main"],
            description="Default values test.",
            source_file="src/main.py",
        )
        assert fact.confidence == 1.0
        assert fact.verified is False
        assert isinstance(fact.created_at, datetime)

    def test_technical_fact_confidence_validation(self) -> None:
        """Test confidence field validation (0.0 to 1.0)."""
        # Valid values
        fact1 = TechnicalFact(
            fact_id="fact_003",
            category="api",
            source_elements=["x"],
            description="Test",
            source_file="test.py",
            confidence=0.5,
        )
        assert fact1.confidence == 0.5

        fact2 = TechnicalFact(
            fact_id="fact_004",
            category="api",
            source_elements=["x"],
            description="Test",
            source_file="test.py",
            confidence=0.0,
        )
        assert fact2.confidence == 0.0

        fact3 = TechnicalFact(
            fact_id="fact_005",
            category="api",
            source_elements=["x"],
            description="Test",
            source_file="test.py",
            confidence=1.0,
        )
        assert fact3.confidence == 1.0

        # Invalid values should raise validation error
        with pytest.raises(ValueError):
            TechnicalFact(
                fact_id="fact_006",
                category="api",
                source_elements=["x"],
                description="Test",
                source_file="test.py",
                confidence=1.5,  # > 1.0
            )

        with pytest.raises(ValueError):
            TechnicalFact(
                fact_id="fact_007",
                category="api",
                source_elements=["x"],
                description="Test",
                source_file="test.py",
                confidence=-0.5,  # < 0.0
            )


class TestChangeSummary:
    """Tests for ChangeSummary model."""

    def test_change_summary_creation(self) -> None:
        """Test creating ChangeSummary with all fields."""
        file_changes = [
            FileChange(
                path="src/main.py",
                change_type="modified",
                lines_added=10,
                lines_deleted=5,
                summary="Added new feature",
            ),
            FileChange(
                path="tests/test_main.py",
                change_type="added",
                lines_added=50,
                lines_deleted=0,
                summary="Added tests for new feature",
            ),
        ]

        summary = ChangeSummary(
            commit_hash="abc123",
            commit_range="abc123..def456",
            change_type=ChangeType.FEATURE,
            description="Added user authentication",
            intent="To allow users to log in securely",
            impact="User login system",
            impact_level=ImpactLevel.HIGH,
            files_changed=file_changes,
            breaking_changes=["API endpoint changed"],
            dependencies_changed=["added: bcrypt"],
        )

        assert summary.commit_hash == "abc123"
        assert summary.commit_range == "abc123..def456"
        assert summary.change_type == ChangeType.FEATURE
        assert summary.description == "Added user authentication"
        assert summary.intent == "To allow users to log in securely"
        assert summary.impact == "User login system"
        assert summary.impact_level == ImpactLevel.HIGH
        assert len(summary.files_changed) == 2
        assert summary.breaking_changes == ["API endpoint changed"]
        assert summary.dependencies_changed == ["added: bcrypt"]

    def test_change_summary_file_change_tracking(self) -> None:
        """Test file change tracking in ChangeSummary."""
        file_change = FileChange(
            path="src/utils.py",
            change_type="modified",
            lines_added=20,
            lines_deleted=10,
            summary="Refactored utility functions",
        )

        summary = ChangeSummary(
            change_type=ChangeType.REFACTOR,
            description="Code refactoring",
            intent="Improve code quality",
            impact="Internal utilities",
            files_changed=[file_change],
        )

        assert len(summary.files_changed) == 1
        assert summary.files_changed[0].path == "src/utils.py"
        assert summary.files_changed[0].lines_added == 20
        assert summary.files_changed[0].lines_deleted == 10

    def test_change_summary_defaults(self) -> None:
        """Test ChangeSummary default values."""
        summary = ChangeSummary(
            change_type=ChangeType.CHORE,
            description="Update dependencies",
            intent="Keep dependencies up to date",
            impact="Build system",
        )

        assert summary.commit_hash is None
        assert summary.commit_range is None
        assert summary.impact_level == ImpactLevel.LOW
        assert summary.files_changed == []
        assert summary.breaking_changes == []
        assert summary.dependencies_changed == []


class TestDocumentPlan:
    """Tests for DocumentPlan model."""

    def test_document_plan_creation(self) -> None:
        """Test creating DocumentPlan with all fields."""
        sections = [
            SectionPlan(
                title="Introduction",
                description="Overview of changes",
                technical_facts=["fact_001"],
                code_references=["main.py"],
                diagrams=["diagram_001"],
            ),
            SectionPlan(
                title="API Changes",
                description="Details of API modifications",
                technical_facts=["fact_002", "fact_003"],
                code_references=["api.py", "routes.py"],
                diagrams=["diagram_002"],
            ),
        ]

        diagrams = [
            DiagramSpec(
                diagram_type="architecture",
                title="System Architecture",
                description="High-level system design",
                elements_to_include=["Frontend", "API", "Database"],
                format="plantuml",
            ),
            DiagramSpec(
                diagram_type="flow",
                title="Data Flow",
                description="How data flows through the system",
                elements_to_include=["Input", "Process", "Output"],
                format="plantuml",
            ),
        ]

        plan = DocumentPlan(
            analysis_id="analysis_123",
            format="markdown",
            title="API Documentation",
            audience="Developers",
            sections=sections,
            diagrams=diagrams,
            template="default",
        )

        assert plan.analysis_id == "analysis_123"
        assert plan.format == "markdown"
        assert plan.title == "API Documentation"
        assert plan.audience == "Developers"
        assert len(plan.sections) == 2
        assert len(plan.diagrams) == 2
        assert plan.template == "default"
        assert isinstance(plan.created_at, datetime)

    def test_document_plan_sections(self) -> None:
        """Test DocumentPlan sections structure."""
        section = SectionPlan(
            title="Test Section",
            description="A test section",
            technical_facts=["fact_1"],
            code_references=["file.py"],
        )

        plan = DocumentPlan(
            analysis_id="test_001",
            format="docx",
            title="Test Document",
            audience="Testers",
            sections=[section],
            diagrams=[],
        )

        assert len(plan.sections) == 1
        assert plan.sections[0].title == "Test Section"
        assert plan.sections[0].technical_facts == ["fact_1"]
        assert plan.sections[0].code_references == ["file.py"]
        assert plan.sections[0].diagrams == []  # Default empty list

    def test_document_plan_diagrams(self) -> None:
        """Test DocumentPlan diagrams structure."""
        diagram = DiagramSpec(
            diagram_type="class",
            title="Class Diagram",
            description="Class hierarchy",
            elements_to_include=["ClassA", "ClassB"],
        )

        plan = DocumentPlan(
            analysis_id="test_002",
            format="pptx",
            title="Presentation",
            audience="Stakeholders",
            sections=[],
            diagrams=[diagram],
        )

        assert len(plan.diagrams) == 1
        assert plan.diagrams[0].diagram_type == "class"
        assert plan.diagrams[0].title == "Class Diagram"
        assert plan.diagrams[0].format == "plantuml"  # Default value


class TestSemanticDiffResult:
    """Tests for SemanticDiffResult dataclass."""

    def test_semantic_diff_result_creation(self) -> None:
        """Test creating SemanticDiffResult."""
        change1 = SemanticChange(
            change_type=SemanticChangeType.API_ADDED,
            description="Added new function",
            file_path="src/api.py",
            line_start=10,
            line_end=20,
            confidence=0.95,
            impact_score=0.5,
        )

        change2 = SemanticChange(
            change_type=SemanticChangeType.API_REMOVED,
            description="Removed old function",
            file_path="src/api.py",
            line_start=30,
            line_end=40,
            confidence=0.90,
            impact_score=1.0,
        )

        result = SemanticDiffResult(
            base_commit="abc123",
            head_commit="def456",
            semantic_changes=[change1, change2],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        assert result.base_commit == "abc123"
        assert result.head_commit == "def456"
        assert len(result.semantic_changes) == 2

    def test_semantic_diff_result_change_categorization(self) -> None:
        """Test automatic change categorization in SemanticDiffResult."""
        # Breaking change (API_REMOVED)
        breaking_change = SemanticChange(
            change_type=SemanticChangeType.API_REMOVED,
            description="Removed function",
            file_path="src/api.py",
            line_start=1,
            line_end=10,
            confidence=0.95,
            impact_score=1.0,
        )

        # Behavioral change
        behavioral_change = SemanticChange(
            change_type=SemanticChangeType.BEHAVIOR_CHANGE,
            description="Changed behavior",
            file_path="src/logic.py",
            line_start=5,
            line_end=15,
            confidence=0.80,
            impact_score=0.6,
        )

        # Refactoring change
        refactor_change = SemanticChange(
            change_type=SemanticChangeType.REFACTORING,
            description="Refactored code",
            file_path="src/utils.py",
            line_start=20,
            line_end=30,
            confidence=0.85,
            impact_score=0.3,
        )

        # Documentation change
        doc_change = SemanticChange(
            change_type=SemanticChangeType.DOCUMENTATION_ADDED,
            description="Added docs",
            file_path="src/api.py",
            line_start=1,
            line_end=5,
            confidence=0.90,
            impact_score=0.2,
        )

        result = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=[
                breaking_change,
                behavioral_change,
                refactor_change,
                doc_change,
            ],
            breaking_changes=[],  # Will be auto-populated
            behavioral_changes=[],  # Will be auto-populated
            refactoring_changes=[],  # Will be auto-populated
            documentation_changes=[],  # Will be auto-populated
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )

        # Check auto-categorization
        # Note: BEHAVIOR_CHANGE is also considered a breaking change type
        assert len(result.breaking_changes) == 2  # API_REMOVED and BEHAVIOR_CHANGE
        breaking_types = [c.change_type for c in result.breaking_changes]
        assert SemanticChangeType.API_REMOVED in breaking_types
        assert SemanticChangeType.BEHAVIOR_CHANGE in breaking_types

        assert len(result.behavioral_changes) == 1
        assert (
            result.behavioral_changes[0].change_type
            == SemanticChangeType.BEHAVIOR_CHANGE
        )

        assert len(result.refactoring_changes) == 1
        assert (
            result.refactoring_changes[0].change_type == SemanticChangeType.REFACTORING
        )

        assert len(result.documentation_changes) == 1
        assert (
            result.documentation_changes[0].change_type
            == SemanticChangeType.DOCUMENTATION_ADDED
        )

    def test_semantic_diff_result_has_breaking_changes(self) -> None:
        """Test has_breaking_changes property."""
        # Without breaking changes
        result_no_breaking = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=[],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )
        assert result_no_breaking.has_breaking_changes is False

        # With breaking changes
        breaking_change = SemanticChange(
            change_type=SemanticChangeType.API_REMOVED,
            description="Removed API",
            file_path="src/api.py",
            line_start=1,
            line_end=10,
            confidence=0.95,
            impact_score=1.0,
        )

        result_with_breaking = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=[breaking_change],
            breaking_changes=[breaking_change],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )
        assert result_with_breaking.has_breaking_changes is True

    def test_semantic_diff_result_total_impact_score(self) -> None:
        """Test total_impact_score property."""
        # Empty changes
        result_empty = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=[],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )
        assert result_empty.total_impact_score == 0.0

        # With changes
        change1 = SemanticChange(
            change_type=SemanticChangeType.API_ADDED,
            description="Added function",
            file_path="src/api.py",
            line_start=1,
            line_end=10,
            confidence=0.95,
            impact_score=0.5,
        )
        change2 = SemanticChange(
            change_type=SemanticChangeType.BEHAVIOR_CHANGE,
            description="Changed behavior",
            file_path="src/logic.py",
            line_start=5,
            line_end=15,
            confidence=0.80,
            impact_score=0.7,
        )

        result = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=[change1, change2],
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )
        assert result.total_impact_score == 1.2  # 0.5 + 0.7

        # Test cap at 10.0
        high_impact_changes = [
            SemanticChange(
                change_type=SemanticChangeType.API_REMOVED,
                description=f"High impact change {i}",
                file_path="src/api.py",
                line_start=i,
                line_end=i + 10,
                confidence=0.95,
                impact_score=1.0,
            )
            for i in range(15)  # 15 changes with impact 1.0 each = 15.0, capped at 10.0
        ]

        result_high = SemanticDiffResult(
            base_commit="base",
            head_commit="head",
            semantic_changes=high_impact_changes,
            breaking_changes=[],
            behavioral_changes=[],
            refactoring_changes=[],
            documentation_changes=[],
            test_changes=[],
            performance_changes=[],
            dependency_changes=[],
        )
        assert result_high.total_impact_score == 10.0  # Capped


class TestCodeChangeDetail:
    """Tests for CodeChangeDetail model."""

    def test_code_change_detail_creation(self) -> None:
        """Test creating CodeChangeDetail."""
        element = CodeElement(
            name="test_func",
            element_type=CodeElementType.FUNCTION,
            start_line=10,
            end_line=20,
            file_path="src/test.py",
        )

        detail = CodeChangeDetail(
            element=element,
            change_category="modified",
            description="Function was modified to add new parameter",
        )

        assert detail.element.name == "test_func"
        assert detail.change_category == "modified"
        assert detail.description == "Function was modified to add new parameter"
        assert detail.behavioral_change is False  # Default
        assert detail.before_state is None  # Default

    def test_code_change_detail_with_before_state(self) -> None:
        """Test CodeChangeDetail with before_state."""
        before_element = CodeElement(
            name="test_func",
            element_type=CodeElementType.FUNCTION,
            signature="def test_func(x):",
            start_line=10,
            end_line=15,
            file_path="src/test.py",
        )

        after_element = CodeElement(
            name="test_func",
            element_type=CodeElementType.FUNCTION,
            signature="def test_func(x, y):",
            start_line=10,
            end_line=20,
            file_path="src/test.py",
        )

        detail = CodeChangeDetail(
            element=after_element,
            change_category="modified",
            before_state=before_element,
            behavioral_change=True,
            description="Added parameter y",
        )

        assert detail.before_state is not None
        assert detail.before_state.signature == "def test_func(x):"
        assert detail.element.signature == "def test_func(x, y):"
        assert detail.behavioral_change is True


class TestEnums:
    """Additional tests for various enums."""

    def test_change_type_values(self) -> None:
        """Test ChangeType enum values."""
        assert ChangeType.FEATURE == "feature"
        assert ChangeType.BUGFIX == "bugfix"
        assert ChangeType.REFACTOR == "refactor"
        assert ChangeType.DOCS == "docs"
        assert ChangeType.TEST == "test"
        assert ChangeType.CHORE == "chore"
        assert ChangeType.PERFORMANCE == "performance"
        assert ChangeType.SECURITY == "security"

    def test_impact_level_values(self) -> None:
        """Test ImpactLevel enum values."""
        assert ImpactLevel.NONE == "none"
        assert ImpactLevel.LOW == "low"
        assert ImpactLevel.MEDIUM == "medium"
        assert ImpactLevel.HIGH == "high"
        assert ImpactLevel.CRITICAL == "critical"

    def test_semantic_change_type_values(self) -> None:
        """Test SemanticChangeType enum values."""
        # API Changes
        assert SemanticChangeType.API_ADDED == "api_added"
        assert SemanticChangeType.API_REMOVED == "api_removed"
        assert SemanticChangeType.API_MODIFIED == "api_modified"
        assert SemanticChangeType.API_DEPRECATED == "api_deprecated"

        # Behavior Changes
        assert SemanticChangeType.BEHAVIOR_CHANGE == "behavior_change"
        assert SemanticChangeType.LOGIC_CHANGE == "logic_change"
        assert SemanticChangeType.ALGORITHM_CHANGE == "algorithm_change"

        # Structure Changes
        assert SemanticChangeType.REFACTORING == "refactoring"
        assert SemanticChangeType.EXTRACTION == "extraction"
        assert SemanticChangeType.INLINE == "inline"
        assert SemanticChangeType.RENAME == "rename"


class TestModelSerialization:
    """Tests for model serialization/deserialization."""

    def test_code_element_serialization(self) -> None:
        """Test CodeElement can be serialized and deserialized."""
        element = CodeElement(
            name="test_func",
            element_type=CodeElementType.FUNCTION,
            start_line=10,
            end_line=20,
            file_path="src/test.py",
            signature="def test_func(x, y):",
        )

        # Serialize to dict
        data = element.model_dump()
        assert data["name"] == "test_func"
        assert data["element_type"] == "function"
        assert data["start_line"] == 10

        # Deserialize from dict
        restored = CodeElement(**data)
        assert restored.name == element.name
        assert restored.element_type == element.element_type

    def test_technical_fact_serialization(self) -> None:
        """Test TechnicalFact serialization."""
        fact = TechnicalFact(
            fact_id="fact_001",
            category="api",
            source_elements=["func1", "func2"],
            description="Test fact",
            source_file="src/test.py",
            confidence=0.85,
        )

        data = fact.model_dump()
        assert data["fact_id"] == "fact_001"
        assert data["confidence"] == 0.85

    def test_document_plan_serialization(self) -> None:
        """Test DocumentPlan serialization."""
        plan = DocumentPlan(
            analysis_id="analysis_001",
            format="markdown",
            title="Test Doc",
            audience="Developers",
            sections=[
                SectionPlan(
                    title="Section 1",
                    description="First section",
                    technical_facts=["fact_1"],
                    code_references=["file.py"],
                )
            ],
            diagrams=[
                DiagramSpec(
                    diagram_type="architecture",
                    title="Arch",
                    description="Architecture diagram",
                    elements_to_include=["A", "B"],
                )
            ],
        )

        data = plan.model_dump()
        assert data["analysis_id"] == "analysis_001"
        assert data["format"] == "markdown"
        assert len(data["sections"]) == 1
        assert len(data["diagrams"]) == 1
