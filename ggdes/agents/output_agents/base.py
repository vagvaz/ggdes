"""Base class for output agents."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

console = Console()


class OutputAgent(ABC):
    """Abstract base class for document output agents."""

    def __init__(self, repo_path: Path, config, analysis_id: str):
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
        self._diagram_generator: Optional = None
        self._diagram_cache = None

    def _get_diagram_cache(self):
        """Get or create diagram cache instance."""
        if self._diagram_cache is None:
            from ggdes.config import get_kb_path
            from ggdes.diagrams.cache import DiagramCache

            cache_dir = get_kb_path(self.config, self.analysis_id) / "diagram_cache"
            self._diagram_cache = DiagramCache(cache_dir)
        return self._diagram_cache

    def _get_diagram_generator(self):
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
        from ggdes.diagrams import (
            generate_architecture_diagram,
            generate_class_diagram,
            generate_flow_diagram,
        )

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
            try:
                # Check cache first
                if cache:
                    cached_path = cache.get_cached_diagram(
                        self.analysis_id, "architecture", facts
                    )
                    if cached_path:
                        console.print(
                            "  [dim]↳ Using cached architecture diagram[/dim]"
                        )
                        generated.append(
                            ("System Architecture", cached_path, "architecture")
                        )
                        # Skip generation
                        raise StopIteration("Using cached diagram")

                # Extract components from facts
                components = []
                relationships = []

                for fact in architecture_facts[:5]:
                    for elem in fact.source_elements[:3]:
                        components.append(
                            {
                                "name": elem.replace(" ", "_"),
                                "type": "service",
                                "label": elem,
                            }
                        )

                for fact in api_facts[:5]:
                    for elem in fact.source_elements[:2]:
                        if elem not in [c["name"] for c in components]:
                            components.append(
                                {
                                    "name": elem.replace(" ", "_"),
                                    "type": "service",
                                    "label": elem,
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

                if components:
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
                            self.analysis_id, "architecture", facts, diagram_path
                        )

                    generated.append(
                        ("System Architecture", diagram_path, "architecture")
                    )
                    console.print("  [green]✓ Generated architecture diagram[/green]")

            except StopIteration:
                pass  # Using cached diagram
            except Exception as e:
                console.print(
                    f"  [dim]Could not generate architecture diagram: {e}[/dim]"
                )

        # Generate flow diagram for behavior/data flow facts
        if "flow" in diagram_types and (behavior_facts or data_flow_facts):
            try:
                # Check cache first
                if cache:
                    cached_path = cache.get_cached_diagram(
                        self.analysis_id, "flow", facts
                    )
                    if cached_path:
                        console.print("  [dim]↳ Using cached flow diagram[/dim]")
                        generated.append(("Process Flow", cached_path, "flow"))
                        raise StopIteration("Using cached diagram")

                steps = []
                all_facts = behavior_facts + data_flow_facts

                for i, fact in enumerate(all_facts[:8]):
                    steps.append(
                        {
                            "id": f"step_{i}",
                            "label": fact.description[:50],
                            "type": "process" if i % 3 != 2 else "decision",
                            "next": [f"step_{i + 1}"] if i < len(all_facts) - 1 else [],
                        }
                    )

                if steps:
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
                        cache.cache_diagram(
                            self.analysis_id, "flow", facts, diagram_path
                        )

                    generated.append(("Process Flow", diagram_path, "flow"))
                    console.print("  [green]✓ Generated flow diagram[/green]")

            except StopIteration:
                pass  # Using cached diagram
            except Exception as e:
                console.print(f"  [dim]Could not generate flow diagram: {e}[/dim]")

        # Generate class diagram if we have class-related elements
        if "class" in diagram_types:
            try:
                # Check cache first
                if cache:
                    cached_path = cache.get_cached_diagram(
                        self.analysis_id, "class", facts
                    )
                    if cached_path:
                        console.print("  [dim]↳ Using cached class diagram[/dim]")
                        generated.append(("Class Structure", cached_path, "class"))
                        raise StopIteration("Using cached diagram")

                # Try to find class definitions in facts
                class_facts = [f for f in facts if "class" in f.description.lower()]

                if class_facts:
                    classes = []
                    for fact in class_facts[:5]:
                        for elem in fact.source_elements[:2]:
                            classes.append(
                                {
                                    "name": elem,
                                    "attributes": [],
                                    "methods": [],
                                }
                            )

                    if classes:
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
                            cache.cache_diagram(
                                self.analysis_id, "class", facts, diagram_path
                            )

                        generated.append(("Class Structure", diagram_path, "class"))
                        console.print("  [green]✓ Generated class diagram[/green]")

            except StopIteration:
                pass  # Using cached diagram
            except Exception as e:
                console.print(f"  [dim]Could not generate class diagram: {e}[/dim]")

        return generated

    @abstractmethod
    def generate(self) -> Path:
        """Generate output document.

        Returns:
            Path to generated file
        """
        pass
