"""Diagram generation module using PlantUML."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "LLMDiagramGenerator",
    "PlantUMLGenerator",
    "generate_architecture_diagram",
    "generate_class_diagram",
    "generate_flow_diagram",
    "generate_sequence_diagram",
]


class PlantUMLGenerator:
    """Generate diagrams using PlantUML."""

    def __init__(self, plantuml_jar: Path | None = None):
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

    def _find_plantuml_jar(self) -> Path | None:
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
        validate_and_repair: bool = True,
    ) -> Path:
        """Generate diagram from PlantUML code.

        Args:
            plantuml_code: PlantUML DSL code
            output_path: Output file path (without extension)
            format: Output format (png, svg, or pdf)
            validate_and_repair: Whether to validate and attempt to repair code

        Returns:
            Path to the generated diagram file
        """
        # Validate and repair if requested
        if validate_and_repair:
            repaired_code, is_valid, error = self.validate_and_repair(plantuml_code)
            if not is_valid:
                raise RuntimeError(
                    f"PlantUML code validation failed and could not be repaired: {error}"
                )
            plantuml_code = repaired_code

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

            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            # PlantUML creates file with same name but different extension
            # When -o flag is used, output goes to the specified directory
            # with the temp file's base name
            generated_file = output_file.parent / (temp_input.stem + f".{format}")
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
        output_dir: Path | None = None,
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

    def validate(self, plantuml_code: str) -> tuple[bool, str | None]:
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

    def validate_and_repair(
        self, plantuml_code: str, max_attempts: int = 3
    ) -> tuple[str, bool, str | None]:
        """Validate PlantUML code and attempt to repair if invalid.

        Args:
            plantuml_code: PlantUML DSL code to validate
            max_attempts: Maximum repair attempts

        Returns:
            Tuple of (code, is_valid, error_message)
            - code: Original or repaired code
            - is_valid: Whether code is valid (original or repaired)
            - error_message: Error message if repair failed
        """
        # First, try to validate as-is
        is_valid, error = self.validate(plantuml_code)
        if is_valid:
            return plantuml_code, True, None

        # Attempt repairs
        current_code = plantuml_code
        for _attempt in range(max_attempts):
            repaired_code = self._repair_plantuml(current_code, error)
            if repaired_code == current_code:
                # No changes made, can't repair
                break

            current_code = repaired_code
            is_valid, error = self.validate(current_code)
            if is_valid:
                return current_code, True, None

        # Repair failed
        return plantuml_code, False, error

    def _repair_plantuml(self, code: str, error_msg: str | None) -> str:
        """Attempt to repair common PlantUML errors.

        Args:
            code: PlantUML code to repair
            error_msg: Error message from validation

        Returns:
            Repaired code (or original if can't repair)
        """
        lines = code.split("\n")
        repaired_lines = []
        has_start = any("@startuml" in line for line in lines)
        has_end = any("@enduml" in line for line in lines)

        # Fix 1: Add missing @startuml/@enduml
        if not has_start:
            repaired_lines.append("@startuml")
        repaired_lines.extend(lines)
        if not has_end:
            repaired_lines.append("@enduml")

        # Fix 2: Fix invalid characters in identifiers
        fixed_lines = []
        for line in repaired_lines:
            # Fix identifiers with spaces or special chars
            if " as " in line and '"' not in line:
                # Component "Label" as name -> Component "Label" as name
                parts = line.split(" as ")
                if len(parts) == 2:
                    before = parts[0].strip()
                    after = parts[1].strip()
                    # Quote the label if it has spaces
                    if " " in before and not before.startswith('"'):
                        # Extract the type and label
                        words = before.split()
                        if len(words) >= 2:
                            comp_type = words[0]
                            label = " ".join(words[1:])
                            before = f'{comp_type} "{label}"'
                    line = f"{before} as {after}"

            # Fix 3: Fix arrow syntax errors
            if "-->" in line or "->" in line:
                # Ensure proper spacing
                line = line.replace(" ->", "->").replace("-> ", "->")
                line = line.replace(" -->", "-->").replace("--> ", "-->")

            # Fix 4: Remove empty parentheses in class definitions
            if line.strip().startswith("class ") and "()" in line:
                line = line.replace("()", "")

            fixed_lines.append(line)

        # Fix 5: Handle specific error patterns from error message
        if error_msg:
            # Fix "Some diagram description contains errors" - often missing quotes
            if "description contains errors" in error_msg:
                # Wrap unquoted labels in quotes
                for i, line in enumerate(fixed_lines):
                    if ":" in line and "-->" in line and '"' not in line:
                        # Relationship with label: A --> B : label
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            relation = parts[0].strip()
                            label = parts[1].strip()
                            if " " in label and not label.startswith('"'):
                                fixed_lines[i] = f'{relation} : "{label}"'

            # Fix invalid color/style syntax
            if "Invalid style" in error_msg or "color" in error_msg.lower():
                for i, line in enumerate(fixed_lines):
                    # Remove or fix invalid style definitions
                    if "#" in line and any(c in line for c in ["[", "]", "{", "}"]):
                        # Simplify by removing color definitions
                        line = line.split("#")[0].strip()
                        fixed_lines[i] = line

        return "\n".join(fixed_lines)


def generate_architecture_diagram(
    components: list[dict[str, Any]],
    relationships: list[tuple[str, str, str]],
    title: str = "System Architecture",
    generator: PlantUMLGenerator | None = None,
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
    steps: list[dict[str, Any]],
    title: str = "Process Flow",
    direction: str = "TB",
) -> str:
    """Generate PlantUML code for a flow/process diagram.

    Uses PlantUML activity diagram (beta) syntax. Steps are connected
    linearly in order. The 'next' field in steps is ignored since
    activity diagrams chain sequentially by default.

    Args:
        steps: List of dicts with 'id', 'label', 'type' (start, process, decision, end)
        title: Diagram title
        direction: Flow direction (TB, LR, BT, RL) — not used in activity syntax,
                   provided for backward compatibility

    Returns:
        PlantUML code string
    """
    lines = ["@startuml", f"title {title}", ""]

    for step in steps:
        step_label = step.get("label", step["id"])
        step_type = step.get("type", "process")

        if step_type == "start":
            lines.append("start")
        elif step_type == "end":
            lines.append("stop")
        elif step_type == "decision":
            # Decision nodes shown as regular activities (no branch info available)
            lines.append(f":{step_label};")
            lines.append("note right: Decision point")
        else:
            lines.append(f":{step_label};")

    lines.append("")
    lines.append("@enduml")

    return "\n".join(lines)


def generate_class_diagram(
    classes: list[dict[str, Any]],
    relationships: list[tuple[str, str, str]] | None = None,
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
    messages: list[dict[str, Any]],
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


from ggdes.diagrams.llm_generator import LLMDiagramGenerator  # noqa: E402
