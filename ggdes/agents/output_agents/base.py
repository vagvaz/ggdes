"""Base class for output agents."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from rich.console import Console

console = Console()


class OutputAgent(ABC):
    """Abstract base class for document output agents."""

    def __init__(self, repo_path: Path, config: Any, analysis_id: str) -> None:
        """Initialize output agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.user_context: Optional[Dict[str, Any]] = None
        self._diagram_generator: Optional[Any] = None
        self._diagram_cache: Optional[Any] = None
        self._validated_elements: Optional[Set[str]] = None

    def _get_diagram_cache(self) -> Any:
        """Get or create diagram cache instance."""
        if self._diagram_cache is None:
            from ggdes.config import get_kb_path
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

    def _load_user_context(self) -> None:
        """Load user context from document plan or metadata."""
        try:
            from ggdes.agents.coordinator import Coordinator
            from ggdes.config import get_kb_path

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

    def _load_validated_elements(self) -> Set[str]:
        """Load and cache valid code element names from AST data.

        Returns:
            Set of valid element names found in the codebase AST
        """
        if self._validated_elements is not None:
            return self._validated_elements

        from ggdes.config import get_kb_path
        from ggdes.kb import KnowledgeBaseManager

        valid_names: Set[str] = set()

        kb_manager = KnowledgeBaseManager(self.config)
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
        facts: List[Any],
        output_dir: Path,
        diagram_types: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> List[tuple[str, Path, str]]:
        """Generate diagrams from technical facts with caching support.

        Args:
            facts: List of TechnicalFact objects
            output_dir: Directory to save diagrams
            diagram_types: Types of diagrams to generate (architecture, flow, class, sequence)
            use_cache: Whether to use diagram caching

        Returns:
            List of (diagram_title, diagram_path, diagram_type) tuples
        """
        generator = self._get_diagram_generator()
        if not generator:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        generated = []

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
        architecture_facts: List[Any],
        api_facts: List[Any],
        all_facts: List[Any],
        generator: Any,
        output_dir: Path,
        cache: Any,
    ) -> Optional[tuple[str, Path, str]]:
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
        behavior_facts: List[Any],
        data_flow_facts: List[Any],
        all_facts: List[Any],
        generator: Any,
        output_dir: Path,
        cache: Any,
    ) -> Optional[tuple[str, Path, str]]:
        """Generate flow diagram from facts.

        Returns:
            Tuple of (title, path, type) or None if generation failed/skipped
        """
        from ggdes.diagrams import generate_flow_diagram

        # Check cache first
        if cache:
            cached_path = cache.get_cached_diagram(self.analysis_id, "flow", all_facts)
            if cached_path:
                console.print("  [dim]↳ Using cached flow diagram[/dim]")
                return ("Process Flow", cached_path, "flow")

        try:
            steps = []
            all_facts_list = behavior_facts + data_flow_facts

            for i, fact in enumerate(all_facts_list[:8]):
                steps.append(
                    {
                        "id": f"step_{i}",
                        "label": fact.description[:50],
                        "type": "process" if i % 3 != 2 else "decision",
                        "next": [f"step_{i + 1}"]
                        if i < len(all_facts_list) - 1
                        else [],
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
        facts: List[Any],
        generator: Any,
        output_dir: Path,
        cache: Any,
    ) -> Optional[tuple[str, Path, str]]:
        """Generate class diagram from facts.

        Returns:
            Tuple of (title, path, type) or None if generation failed/skipped
        """
        from ggdes.diagrams import generate_class_diagram

        # Check cache first
        if cache:
            cached_path = cache.get_cached_diagram(self.analysis_id, "class", facts)
            if cached_path:
                console.print("  [dim]↳ Using cached class diagram[/dim]")
                return ("Class Structure", cached_path, "class")

        try:
            # Try to find class definitions in facts
            class_facts = [f for f in facts if "class" in f.description.lower()]

            if not class_facts:
                return None

            classes = []
            for fact in class_facts[:5]:
                for elem in fact.source_elements[:2]:
                    validated = self._validate_element_name(elem)
                    classes.append(
                        {
                            "name": validated,
                            "attributes": [],
                            "methods": [],
                        }
                    )

            if not classes:
                return None

            plantuml_code = generate_class_diagram(
                classes=classes,
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
