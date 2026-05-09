"""Doctor command - system diagnostics."""
# mypy: disable-error-code="has-type,untyped-decorator"

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from ggdes.cli import app, console
from ggdes.config import load_config


def _check_exec(name: str, description: str, required: bool = False) -> bool:
    """Check if an executable is available on PATH."""
    path = shutil.which(name)
    if path:
        console.print(f"  [green]✓[/green] {name}: {description} ({path})")
        return True
    else:
        icon = "[red]✗[/red]" if required else "[yellow]⚠[/yellow]"
        label = "MISSING" if required else "not found"
        console.print(f"  {icon} {name}: {description} ({label})")
        return False


def _check_npm_package(name: str) -> bool:
    """Check if an npm package is available via require()."""
    try:
        result = subprocess.run(
            ["node", "-e", f"try {{ require.resolve('{name}'); process.exit(0); }} catch(e) {{ process.exit(1); }}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            resolved = subprocess.run(
                ["node", "-e", f"console.log(require.resolve('{name}'));"],
                capture_output=True, text=True, timeout=10,
            )
            location = resolved.stdout.strip() if resolved.returncode == 0 else "?"
            console.print(f"  [green]✓[/green] npm/{name}: {location}")
            return True
        else:
            console.print(f"  [yellow]⚠[/yellow] npm/{name}: not found")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        console.print(f"  [yellow]⚠[/yellow] npm/{name}: cannot check (Node.js unavailable)")
        return False


def _check_dot_features() -> None:
    """Check if Graphviz dot supports specific rendering features."""
    try:
        subprocess.run(
            ["dot", "-?"],
            capture_output=True, text=True, timeout=10,
        )
        # Check for common Graphviz features
        features = []
        if shutil.which("neato"):
            features.append("neato (spring model)")
        if shutil.which("twopi"):
            features.append("twopi (radial)")
        if shutil.which("circo"):
            features.append("circo (circular)")
        if features:
            console.print(f"    [dim]Additional layouts: {', '.join(features)}[/dim]")
        console.print("    [dim]PlantUML uses 'dot' for: activity, component, deployment, usecase diagrams[/dim]")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


@app.command()
def doctor(
    fix: Annotated[
        bool,
        typer.Option(help="Attempt to fix issues automatically"),
    ] = False,
) -> None:
    """Diagnose system health and configuration."""
    console.print("[bold]GGDes System Diagnostics[/bold]\n")

    issues = 0
    warnings = 0
    fixes = 0

    # ════════════════════════════════════════════
    # 1. Python Environment
    # ════════════════════════════════════════════
    console.print("[bold]Python Environment[/bold]")
    console.print(
        f"  [green]✓[/green] Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    required_packages = [
        ("typer", "typer"),
        ("rich", "rich"),
        ("pydantic", "pydantic"),
        ("yaml", "pyyaml"),
        ("tree_sitter", "tree-sitter"),
        ("loguru", "loguru"),
    ]
    all_packages_found = True
    for import_name, display_name in required_packages:
        try:
            __import__(import_name)
        except ImportError:
            console.print(f"  [red]✗[/red] {display_name}: MISSING")
            all_packages_found = False
            issues += 1
    if all_packages_found:
        console.print("  [green]✓[/green] Core Python packages: all installed")
    console.print()

    # ════════════════════════════════════════════
    # 2. Diagram Generation (PlantUML)
    # ════════════════════════════════════════════
    console.print("[bold]Diagram Generation[/bold]")

    # PlantUML jar
    try:
        from ggdes.diagrams import PlantUMLGenerator

        gen = PlantUMLGenerator()
        console.print(f"  [green]✓[/green] PlantUML jar: {gen.plantuml_jar}")
    except FileNotFoundError:
        console.print("  [yellow]⚠[/yellow] PlantUML jar: not found")
        warnings += 1
        if fix:
            console.print("    [dim]Attempting download...[/dim]")
            import urllib.request
            jar_dir = Path(__file__).parent.parent.parent / "diagrams"
            jar_dir.mkdir(parents=True, exist_ok=True)
            url = "https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar"
            urllib.request.urlretrieve(url, jar_dir / "plantuml.jar")
            console.print("    [green]✓[/green] Downloaded plantuml.jar")
            fixes += 1

    # Java runtime
    java_found = _check_exec("java", "Java runtime for PlantUML", required=True)
    if not java_found:
        issues += 1

    # Graphviz (dot) — PlantUML needs this for many diagram types
    dot_found = _check_exec("dot", "Graphviz layout engine for PlantUML diagrams")
    if dot_found:
        _check_dot_features()
    else:
        console.print("    [yellow]⚠ PlantUML cannot render activity/component/deployment diagrams without Graphviz[/yellow]")
        warnings += 1
    console.print()

    # ════════════════════════════════════════════
    # 3. Document Generation (DOCX / PPTX)
    # ════════════════════════════════════════════
    console.print("[bold]Document Generation[/bold]")

    # Node.js
    node_found = _check_exec("node", "Node.js runtime for DOCX/PPTX generation")

    # NPM packages
    if node_found:
        _check_npm_package("pptxgenjs")
        _check_npm_package("docx")
    else:
        console.print("  [yellow]⚠[/yellow] npm/pptxgenjs: cannot check (Node.js unavailable)")
        console.print("  [yellow]⚠[/yellow] npm/docx: cannot check (Node.js unavailable)")

    # Pandoc fallback
    _check_exec("pandoc", "Document conversion fallback for DOCX/PPTX")
    console.print()

    # ════════════════════════════════════════════
    # 4. PDF / Image Processing
    # ════════════════════════════════════════════
    console.print("[bold]PDF & Image Processing[/bold]")

    # LibreOffice (for PDF conversion, slide rendering)
    _check_exec("soffice", "LibreOffice for PDF/PPTX→image conversion")

    # Poppler (for PDF to image)
    _check_exec("pdftoppm", "Poppler PDF→image converter")
    _check_exec("pdfimages", "Poppler PDF image extractor")

    # Tesseract (optional OCR)
    _check_exec("tesseract", "OCR for scanned PDFs (optional)")
    console.print()

    # ════════════════════════════════════════════
    # 5. Knowledge Base & Git
    # ════════════════════════════════════════════
    console.print("[bold]Knowledge Base & Git[/bold]")

    _check_exec("git", "Git version control", required=True)

    config, _ = load_config()
    kb_path = Path(config.paths.knowledge_base).expanduser()
    if kb_path.exists():
        analyses = list(kb_path.glob("*/metadata.yaml"))
        console.print(f"  [green]✓[/green] Knowledge base: {kb_path}")
        console.print(f"    [dim]Found {len(analyses)} analysis(es)[/dim]")
    else:
        console.print(f"  [yellow]⚠[/yellow] Knowledge base: {kb_path} (not found)")
        warnings += 1
        if fix:
            kb_path.mkdir(parents=True, exist_ok=True)
            console.print("    [green]✓[/green] Created knowledge base directory")
            fixes += 1
    console.print()

    # ════════════════════════════════════════════
    # Summary
    # ════════════════════════════════════════════
    if issues == 0 and warnings == 0:
        console.print("[green]✓ All checks passed![/green]")
        return

    summary_parts = []
    if issues > 0:
        summary_parts.append(f"{issues} issue(s)")
    if warnings > 0:
        summary_parts.append(f"{warnings} warning(s)")
    if fixes > 0:
        summary_parts.append(f"{fixes} fixed automatically")

    if issues > 0:
        console.print(f"[red]✗ {', '.join(summary_parts)}[/red]")
    else:
        console.print(f"[yellow]⚠ {', '.join(summary_parts)}[/yellow]")

    if issues > 0 and not fix:
        console.print("[dim]Run 'ggdes doctor --fix' to attempt automatic fixes[/dim]")
    elif issues > 0 and fix:
        console.print("[dim]Some issues couldn't be auto-fixed. See details above.[/dim]")
