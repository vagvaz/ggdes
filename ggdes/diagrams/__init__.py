"""Diagram generation module using PlantUML."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Optional


class PlantUMLGenerator:
    """Generate diagrams using PlantUML."""

    def __init__(self, plantuml_jar: Optional[Path] = None):
        """Initialize PlantUML generator.

        Args:
            plantuml_jar: Path to plantuml.jar. If not provided, searches
                         in default locations.
        """
        self.plantuml_jar = plantuml_jar or self._find_plantuml_jar()
        if not self.plantuml_jar or not self.plantuml_jar.exists():
            raise FileNotFoundError(
                "PlantUML jar not found. Please download it from: "
                "https://github.com/plantuml/plantuml/releases"
            )

    def _find_plantuml_jar(self) -> Optional[Path]:
        """Find plantuml.jar in default locations."""
        possible_paths = [
            # Current package directory
            Path(__file__).parent / "plantuml.jar",
            # Project root
            Path(__file__).parent.parent / "diagrams" / "plantuml.jar",
            # Current working directory
            Path.cwd() / "plantuml.jar",
            Path.cwd() / "ggdes" / "diagrams" / "plantuml.jar",
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def generate(
        self,
        plantuml_code: str,
        output_path: Path,
        format: Literal["png", "svg", "pdf"] = "png",
    ) -> Path:
        """Generate diagram from PlantUML code.

        Args:
            plantuml_code: PlantUML DSL code
            output_path: Output file path (without extension)
            format: Output format (png, svg, or pdf)

        Returns:
            Path to the generated diagram file
        """
        # Create temp file with plantuml code
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".puml", delete=False
        ) as temp_file:
            temp_file.write(plantuml_code)
            temp_input = Path(temp_file.name)

        try:
            # Build output path with correct extension
            output_file = output_path.with_suffix(f".{format}")
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Run PlantUML
            cmd = [
                "java",
                "-jar",
                str(self.plantuml_jar),
                "-t" + format,
                "-o",
                str(output_file.parent),
                str(temp_input),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            # PlantUML creates file with same name but different extension
            generated_file = temp_input.with_suffix(f".{format}")
            if generated_file.exists():
                generated_file.rename(output_file)

            if not output_file.exists():
                raise RuntimeError(
                    f"Diagram generation failed. Output not found: {output_file}"
                )

            return output_file

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"PlantUML execution failed:\n{e.stderr}") from e

        finally:
            # Cleanup temp file
            if temp_input.exists():
                temp_input.unlink()
            # Cleanup any generated temp files
            for ext in [".png", ".svg", ".pdf"]:
                temp_output = temp_input.with_suffix(ext)
                if temp_output.exists():
                    temp_output.unlink()

    def generate_from_file(
        self,
        input_file: Path,
        output_dir: Optional[Path] = None,
        format: Literal["png", "svg", "pdf"] = "png",
    ) -> Path:
        """Generate diagram from a PlantUML file.

        Args:
            input_file: Path to .puml file
            output_dir: Output directory (defaults to same as input)
            format: Output format

        Returns:
            Path to the generated diagram file
        """
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        output_dir = output_dir or input_file.parent
        output_path = output_dir / input_file.stem

        return self.generate(input_file.read_text(), output_path, format)

    def validate(self, plantuml_code: str) -> tuple[bool, Optional[str]]:
        """Validate PlantUML code without generating.

        Args:
            plantuml_code: PlantUML DSL code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".puml", delete=False
            ) as temp_file:
                temp_file.write(plantuml_code)
                temp_input = Path(temp_file.name)

            # Run PlantUML in check mode
            cmd = [
                "java",
                "-jar",
                str(self.plantuml_jar),
                "-checkonly",
                str(temp_input),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            return (
                result.returncode == 0,
                result.stderr if result.returncode != 0 else None,
            )

        except Exception as e:
            return False, str(e)

        finally:
            if temp_input.exists():
                temp_input.unlink()


def generate_architecture_diagram(
    components: list[dict],
    relationships: list[tuple[str, str, str]],
    title: str = "System Architecture",
    generator: Optional[PlantUMLGenerator] = None,
) -> str:
    """Generate PlantUML code for an architecture diagram.

    Args:
        components: List of dicts with 'name', 'type' (component, database, etc.)
        relationships: List of (from, to, description) tuples
        title: Diagram title
        generator: Optional PlantUML generator (for validation)

    Returns:
        PlantUML code string
    """
    lines = ["@startuml", f"title {title}", ""]

    # Add components
    type_map = {
        "database": "database",
        "service": "component",
        "api": "interface",
        "client": "actor",
        "queue": "queue",
        "cache": "component",
    }

    for comp in components:
        comp_type = type_map.get(comp.get("type", "component"), "component")
        comp_name = comp["name"].replace(" ", "_")
        comp_label = comp.get("label", comp["name"])
        lines.append(f'{comp_type} "{comp_label}" as {comp_name}')

    lines.append("")

    # Add relationships
    for from_comp, to_comp, desc in relationships:
        from_clean = from_comp.replace(" ", "_")
        to_clean = to_comp.replace(" ", "_")
        lines.append(f'{from_clean} --> {to_clean} : "{desc}"')

    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)


def generate_flow_diagram(
    steps: list[dict],
    title: str = "Process Flow",
    direction: str = "TB",
) -> str:
    """Generate PlantUML code for a flow/process diagram.

    Args:
        steps: List of dicts with 'id', 'label', 'type' (start, process, decision, end)
        title: Diagram title
        direction: Flow direction (TB, LR, BT, RL)

    Returns:
        PlantUML code string
    """
    lines = ["@startuml", f"title {title}", f"{direction}", ""]

    type_map = {
        "start": "(:",
        "end": ":)",
        "process": ":",
        "decision": "<:",
        "input": "(:",
        "output": ":)",
    }

    # Define nodes
    for step in steps:
        step_id = step["id"].replace(" ", "_")
        step_label = step.get("label", step["id"])
        step_type = type_map.get(step.get("type", "process"), ":")

        if step.get("type") == "decision":
            lines.append(f"{step_id} {step_type} {step_label} :>")
        else:
            lines.append(f"{step_id} {step_type}{step_label}{step_type}")

    lines.append("")

    # Add connections from step definitions if provided
    for step in steps:
        if "next" in step:
            step_id = step["id"].replace(" ", "_")
            next_ids = (
                step["next"] if isinstance(step["next"], list) else [step["next"]]
            )
            for next_id in next_ids:
                next_clean = next_id.replace(" ", "_")
                lines.append(f"{step_id} --> {next_clean}")

    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)


def generate_class_diagram(
    classes: list[dict],
    relationships: list[tuple[str, str, str]] = None,
    title: str = "Class Diagram",
) -> str:
    """Generate PlantUML code for a class diagram.

    Args:
        classes: List of dicts with 'name', 'attributes' (list), 'methods' (list)
        relationships: Optional list of (class_a, class_b, relation_type) tuples
        title: Diagram title

    Returns:
        PlantUML code string
    """
    lines = ["@startuml", f"title {title}", ""]

    # Define classes
    for cls in classes:
        class_name = cls["name"]
        lines.append(f"class {class_name} {{")

        # Add attributes
        for attr in cls.get("attributes", []):
            visibility = attr.get("visibility", "private")
            vis_map = {"public": "+", "private": "-", "protected": "#", "package": "~"}
            vis_symbol = vis_map.get(visibility, "-")
            attr_type = attr.get("type", "")
            attr_name = attr.get("name", "")
            lines.append(f"    {vis_symbol}{attr_name}: {attr_type}")

        if cls.get("attributes") and cls.get("methods"):
            lines.append("    ..")  # Separator

        # Add methods
        for method in cls.get("methods", []):
            visibility = method.get("visibility", "public")
            vis_map = {"public": "+", "private": "-", "protected": "#", "package": "~"}
            vis_symbol = vis_map.get(visibility, "+")
            method_sig = method.get("signature", method.get("name", "method"))
            lines.append(f"    {vis_symbol}{method_sig}")

        lines.append("}")
        lines.append("")

    # Add relationships
    if relationships:
        rel_map = {
            "extends": "--|>",
            "implements": "..|>",
            "association": "--",
            "aggregation": "--o",
            "composition": "--*",
            "dependency": "..>",
        }

        for class_a, class_b, relation in relationships or []:
            rel_symbol = rel_map.get(relation, "--")
            lines.append(f"{class_a} {rel_symbol} {class_b}")

    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)


def generate_sequence_diagram(
    participants: list[str],
    messages: list[dict],
    title: str = "Sequence Diagram",
) -> str:
    """Generate PlantUML code for a sequence diagram.

    Args:
        participants: List of participant names
        messages: List of dicts with 'from', 'to', 'message', optional 'activation'
        title: Diagram title

    Returns:
        PlantUML code string
    """
    lines = ["@startuml", f"title {title}", ""]

    # Define participants
    for participant in participants:
        lines.append(f'participant "{participant}" as {participant.replace(" ", "_")}')

    lines.append("")

    # Add messages
    for msg in messages:
        from_part = msg["from"].replace(" ", "_")
        to_part = msg["to"].replace(" ", "_")
        message = msg.get("message", "")

        if msg.get("activation"):
            lines.append(f"activate {from_part}")

        lines.append(f"{from_part} -> {to_part}: {message}")

        if msg.get("activation") == "end":
            lines.append(f"deactivate {from_part}")

    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)
