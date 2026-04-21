"""LLM-driven PlantUML diagram generation.

Uses LLMs to produce semantically meaningful PlantUML diagrams from technical facts,
with validation, self-repair, and template-based fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from ggdes.config import GGDesConfig, get_kb_path
from ggdes.diagrams import PlantUMLGenerator
from ggdes.diagrams.cache import DiagramCache
from ggdes.schemas import TechnicalFact


class PlantUMLDiagram(BaseModel):
    """Structured output for an LLM-generated PlantUML diagram."""

    plantuml_code: str = Field(
        description="Complete PlantUML code including @startuml/@enduml"
    )
    title: str = Field(description="Diagram title")
    description: str = Field(description="Brief description of what the diagram shows")
    diagram_type: str = Field(
        description="Type: architecture, flow, sequence, class, state, deployment"
    )


class ArchitectureDiagramSpec(BaseModel):
    """Specification for architecture diagram generation."""

    components: list[str] = Field(description="Component/service names to include")
    relationships: list[str] = Field(
        default_factory=list, description="Known relationships between components"
    )
    changed_elements: list[str] = Field(
        default_factory=list, description="Elements that changed (highlight these)"
    )
    context: str = Field(
        description="Context about what the architecture change represents"
    )


class FlowDiagramSpec(BaseModel):
    """Specification for flow/process diagram generation."""

    steps: list[str] = Field(description="Process steps or flow stages")
    changed_elements: list[str] = Field(
        default_factory=list, description="Elements that changed (highlight these)"
    )
    context: str = Field(description="Context about what the flow change represents")


class ClassDiagramSpec(BaseModel):
    """Specification for class diagram generation."""

    classes: list[str] = Field(description="Class names to include")
    changed_classes: list[str] = Field(
        default_factory=list, description="Classes that were added/modified"
    )
    relationships: list[str] = Field(
        default_factory=list,
        description="Known relationships (extends, implements, etc.)",
    )
    context: str = Field(description="Context about what the class changes represent")


class SequenceDiagramSpec(BaseModel):
    """Specification for sequence diagram generation."""

    participants: list[str] = Field(description="Participants/actors in the sequence")
    interactions: list[str] = Field(description="Key interactions/messages")
    changed_elements: list[str] = Field(
        default_factory=list, description="Elements that changed (highlight these)"
    )
    context: str = Field(
        description="Context about what the sequence change represents"
    )


class LLMDiagramGenerator:
    """Generate PlantUML diagrams using LLMs from technical facts.

    Uses structured output to get well-formed PlantUML code, validates it,
    and attempts self-repair if validation fails. Falls back to template-based
    generation when LLM is unavailable.
    """

    def __init__(
        self,
        config: GGDesConfig,
        analysis_id: str,
        plantuml_jar: Path | None = None,
    ):
        """Initialize LLM diagram generator.

        Args:
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading facts and KB
            plantuml_jar: Optional path to plantuml.jar
        """
        self.config = config
        self.analysis_id = analysis_id
        self._plantuml_generator = PlantUMLGenerator(plantuml_jar=plantuml_jar)
        self._llm_provider: Any = None
        self._diagram_cache: DiagramCache | None = None

    @property
    def diagram_cache(self) -> DiagramCache:
        """Get or create diagram cache."""
        if self._diagram_cache is None:
            from ggdes.diagrams.cache import DiagramCache

            cache_dir = get_kb_path(self.config, self.analysis_id) / "diagram_cache"
            self._diagram_cache = DiagramCache(cache_dir)
        return self._diagram_cache

    @property
    def llm_provider(self) -> Any:
        """Get or create LLM provider."""
        if self._llm_provider is None:
            try:
                from ggdes.llm import LLMFactory

                self._llm_provider = LLMFactory.from_config(self.config)
            except Exception as e:
                logger.warning(
                    f"LLM provider not available, using template fallback: {e}"
                )
                self._llm_provider = None
        return self._llm_provider

    def generate_architecture_diagram(
        self,
        facts: list[TechnicalFact],
        output_dir: Path,
        spec: ArchitectureDiagramSpec | None = None,
        use_cache: bool = True,
    ) -> tuple[str, Path, str] | None:
        """Generate architecture diagram from technical facts.

        Args:
            facts: Technical facts to base diagram on
            output_dir: Directory to save generated diagram
            spec: Optional specific architecture spec (auto-derived from facts if None)
            use_cache: Whether to use diagram caching

        Returns:
            Tuple of (title, diagram_path, diagram_type) or None
        """
        # Check cache
        if use_cache:
            cached = self.diagram_cache.get_cached_diagram(
                self.analysis_id, "architecture", facts
            )
            if cached:
                logger.info("Using cached architecture diagram")
                return ("System Architecture", cached, "architecture")

        # Build spec from facts if not provided
        if spec is None:
            spec = self._build_architecture_spec(facts)
            if spec is None:
                return None

        # Generate PlantUML
        plantuml_code = self._generate_plantuml(
            diagram_type="architecture",
            spec=spec,
            facts=facts,
        )
        if plantuml_code is None:
            return None

        # Render to image
        diagram_path = self._render_plantuml(plantuml_code, output_dir, "architecture")
        if diagram_path is None:
            return None

        # Cache
        if use_cache:
            self.diagram_cache.cache_diagram(
                self.analysis_id, "architecture", facts, diagram_path
            )

        return ("System Architecture", diagram_path, "architecture")

    def generate_flow_diagram(
        self,
        facts: list[TechnicalFact],
        output_dir: Path,
        spec: FlowDiagramSpec | None = None,
        use_cache: bool = True,
    ) -> tuple[str, Path, str] | None:
        """Generate flow/process diagram from technical facts."""
        if use_cache:
            cached = self.diagram_cache.get_cached_diagram(
                self.analysis_id, "flow", facts
            )
            if cached:
                logger.info("Using cached flow diagram")
                return ("Process Flow", cached, "flow")

        if spec is None:
            spec = self._build_flow_spec(facts)
            if spec is None:
                return None

        plantuml_code = self._generate_plantuml(
            diagram_type="flow",
            spec=spec,
            facts=facts,
        )
        if plantuml_code is None:
            return None

        diagram_path = self._render_plantuml(plantuml_code, output_dir, "flow")
        if diagram_path is None:
            return None

        if use_cache:
            self.diagram_cache.cache_diagram(
                self.analysis_id, "flow", facts, diagram_path
            )

        return ("Process Flow", diagram_path, "flow")

    def generate_class_diagram(
        self,
        facts: list[TechnicalFact],
        output_dir: Path,
        spec: ClassDiagramSpec | None = None,
        use_cache: bool = True,
    ) -> tuple[str, Path, str] | None:
        """Generate class diagram from technical facts."""
        if use_cache:
            cached = self.diagram_cache.get_cached_diagram(
                self.analysis_id, "class", facts
            )
            if cached:
                logger.info("Using cached class diagram")
                return ("Class Structure", cached, "class")

        if spec is None:
            spec = self._build_class_spec(facts)
            if spec is None:
                return None

        plantuml_code = self._generate_plantuml(
            diagram_type="class",
            spec=spec,
            facts=facts,
        )
        if plantuml_code is None:
            return None

        diagram_path = self._render_plantuml(plantuml_code, output_dir, "class")
        if diagram_path is None:
            return None

        if use_cache:
            self.diagram_cache.cache_diagram(
                self.analysis_id, "class", facts, diagram_path
            )

        return ("Class Structure", diagram_path, "class")

    def generate_sequence_diagram(
        self,
        facts: list[TechnicalFact],
        output_dir: Path,
        spec: SequenceDiagramSpec | None = None,
        use_cache: bool = True,
    ) -> tuple[str, Path, str] | None:
        """Generate sequence diagram from technical facts."""
        if use_cache:
            cached = self.diagram_cache.get_cached_diagram(
                self.analysis_id, "sequence", facts
            )
            if cached:
                logger.info("Using cached sequence diagram")
                return ("Sequence Diagram", cached, "sequence")

        if spec is None:
            spec = self._build_sequence_spec(facts)
            if spec is None:
                return None

        plantuml_code = self._generate_plantuml(
            diagram_type="sequence",
            spec=spec,
            facts=facts,
        )
        if plantuml_code is None:
            return None

        diagram_path = self._render_plantuml(plantuml_code, output_dir, "sequence")
        if diagram_path is None:
            return None

        if use_cache:
            self.diagram_cache.cache_diagram(
                self.analysis_id, "sequence", facts, diagram_path
            )

        return ("Sequence Diagram", diagram_path, "sequence")

    # --- Internal methods ---

    def _build_architecture_spec(
        self, facts: list[TechnicalFact]
    ) -> ArchitectureDiagramSpec | None:
        """Derive architecture diagram spec from technical facts."""
        architecture_facts = [f for f in facts if f.category == "architecture"]
        api_facts = [f for f in facts if f.category == "api"]
        relevant_facts = architecture_facts[:8] + api_facts[:5]

        if not relevant_facts:
            return None

        components: list[str] = []
        relationships: list[str] = []
        changed: list[str] = []

        for fact in relevant_facts:
            for elem in fact.source_elements[:3]:
                clean = elem.replace(" ", "_")
                if clean not in components:
                    components.append(clean)
                if fact.category == "api":
                    changed.append(clean)

        # Infer relationships from fact descriptions
        for fact in relevant_facts:
            if len(fact.source_elements) >= 2:
                a = fact.source_elements[0].replace(" ", "_")
                b = fact.source_elements[1].replace(" ", "_")
                if a in components and b in components:
                    rel = f"{a} -> {b}: {fact.description[:50]}"
                    if rel not in relationships:
                        relationships.append(rel)

        context = "; ".join(f.description[:80] for f in relevant_facts[:5])

        return ArchitectureDiagramSpec(
            components=components,
            relationships=relationships,
            changed_elements=changed,
            context=context,
        )

    def _build_flow_spec(self, facts: list[TechnicalFact]) -> FlowDiagramSpec | None:
        """Derive flow diagram spec from technical facts."""
        behavior_facts = [f for f in facts if f.category == "behavior"]
        data_flow_facts = [f for f in facts if f.category == "data_flow"]
        relevant_facts = behavior_facts[:8] + data_flow_facts[:5]

        if not relevant_facts:
            return None

        steps = [f.description[:80] for f in relevant_facts]
        changed = [
            elem.replace(" ", "_")
            for f in relevant_facts
            for elem in f.source_elements[:2]
        ]
        context = "; ".join(f.description[:80] for f in relevant_facts[:5])

        return FlowDiagramSpec(
            steps=steps,
            changed_elements=list(set(changed)),
            context=context,
        )

    def _build_class_spec(self, facts: list[TechnicalFact]) -> ClassDiagramSpec | None:
        """Derive class diagram spec from technical facts."""
        # Load AST data for class names
        ast_classes = self._load_ast_class_names()
        if not ast_classes:
            return None

        # Find classes referenced in facts
        relevant_names: set[str] = set()
        for fact in facts:
            for elem in fact.source_elements:
                if elem in ast_classes:
                    relevant_names.add(elem)

        # Load changed classes
        changed_classes = self._load_changed_class_names()

        # Include changed classes + their dependencies
        classes_to_include = changed_classes | relevant_names
        if not classes_to_include:
            return None

        # Limit to reasonable number
        classes_list = list(classes_to_include)[:15]

        return ClassDiagramSpec(
            classes=classes_list,
            changed_classes=list(changed_classes & set(classes_list)),
            context=f"Classes changed in this analysis: {', '.join(changed_classes)}",
        )

    def _build_sequence_spec(
        self, facts: list[TechnicalFact]
    ) -> SequenceDiagramSpec | None:
        """Derive sequence diagram spec from technical facts."""
        # Look for facts that describe interactions between components
        interaction_facts = [
            f
            for f in facts
            if f.category in ("api", "behavior", "data_flow")
            and len(f.source_elements) >= 2
        ]

        if not interaction_facts:
            return None

        participants: set[str] = set()
        interactions: list[str] = []

        for fact in interaction_facts[:10]:
            for elem in fact.source_elements[:3]:
                participants.add(elem)
            interactions.append(
                f"{fact.source_elements[0]} -> {fact.source_elements[1]}: {fact.description[:60]}"
            )

        if len(participants) < 2:
            return None

        return SequenceDiagramSpec(
            participants=list(participants)[:10],
            interactions=interactions[:15],
            changed_elements=[
                elem.replace(" ", "_")
                for f in interaction_facts
                for elem in f.source_elements[:2]
            ],
            context="; ".join(f.description[:80] for f in interaction_facts[:5]),
        )

    def _generate_plantuml(
        self,
        diagram_type: str,
        spec: Any,
        facts: list[TechnicalFact],
    ) -> str | None:
        """Generate PlantUML code using LLM or template fallback."""
        llm = self.llm_provider
        if llm is not None:
            try:
                return self._generate_with_llm(llm, diagram_type, spec, facts)
            except Exception as e:
                logger.warning(
                    f"LLM diagram generation failed, falling back to template: {e}"
                )

        # Template fallback
        return self._generate_with_template(diagram_type, spec, facts)

    def _generate_with_llm(
        self,
        llm: Any,
        diagram_type: str,
        spec: Any,
        facts: list[TechnicalFact],
    ) -> str | None:
        """Generate PlantUML using LLM structured output."""
        system_prompt = self._build_system_prompt(diagram_type)
        user_prompt = self._build_user_prompt(diagram_type, spec, facts)

        result = llm.generate_structured(
            prompt=user_prompt,
            response_model=PlantUMLDiagram,
            system_prompt=system_prompt,
            temperature=0.3,
            max_retries=2,
        )

        # Validate the generated PlantUML
        validated_code = self._validate_and_repair_plantuml(result.plantuml_code)
        if validated_code is None:
            return None

        return validated_code

    def _build_system_prompt(self, diagram_type: str) -> str:
        """Build system prompt for PlantUML generation."""
        return f"""You are an expert PlantUML diagram generator. Your task is to produce
valid, well-structured PlantUML code that accurately represents the given technical facts.

Rules for PlantUML generation:
1. Always include @startuml and @enduml tags
2. Use proper PlantUML syntax - no markdown, no code fences
3. Use meaningful labels and identifiers (no spaces in IDs, use underscores)
4. For architecture diagrams: use components, databases, interfaces, actors
5. For flow diagrams: use activity diagram syntax with proper start/stop
6. For class diagrams: use class definitions with attributes and methods
7. For sequence diagrams: use participants and message arrows
8. Highlight changed elements with <<new>> stereotype or #Green color
9. Add a legend explaining color coding and stereotypes
10. Keep diagrams focused and readable - max 20 elements

Use the {diagram_type} diagram type. Respond with ONLY the PlantUML code, title, and description."""

    def _build_user_prompt(
        self,
        diagram_type: str,
        spec: Any,
        facts: list[TechnicalFact],
    ) -> str:
        """Build user prompt with facts and spec."""
        lines = [
            f"Generate a {diagram_type} diagram from the following technical facts:",
            "",
        ]

        # Add facts
        for i, fact in enumerate(facts[:15], 1):
            lines.append(f"Fact {i}: {fact.description}")
            if fact.source_elements:
                lines.append(f"  Elements: {', '.join(fact.source_elements[:5])}")
            lines.append("")

        # Add spec details
        if isinstance(spec, ArchitectureDiagramSpec):
            lines.append("Components to include:")
            for comp in spec.components:
                marker = " (CHANGED)" if comp in spec.changed_elements else ""
                lines.append(f"  - {comp}{marker}")
            if spec.relationships:
                lines.append("Known relationships:")
                for rel in spec.relationships:
                    lines.append(f"  - {rel}")

        elif isinstance(spec, FlowDiagramSpec):
            lines.append("Process steps:")
            for i, step in enumerate(spec.steps, 1):
                lines.append(f"  {i}. {step}")

        elif isinstance(spec, ClassDiagramSpec):
            lines.append("Classes to include:")
            for cls in spec.classes:
                marker = " (CHANGED)" if cls in spec.changed_classes else ""
                lines.append(f"  - {cls}{marker}")
            if spec.relationships:
                lines.append("Known relationships:")
                for rel in spec.relationships:
                    lines.append(f"  - {rel}")

        elif isinstance(spec, SequenceDiagramSpec):
            lines.append("Participants:")
            for p in spec.participants:
                lines.append(f"  - {p}")
            lines.append("Interactions:")
            for interaction in spec.interactions:
                lines.append(f"  - {interaction}")

        if spec.context:
            lines.append(f"\nContext: {spec.context}")

        lines.append(
            "\nGenerate valid PlantUML code for this diagram. "
            "Highlight changed elements visually. Include a legend."
        )

        return "\n".join(lines)

    def _validate_and_repair_plantuml(self, code: str) -> str | None:
        """Validate PlantUML code and attempt repair."""
        try:
            validated, is_valid, error = self._plantuml_generator.validate_and_repair(
                code
            )
            if is_valid:
                return validated
            logger.warning(f"PlantUML validation failed after repair: {error}")
            return None
        except Exception as e:
            logger.warning(f"PlantUML validation error: {e}")
            return None

    def _render_plantuml(
        self, plantuml_code: str, output_dir: Path, diagram_type: str
    ) -> Path | None:
        """Render PlantUML code to an image file."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{self.analysis_id}_{diagram_type}"
            return self._plantuml_generator.generate(
                plantuml_code,
                output_path,
                format="png",
            )
        except Exception as e:
            logger.warning(f"PlantUML rendering failed: {e}")
            return None

    def _generate_with_template(
        self,
        diagram_type: str,
        spec: Any,
        facts: list[TechnicalFact],
    ) -> str | None:
        """Fallback to template-based generation."""
        from ggdes.diagrams import (
            generate_architecture_diagram,
            generate_flow_diagram,
            generate_sequence_diagram,
        )

        try:
            if diagram_type == "architecture" and isinstance(
                spec, ArchitectureDiagramSpec
            ):
                components = [
                    {"name": c, "type": "service", "label": c.replace("_", " ")}
                    for c in spec.components
                ]
                relationships = []
                for rel in spec.relationships:
                    parts = rel.split(":", 1)
                    if len(parts) == 2:
                        src, dst = parts[0].strip().split(" -> ")
                        relationships.append((src, dst, parts[1].strip()))
                return generate_architecture_diagram(
                    components=components,
                    relationships=relationships,
                    title="System Architecture",
                )

            elif diagram_type == "flow" and isinstance(spec, FlowDiagramSpec):
                steps: list[dict[str, Any]] = [
                    {"id": f"step_{i}", "label": step, "type": "process"}
                    for i, step in enumerate(spec.steps)
                ]
                for i in range(len(steps) - 1):
                    steps[i]["next"] = [f"step_{i + 1}"]
                return generate_flow_diagram(steps=steps, title="Process Flow")

            elif diagram_type == "class" and isinstance(spec, ClassDiagramSpec):
                return self._generate_template_class_diagram(spec)

            elif diagram_type == "sequence" and isinstance(spec, SequenceDiagramSpec):
                messages = []
                for interaction in spec.interactions:
                    parts = interaction.split(":", 1)
                    if len(parts) == 2:
                        src_dst = parts[0].strip().split(" -> ")
                        if len(src_dst) == 2:
                            messages.append(
                                {
                                    "from": src_dst[0].strip(),
                                    "to": src_dst[1].strip(),
                                    "message": parts[1].strip(),
                                }
                            )
                return generate_sequence_diagram(
                    participants=spec.participants,
                    messages=messages,
                    title="Sequence Diagram",
                )

        except Exception as e:
            logger.warning(f"Template diagram generation failed: {e}")

        return None

    def _generate_template_class_diagram(
        self, spec: ClassDiagramSpec
    ) -> str | None:
        """Generate a class diagram using AST data for methods and relationships."""
        from ggdes.diagrams import generate_class_diagram

        ast_data = self._load_ast_class_data()
        if not ast_data:
            # Fallback to empty shells if no AST data
            classes = [
                {"name": c, "attributes": [], "methods": []} for c in spec.classes
            ]
            return generate_class_diagram(
                classes=classes,
                relationships=[],
                title="Class Structure",
            )

        # Build class dicts with methods from AST
        classes = self._build_class_dicts_from_ast(spec.classes, ast_data)

        # Infer relationships from AST data
        relationships = self._infer_class_relationships(ast_data, spec.classes)

        return generate_class_diagram(
            classes=classes,
            relationships=relationships,
            title="Class Structure",
        )

    def _load_ast_class_data(self) -> list[dict[str, Any]]:
        """Load full class data from AST JSON files."""
        import json

        ast_head_dir = get_kb_path(self.config, self.analysis_id) / "ast_head"
        all_elements: list[dict[str, Any]] = []

        if ast_head_dir.exists():
            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    elements = data.get("elements", [])
                    all_elements.extend(elements)
                except Exception:
                    continue

        return all_elements

    def _build_class_dicts_from_ast(
        self, class_names: list[str], ast_elements: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build class dicts with methods and attributes from AST data."""
        classes = []

        # Index methods by parent class
        methods_by_class: dict[str, list[dict[str, Any]]] = {}
        for elem in ast_elements:
            if elem.get("element_type") == "method":
                parent = elem.get("parent")
                if parent:
                    if parent not in methods_by_class:
                        methods_by_class[parent] = []
                    methods_by_class[parent].append(elem)

        for class_name in class_names:
            # Get methods for this class
            methods = []
            for method_elem in methods_by_class.get(class_name, []):
                visibility = "public"
                name = method_elem.get("name", "")
                decorators = method_elem.get("decorators", [])

                # Determine visibility from decorators and naming
                if name.startswith("_") and not name.startswith("__"):
                    visibility = "protected"
                elif name.startswith("__") and not name.endswith("__"):
                    visibility = "private"

                if "property" in decorators:
                    visibility = "public"
                if "abstractmethod" in decorators:
                    visibility = "public"

                signature = method_elem.get("signature", f"{name}()")
                # Ensure signature includes method name
                if not signature.startswith(name):
                    signature = f"{name}{signature}"

                methods.append({
                    "name": name,
                    "signature": signature,
                    "visibility": visibility,
                })

            # Extract attributes from method parameters (especially __init__)
            attributes = self._extract_attributes_from_ast(
                class_name, methods_by_class.get(class_name, [])
            )

            classes.append({
                "name": class_name,
                "attributes": attributes,
                "methods": methods,
            })

        return classes

    def _extract_attributes_from_ast(
        self, class_name: str, methods: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract class attributes from __init__ method parameters."""
        attributes: list[dict[str, Any]] = []

        # Find __init__ method
        init_method = None
        for method in methods:
            if method.get("name") == "__init__":
                init_method = method
                break

        if not init_method:
            return attributes

        # Parse __init__ signature for parameters
        signature = init_method.get("signature", "")
        # Extract parameters from signature like (self, param1, param2=default)
        import re

        match = re.search(r"\((.*)\)", signature)
        if not match:
            return attributes

        params_str = match.group(1)
        # Split by comma, handling defaults
        params = []
        for param in params_str.split(","):
            param = param.strip()
            if not param:
                continue
            # Remove default values
            param_name = param.split("=")[0].strip()
            # Skip 'self' and 'cls'
            if param_name in ("self", "cls"):
                continue
            params.append(param_name)

        # Create attributes from parameters
        for param in params:
            attributes.append({
                "name": param,
                "type": "",
                "visibility": "private",
            })

        return attributes

    def _infer_class_relationships(
        self, ast_elements: list[dict[str, Any]], class_names: list[str]
    ) -> list[tuple[str, str, str]]:
        """Infer class relationships from AST data."""
        relationships = []
        class_name_set = set(class_names)

        # Build index of classes and their source code
        class_source: dict[str, str] = {}
        class_decorators: dict[str, list[str]] = {}
        for elem in ast_elements:
            if elem.get("element_type") == "class":
                name = elem.get("name", "")
                if name:
                    class_source[name] = elem.get("source_code", "")
                    class_decorators[name] = elem.get("decorators", [])

        # Infer inheritance from source code
        import re

        for class_name in class_names:
            source = class_source.get(class_name, "")
            if not source:
                continue

            # Extract base classes from class definition
            # Match patterns like: class Foo(Base1, Base2):
            match = re.search(r"class\s+\w+\s*\(([^)]+)\)", source)
            if match:
                bases_str = match.group(1)
                bases = [b.strip() for b in bases_str.split(",")]
                for base in bases:
                    # Clean up base name (remove module prefixes)
                    base_name = base.split(".")[-1].strip()
                    if base_name in class_name_set and base_name != class_name:
                        # Check if it's an ABC or protocol (implements vs extends)
                        if base_name.endswith("Mixin") or base_name.endswith("Protocol"):
                            relationships.append(
                                (class_name, base_name, "implements")
                            )
                        else:
                            relationships.append(
                                (class_name, base_name, "extends")
                            )

        # Infer composition/dependency from method signatures
        methods_by_class: dict[str, list[dict[str, Any]]] = {}
        for elem in ast_elements:
            if elem.get("element_type") == "method":
                parent = elem.get("parent")
                if parent:
                    if parent not in methods_by_class:
                        methods_by_class[parent] = []
                    methods_by_class[parent].append(elem)

        for class_name in class_names:
            for method in methods_by_class.get(class_name, []):
                signature = method.get("signature", "")
                # Look for type hints that reference other classes
                for other_class in class_name_set:
                    if other_class == class_name:
                        continue
                    # Check if other class name appears in signature
                    if re.search(rf"\b{re.escape(other_class)}\b", signature):
                        # Avoid duplicate relationships
                        existing = (class_name, other_class, "dependency")
                        if existing not in relationships:
                            relationships.append(
                                (class_name, other_class, "dependency")
                            )

        return relationships

    def _load_ast_class_names(self) -> set[str]:
        """Load class names from AST data."""
        class_names: set[str] = set()
        ast_head_dir = get_kb_path(self.config, self.analysis_id) / "ast_head"

        if ast_head_dir.exists():
            import json

            for json_file in ast_head_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for elem_data in data.get("elements", []):
                        if elem_data.get("element_type") == "class":
                            class_names.add(elem_data.get("name", ""))
                except Exception:
                    continue

        return class_names - {""}

    def _load_changed_class_names(self) -> set[str]:
        """Load changed class names from semantic diff data."""
        changed_classes: set[str] = set()
        semantic_diff_dir = get_kb_path(self.config, self.analysis_id) / "semantic_diff"

        if semantic_diff_dir.exists():
            import json

            for json_file in semantic_diff_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    for change in data.get("semantic_changes", []):
                        if change.get("is_doc_only", False):
                            continue
                        element = change.get("element", {})
                        if element.get("element_type") == "class":
                            changed_classes.add(element.get("name", ""))
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
