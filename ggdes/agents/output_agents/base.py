"""Base class for output agents."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from ggdes.config import GGDesConfig, get_kb_path

if TYPE_CHECKING:
    from ggdes.diagrams import LLMDiagramGenerator, PlantUMLGenerator
    from ggdes.diagrams.cache import DiagramCache
    from ggdes.schemas import TechnicalFact

console = Console()


class OutputAgent(ABC):
    """Abstract base class for document output agents."""

    def __init__(
        self,
        repo_path: Path,
        config: GGDesConfig,
        analysis_id: str,
        review_feedback: str | None = None,
    ) -> None:
        """Initialize output agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
            review_feedback: Optional feedback from review session to incorporate during regeneration.
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context: dict[str, Any] | None = None
        self.review_feedback = review_feedback
        self._diagram_generator: PlantUMLGenerator | None = None
        self._llm_diagram_generator: LLMDiagramGenerator | None = None
        self._diagram_cache: DiagramCache | None = None
        self._validated_elements: set[str] | None = None
        self._cached_facts: list[TechnicalFact] | None = None
        self._ast_classes: list[dict[str, Any]] | None = None

    @property
    def output_dir(self) -> Path:
        """Output directory for generated documents.

        Uses config-based path: ~/ggdes-output/<analysis_id>/
        alongside ggdes-kb and ggdes-worktrees.
        """
        from ggdes.config import get_output_path

        return get_output_path(self.config, self.analysis_id)

    def _get_diagram_cache(self) -> Any:
        """Get or create diagram cache instance."""
        if self._diagram_cache is None:
            from ggdes.diagrams.cache import DiagramCache

            cache_dir = get_kb_path(self.config, self.analysis_id) / "diagram_cache"
            self._diagram_cache = DiagramCache(cache_dir)
        return self._diagram_cache

    def _get_diagram_generator(self) -> Any:
        """Get or create diagram generator instance."""
        if self._diagram_generator is None:
            from ggdes.diagrams import PlantUMLGenerator

            try:
                self._diagram_generator = PlantUMLGenerator()
            except FileNotFoundError:
                console.print(
                    "  [yellow]⚠ PlantUML not available. Diagrams will be skipped.[/yellow]"
                )
                return None
        return self._diagram_generator

    def _get_llm_diagram_generator(self) -> Any:
        """Get or create LLM-driven diagram generator instance.

        Falls back to template-based generator if LLM is unavailable.

        Returns:
            LLMDiagramGenerator instance or None if PlantUML is unavailable.
        """
        if self._llm_diagram_generator is None:
            from ggdes.diagrams import LLMDiagramGenerator

            try:
                self._llm_diagram_generator = LLMDiagramGenerator(
                    config=self.config,
                    analysis_id=self.analysis_id,
                )
            except Exception as e:
                console.print(
                    f"  [yellow]⚠ LLM diagram generator unavailable, using templates: {e}[/yellow]"
                )
                # Fall back to template generator
                if self._get_diagram_generator() is None:
                    return None
        return self._llm_diagram_generator

    def _load_user_context(self) -> None:
        """Load user context from document plan or metadata."""
        try:
            from ggdes.agents.coordinator import Coordinator

            kb_path = get_kb_path(self.config, self.analysis_id)

            # Try to find the plan for this agent's format
            format_name = getattr(self, "format_name", None)
            if format_name:
                plan = Coordinator.load_plan(kb_path, format_name)
                if plan and plan.user_context:
                    self.user_context = plan.user_context
                    return

            # Fallback: try to load from metadata
            from ggdes.kb import KnowledgeBaseManager

            kb_manager = KnowledgeBaseManager(self.config)
            metadata = kb_manager.load_metadata(self.analysis_id)
            if metadata and metadata.user_context:
                self.user_context = metadata.user_context

        except Exception as e:
            console.print(f"  [dim]Could not load user context: {e}[/dim]")
            self.user_context = None

    def _load_validated_elements(self) -> set[str]:
        """Load and cache valid code element names from AST data.

        Returns:
            Set of valid element names found in the codebase AST
        """
        if self._validated_elements is not None:
            return self._validated_elements

        valid_names: set[str] = set()

        ast_head_dir = get_kb_path(self.config, self.analysis_id) / "ast_head"

        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for elem_data in data.get("elements", []):
                        name = elem_data.get("name", "")
                        if name:
                            valid_names.add(name)
                except Exception:
                    continue

        self._validated_elements = valid_names
        return valid_names

    def _load_technical_facts(self) -> list["TechnicalFact"]:
        """Load and cache technical facts from the knowledge base.

        Returns:
            List of TechnicalFact objects loaded from technical_facts/*.json
        """
        if self._cached_facts is not None:
            return self._cached_facts

        from ggdes.schemas import TechnicalFact

        facts: list[TechnicalFact] = []
        facts_dir = get_kb_path(self.config, self.analysis_id) / "technical_facts"

        if facts_dir.exists():
            for fact_file in facts_dir.glob("*.json"):
                try:
                    data = json.loads(fact_file.read_text())
                    facts.append(TechnicalFact(**data))
                except Exception:
                    continue

        self._cached_facts = facts
        return facts

    def _load_ast_classes(self) -> list[dict[str, Any]]:
        """Load class metadata from AST head data.

        Returns:
            List of dicts with keys: name, attributes, methods, bases, file_path
        """
        if self._ast_classes is not None:
            return self._ast_classes

        classes: list[dict[str, Any]] = []
        ast_head_dir = get_kb_path(self.config, self.analysis_id) / "ast_head"

        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for elem_data in data.get("elements", []):
                        if elem_data.get("element_type") == "class":
                            class_info: dict[str, Any] = {
                                "name": elem_data.get("name", ""),
                                "methods": elem_data.get("children", []),
                                "attributes": [],
                                "bases": [],
                                "file_path": elem_data.get("file_path", ""),
                                "docstring": elem_data.get("docstring"),
                                "decorators": elem_data.get("decorators", []),
                            }

                            # Extract attributes from source code if available
                            source = elem_data.get("source_code")
                            if source:
                                class_info["attributes"] = (
                                    self._extract_attributes_from_source(source)
                                )

                            # Try to extract base classes from decorators or source
                            decorators = elem_data.get("decorators", [])
                            for dec in decorators:
                                if dec.startswith("@"):
                                    class_info["bases"].append(dec[1:])

                            classes.append(class_info)
                except Exception:
                    continue

        self._ast_classes = classes
        return classes

    def _load_changed_classes(self) -> set[str]:
        """Load set of changed class names from semantic diff data.

        Returns:
            Set of class names that were added, modified, or had behavioral changes.
        """
        semantic_diff_dir = get_kb_path(self.config, self.analysis_id) / "semantic_diff"
        changed_classes: set[str] = set()

        if semantic_diff_dir.exists():
            for json_file in semantic_diff_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for change in data.get("semantic_changes", []):
                        # Skip doc-only changes
                        if change.get("is_doc_only", False):
                            continue

                        element = change.get("element", {})
                        if element.get("element_type") == "class":
                            changed_classes.add(element.get("name", ""))
                        # Also check if a method's parent class changed
                        parent = element.get("parent")
                        if parent and element.get("change_category") in (
                            "added",
                            "modified",
                            "deleted",
                        ):
                            changed_classes.add(parent)
                except Exception:
                    continue

        return changed_classes - {""}

    def _extract_attributes_from_source(self, source: str) -> list[str]:
        """Extract class-level attribute assignments from source code.

        Looks for patterns like `self.attr = ...` in __init__ and
        class-level assignments like `attr = ...`.
        """
        import re

        attributes: list[str] = []
        for line in source.splitlines():
            stripped = line.strip()
            # Skip comments, empty lines, docstrings, def/class statements
            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith('"""')
                or stripped.startswith("'''")
                or stripped.startswith("def ")
                or stripped.startswith("class ")
                or stripped.startswith("@")
                or stripped.startswith("pass")
                or stripped.startswith("return")
            ):
                continue
            # Match self.attr = ... patterns
            match = re.match(r"self\.(\w+)\s*=", stripped)
            if match:
                attr_name = match.group(1)
                if attr_name not in attributes:
                    attributes.append(attr_name)
            # Match class-level attr = ... (but not inside methods)
            elif re.match(r"(\w+)\s*=", stripped) and not stripped.startswith("self."):
                # Only top-level assignments (no indentation or minimal)
                if not line.startswith("        "):  # Not inside a method
                    attr_name = stripped.split("=")[0].strip()
                    if attr_name and attr_name not in attributes:
                        attributes.append(attr_name)

        return attributes

    def _validate_element_name(self, elem: str) -> str:
        """Validate and correct a source element name against AST data.

        If the element name exists in the AST, returns it unchanged.
        If not found, tries to find a similar name. Returns the original
        name if no similar name is found (best-effort validation).

        Args:
            elem: Source element name to validate

        Returns:
            Validated element name (original or corrected)
        """
        valid_names = self._load_validated_elements()

        if not valid_names:
            # No AST data available, return as-is
            return elem

        if elem in valid_names:
            return elem

        # Try to find a similar name (case-insensitive prefix match)
        elem_lower = elem.lower()
        for valid_name in valid_names:
            if valid_name.lower() == elem_lower:
                return valid_name

        # Try prefix match
        for valid_name in valid_names:
            if valid_name.lower().startswith(elem_lower[:3]):
                return valid_name

        # No match found — return original but log warning
        console.print(
            f"  [yellow]⚠ Element '{elem}' not found in AST, using as-is[/yellow]"
        )
        return elem

    def _build_review_feedback_block(self) -> str:
        """Build a formatted block with review feedback for injection into prompts."""
        return (
            "╔══════════════════════════════════════════════════════════════════╗\n"
            "║              ⚠️  REVIEW FEEDBACK (MUST INCORPORATE)  ⚠️          ║\n"
            "╚══════════════════════════════════════════════════════════════════╝\n\n"
            "The following feedback was provided during review. You MUST incorporate\n"
            f"this feedback into your document generation:\n\n{self.review_feedback}"
        )

    def _load_section_feedback(self) -> dict[str, str]:
        """Load section-level feedback from KB.

        Returns:
            Dict mapping section titles to feedback text.
        """
        from ggdes.kb import KnowledgeBaseManager

        kb = KnowledgeBaseManager(self.config)
        return kb.load_section_feedback(self.analysis_id)

    def _get_section_feedback(self, section_title: str) -> str | None:
        """Get feedback for a specific document section.

        Args:
            section_title: The section title to look up.

        Returns:
            Feedback text or None if no feedback exists for this section.
        """
        feedback = self._load_section_feedback()
        return feedback.get(section_title)

    def _load_skill(self, skill_name: str) -> str:
        """Load skill documentation from skills directory.

        Args:
            skill_name: Name of the skill (e.g., 'docx', 'pdf', 'pptx')

        Returns:
            Content of the skill's SKILL.md file
        """
        from ggdes.agents.skill_utils import load_skill

        content = load_skill(skill_name)
        if content:
            return content

        raise FileNotFoundError(f"Could not find skill '{skill_name}'")

    def _generate_diagrams_for_facts(
        self,
        facts: list["TechnicalFact"],
        output_dir: Path,
        diagram_types: list[str] | None = None,
        use_cache: bool = True,
    ) -> list[tuple[str, Path, str]]:
        """Generate diagrams from technical facts with caching support.

        Uses LLM-driven generation as primary approach, falling back to
        template-based generation when LLM is unavailable.

        Args:
            facts: List of TechnicalFact objects
            output_dir: Directory to save diagrams
            diagram_types: Types of diagrams to generate (architecture, flow, class, sequence)
            use_cache: Whether to use diagram caching

        Returns:
            List of (diagram_title, diagram_path, diagram_type) tuples
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = []

        # Try LLM-driven generation first
        llm_generator = self._get_llm_diagram_generator()
        if llm_generator is not None:
            console.print("  [dim]Using LLM-driven diagram generation[/dim]")
            diagram_types = diagram_types or ["architecture", "flow", "class"]

            if "architecture" in diagram_types:
                result = llm_generator.generate_architecture_diagram(
                    facts, output_dir, use_cache=use_cache
                )
                if result:
                    generated.append(result)

            if "flow" in diagram_types:
                result = llm_generator.generate_flow_diagram(
                    facts, output_dir, use_cache=use_cache
                )
                if result:
                    generated.append(result)

            if "class" in diagram_types:
                result = llm_generator.generate_class_diagram(
                    facts, output_dir, use_cache=use_cache
                )
                if result:
                    generated.append(result)

            if generated:
                return generated

        # Fall back to template-based generation
        console.print("  [dim]Falling back to template-based diagram generation[/dim]")
        generator = self._get_diagram_generator()
        if not generator:
            return []

        # Get cache if enabled
        cache = self._get_diagram_cache() if use_cache else None

        # Group facts by category
        api_facts = [f for f in facts if f.category == "api"]
        behavior_facts = [f for f in facts if f.category == "behavior"]
        architecture_facts = [f for f in facts if f.category == "architecture"]
        data_flow_facts = [f for f in facts if f.category == "data_flow"]

        diagram_types = diagram_types or ["architecture", "flow", "class"]

        # Generate architecture diagram if we have architecture or API facts
        if "architecture" in diagram_types and (architecture_facts or api_facts):
            result = self._generate_architecture_diagram(
                architecture_facts, api_facts, facts, generator, output_dir, cache
            )
            if result:
                generated.append(result)

        # Generate flow diagram for behavior/data flow facts
        if "flow" in diagram_types and (behavior_facts or data_flow_facts):
            result = self._generate_flow_diagram(
                behavior_facts, data_flow_facts, facts, generator, output_dir, cache
            )
            if result:
                generated.append(result)

        # Generate class diagram if we have class-related elements
        if "class" in diagram_types:
            result = self._generate_class_diagram(facts, generator, output_dir, cache)
            if result:
                generated.append(result)

        return generated

    def _generate_architecture_diagram(
        self,
        architecture_facts: list["TechnicalFact"],
        api_facts: list["TechnicalFact"],
        all_facts: list["TechnicalFact"],
        generator: "PlantUMLGenerator",
        output_dir: Path,
        cache: "DiagramCache | None",
    ) -> tuple[str, Path, str] | None:
        """Generate architecture diagram from facts.

        Returns:
            Tuple of (title, path, type) or None if generation failed/skipped
        """
        from ggdes.diagrams import generate_architecture_diagram

        # Check cache first
        if cache:
            cached_path = cache.get_cached_diagram(
                self.analysis_id, "architecture", all_facts
            )
            if cached_path:
                console.print("  [dim]↳ Using cached architecture diagram[/dim]")
                return ("System Architecture", cached_path, "architecture")

        try:
            # Extract components from facts
            components = []
            relationships = []

            for fact in architecture_facts[:5]:
                for elem in fact.source_elements[:3]:
                    validated = self._validate_element_name(elem)
                    components.append(
                        {
                            "name": validated.replace(" ", "_"),
                            "type": "service",
                            "label": validated,
                        }
                    )

            for fact in api_facts[:5]:
                for elem in fact.source_elements[:2]:
                    validated = self._validate_element_name(elem)
                    if validated.replace(" ", "_") not in [
                        c["name"] for c in components
                    ]:
                        components.append(
                            {
                                "name": validated.replace(" ", "_"),
                                "type": "service",
                                "label": validated,
                            }
                        )

            # Create relationships between components
            if len(components) >= 2:
                for i in range(min(len(components) - 1, 4)):
                    relationships.append(
                        (
                            components[i]["name"],
                            components[i + 1]["name"],
                            "interacts",
                        )
                    )

            if not components:
                return None

            plantuml_code = generate_architecture_diagram(
                components=components,
                relationships=relationships,
                title="System Architecture",
            )

            diagram_path = generator.generate(
                plantuml_code,
                output_dir / f"{self.analysis_id}_architecture",
                format="png",
            )

            # Cache the diagram
            if cache:
                cache.cache_diagram(
                    self.analysis_id, "architecture", all_facts, diagram_path
                )

            console.print("  [green]✓ Generated architecture diagram[/green]")
            return ("System Architecture", diagram_path, "architecture")

        except Exception as e:
            console.print(f"  [dim]Could not generate architecture diagram: {e}[/dim]")
            return None

    def _generate_flow_diagram(
        self,
        behavior_facts: list["TechnicalFact"],
        data_flow_facts: list["TechnicalFact"],
        all_facts: list["TechnicalFact"],
        generator: "PlantUMLGenerator",
        output_dir: Path,
        cache: "DiagramCache | None",
    ) -> tuple[str, Path, str] | None:
        """Generate flow diagram from facts.

        Extracts meaningful process flows from behavior and data flow facts,
        using before/after context to show how flows have changed.
        """
        from ggdes.diagrams import generate_flow_diagram

        # Check cache first
        if cache:
            cached_path = cache.get_cached_diagram(self.analysis_id, "flow", all_facts)
            if cached_path:
                console.print("  [dim]↳ Using cached flow diagram[/dim]")
                return ("Process Flow", cached_path, "flow")

        try:
            # Combine behavior and data flow facts, prioritizing behavior
            flow_facts = behavior_facts[:5] + data_flow_facts[:3]

            if not flow_facts:
                return None

            # Build steps with meaningful labels and flow types
            steps = []
            for i, fact in enumerate(flow_facts):
                # Determine step type based on fact category
                step_type = "process"
                if fact.category == "data_flow":
                    step_type = "database"
                elif (
                    "if" in fact.description.lower()
                    or "check" in fact.description.lower()
                ):
                    step_type = "decision"
                elif (
                    "error" in fact.description.lower()
                    or "exception" in fact.description.lower()
                ):
                    step_type = "boundary"

                # Truncate label to reasonable length
                label = fact.description[:60]
                if len(fact.description) > 60:
                    label += "..."

                steps.append(
                    {
                        "id": f"step_{i}",
                        "label": label,
                        "type": step_type,
                        "next": [f"step_{i + 1}"] if i < len(flow_facts) - 1 else [],
                    }
                )

            if not steps:
                return None

            plantuml_code = generate_flow_diagram(
                steps=steps,
                title="Process Flow",
                direction="TB",
            )

            diagram_path = generator.generate(
                plantuml_code,
                output_dir / f"{self.analysis_id}_flow",
                format="png",
            )

            # Cache the diagram
            if cache:
                cache.cache_diagram(self.analysis_id, "flow", all_facts, diagram_path)

            console.print("  [green]✓ Generated flow diagram[/green]")
            return ("Process Flow", diagram_path, "flow")

        except Exception as e:
            console.print(f"  [dim]Could not generate flow diagram: {e}[/dim]")
            return None

    def _generate_class_diagram(
        self,
        facts: list["TechnicalFact"],
        generator: "PlantUMLGenerator",
        output_dir: Path,
        cache: "DiagramCache | None",
    ) -> tuple[str, Path, str] | None:
        """Generate class diagram from facts and AST metadata.

        Uses AST data as the primary source for class structure (methods, attributes),
        with facts providing context for which classes are relevant to the changes.
        Only includes changed classes and their direct dependencies to keep diagrams focused.
        """
        from ggdes.diagrams import generate_class_diagram

        # Check cache first
        if cache:
            cached_path = cache.get_cached_diagram(self.analysis_id, "class", facts)
            if cached_path:
                console.print("  [dim]↳ Using cached class diagram[/dim]")
                return ("Class Structure", cached_path, "class")

        try:
            # Load AST class metadata
            ast_classes = self._load_ast_classes()
            if not ast_classes:
                return None

            # Get changed classes from semantic diff
            changed_classes = self._load_changed_classes()

            # Build a set of relevant element names from facts
            relevant_names: set[str] = set()
            for fact in facts:
                for elem in fact.source_elements:
                    relevant_names.add(elem)
                    relevant_names.add(elem.lower())

            # Filter AST classes to those relevant to the changes
            # Priority: 1) Changed classes, 2) Fact-referenced classes, 3) Classes with changed methods
            classes_for_diagram = []
            for cls in ast_classes:
                cls_name = cls["name"]
                is_changed = cls_name in changed_classes
                is_relevant = (
                    cls_name in relevant_names or cls_name.lower() in relevant_names
                )

                # Check if any methods are referenced in facts
                has_relevant_method = False
                for method in cls.get("methods", []):
                    if method in relevant_names or method.lower() in relevant_names:
                        has_relevant_method = True
                        break

                # Include if: changed, relevant to facts, or has relevant methods
                if is_changed or is_relevant or has_relevant_method:
                    classes_for_diagram.append(cls)

            if not classes_for_diagram:
                return None

            # Build PlantUML-compatible class structures with change annotations
            plantuml_classes = []
            for cls in classes_for_diagram:
                cls_name = cls["name"]
                is_changed = cls_name in changed_classes

                # Format attributes as dicts for PlantUML generator
                attributes = []
                for attr in cls.get("attributes", [])[:10]:  # Limit to avoid clutter
                    attributes.append(
                        {
                            "name": attr,
                            "type": "",
                            "visibility": "public",
                        }
                    )

                # Format methods as dicts, limit to first 15
                methods = []
                for m in cls.get("methods", [])[:15]:
                    methods.append(
                        {
                            "name": m,
                            "signature": f"{m}()",
                            "visibility": "public",
                        }
                    )

                plantuml_classes.append(
                    {
                        "name": cls_name,
                        "attributes": attributes,
                        "methods": methods,
                        "is_changed": is_changed,
                    }
                )

            # Build relationships between classes (inheritance, composition)
            relationships = []
            class_names = {c["name"] for c in plantuml_classes}
            for cls in classes_for_diagram:
                cls_name = cls["name"]
                # Check for inheritance (base classes)
                for base in cls.get("bases", []):
                    if base in class_names:
                        relationships.append((cls_name, base, "extends"))

            plantuml_code = generate_class_diagram(
                classes=plantuml_classes,
                relationships=relationships,
                title="Class Structure",
            )

            diagram_path = generator.generate(
                plantuml_code,
                output_dir / f"{self.analysis_id}_class",
                format="png",
            )

            # Cache the diagram
            if cache:
                cache.cache_diagram(self.analysis_id, "class", facts, diagram_path)

            console.print("  [green]✓ Generated class diagram[/green]")
            return ("Class Structure", diagram_path, "class")

        except Exception as e:
            console.print(f"  [dim]Could not generate class diagram: {e}[/dim]")
            return None

    @abstractmethod
    def generate(self, **kwargs: Any) -> Path:
        """Generate output document.

        Args:
            **kwargs: Additional arguments for document generation

        Returns:
            Path to generated file
        """
        pass
