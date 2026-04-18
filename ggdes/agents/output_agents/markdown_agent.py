"""Markdown output agent for generating markdown documentation."""

from pathlib import Path
from typing import Any

from loguru import logger

from ggdes.agents.output_agents.base import OutputAgent
from ggdes.config import GGDesConfig
from ggdes.llm import ConversationContext, LLMFactory
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    DiagramSpec,
    DocumentPlan,
    SectionPlan,
    StoragePolicy,
    TechnicalFact,
)


class MarkdownAgent(OutputAgent):
    """Generate markdown documentation from document plan."""

    def __init__(
        self,
        repo_path: Path,
        config: GGDesConfig,
        analysis_id: str,
    ):
        """Initialize markdown agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
        """
        super().__init__(repo_path, config, analysis_id)
        self.llm = LLMFactory.from_config(config)
        self.conversation: ConversationContext | None = None
        self.format_name = "markdown"

        # Load user context from plan
        self._load_user_context()

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context."""
        # Build system prompt with user context if available
        system_prompt = get_prompt("output", "markdown_system")

        if self.user_context:
            user_guidance = self._build_user_context_guidance()
            if user_guidance:
                system_prompt += (
                    f"\n\n=== USER CONTEXT ===\n{user_guidance}\n=== END CONTEXT ==="
                )

        self.conversation = ConversationContext(
            system_prompt=system_prompt,
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _build_user_context_guidance(self) -> str:
        """Build guidance text from user context."""
        from ggdes.agents.skill_utils import build_user_context_guidance

        return build_user_context_guidance(self.user_context)

    def _load_facts(self, fact_ids: list[str]) -> list[TechnicalFact]:
        """Load specific technical facts from KB."""
        import json

        from ggdes.config import get_kb_path

        facts_dir = get_kb_path(self.config, self.analysis_id) / "technical_facts"
        facts = []

        for fact_id in fact_ids:
            fact_file = facts_dir / f"{fact_id}.json"
            if fact_file.exists():
                data = json.loads(fact_file.read_text())
                facts.append(TechnicalFact(**data))

        return facts

    def _load_plan(self) -> DocumentPlan | None:
        """Load document plan from KB."""
        import json

        from ggdes.config import get_kb_path

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_markdown.json"
        )

        if not plan_file.exists():
            return None

        data = json.loads(plan_file.read_text())
        return DocumentPlan(**data)

    def _generate_plantuml(self, diagram: DiagramSpec) -> str:
        """Generate PlantUML source for a diagram."""
        # Simple PlantUML generation based on diagram type
        if diagram.diagram_type == "architecture":
            return self._generate_architecture_plantuml(diagram)
        elif diagram.diagram_type == "flow":
            return self._generate_flow_plantuml(diagram)
        elif diagram.diagram_type == "sequence":
            return self._generate_sequence_plantuml(diagram)
        elif diagram.diagram_type == "class":
            return self._generate_class_plantuml(diagram)
        else:
            return f"@startuml\ntitle {diagram.title}\n{diagram.description}\n@enduml"

    def _generate_architecture_plantuml(self, diagram: DiagramSpec) -> str:
        """Generate architecture diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}

package "System" {{
"""

        for element in diagram.elements_to_include[:10]:
            uml += f'  component "{element}"\n'

        uml += f"""}}

note right
  {diagram.description}
end note

@enduml"""

        return uml

    def _generate_flow_plantuml(self, diagram: DiagramSpec) -> str:
        """Generate flow diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}
start
"""

        for element in diagram.elements_to_include[:8]:
            uml += f":{element};\n"

        uml += """stop
@enduml"""

        return uml

    def _generate_sequence_plantuml(self, diagram: DiagramSpec) -> str:
        """Generate sequence diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}
"""

        elements = diagram.elements_to_include[:6]
        if len(elements) >= 2:
            for i, elem in enumerate(elements[:-1]):
                uml += f"{elem} -> {elements[i + 1]}: interaction\n"

        uml += """@enduml"""

        return uml

    def _generate_class_plantuml(self, diagram: DiagramSpec) -> str:
        """Generate class diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}
"""

        for element in diagram.elements_to_include[:10]:
            uml += f'class "{element}"\n'

        uml += """@enduml"""

        return uml

    def generate(self, **kwargs: Any) -> Path:
        """Generate markdown document with integrated diagrams.

        Args:
            **kwargs: Additional arguments including storage_policy and auto_generate_diagrams

        Returns:
            Path to generated markdown file
        """
        import asyncio

        storage_policy = kwargs.get("storage_policy", StoragePolicy.SUMMARY)
        auto_generate_diagrams = kwargs.get("auto_generate_diagrams", True)

        from rich.console import Console

        console = Console()

        # Initialize conversation
        self._init_conversation(storage_policy)

        # Load document plan
        plan = self._load_plan()
        if not plan:
            raise ValueError(f"No markdown plan found for {self.analysis_id}")

        console.print(
            f"\n[bold blue]Generating Markdown Document:[/bold blue] {plan.title}"
        )

        # Generate document content
        sections_content = []

        for section in plan.sections:
            content = asyncio.run(self._generate_section(section))
            sections_content.append((section.title, content))

        # Generate diagrams directory
        output_dir = self.repo_path / "docs" / "diagrams"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Collect all facts for diagram generation
        all_facts = []
        for section in plan.sections:
            all_facts.extend(self._load_facts(section.technical_facts))

        # Auto-generate diagrams from facts
        auto_diagrams = []
        if auto_generate_diagrams and all_facts:
            console.print("  [dim]Generating diagrams from technical facts...[/dim]")
            auto_diagrams = self._generate_diagrams_for_facts(
                all_facts, output_dir, ["architecture", "flow", "class"]
            )

        # Generate diagrams from plan
        plan_diagrams = []
        for diagram in plan.diagrams:
            plantuml = self._generate_plantuml(diagram)
            plan_diagrams.append((diagram.title, plantuml, diagram.diagram_type))

        # Build complete markdown with integrated diagrams
        markdown = self._build_markdown(
            plan, sections_content, plan_diagrams, auto_diagrams
        )

        # Save to output directory
        output_path = self._save_markdown(markdown, plan)

        console.print(f"  [green]✓ Document saved:[/green] {output_path}")

        # Optionally render markdown to PNG images
        render_png = kwargs.get("render_png", False)
        if render_png:
            try:
                from ggdes.rendering import MarkdownToPngRenderer

                renderer = MarkdownToPngRenderer(
                    output_dir=self.repo_path / "docs" / "diagrams"
                )
                png_paths = renderer.render(output_path, sections=True)
                console.print(
                    f"  [green]✓ Rendered {len(png_paths)} diagram images[/green]"
                )
            except ImportError:
                console.print(
                    "  [yellow]⚠ Playwright not installed. Install with: pip install ggdes[render] && playwright install chromium[/yellow]"
                )
            except Exception as e:
                console.print(f"  [yellow]⚠ PNG rendering failed: {e}[/yellow]")

        # Save conversation
        from ggdes.config import get_kb_path

        kb_path = (
            get_kb_path(self.config, self.analysis_id)
            / "conversations"
            / "markdown_agent"
        )
        if self.conversation:
            self.conversation.save(kb_path)

        return output_path

    async def _generate_section(self, section: SectionPlan) -> str:
        """Generate content for a document section."""
        logger.info(
            "MarkdownAgent: generating section | title={} facts={} model={}",
            section.title,
            len(section.technical_facts),
            self.llm.model_name,
        )
        # Load relevant facts
        facts = self._load_facts(section.technical_facts)

        # Build prompt
        prompt = f"""Write the "{section.title}" section for a design document.

Section Description: {section.description}

Technical Facts to Include:
"""
        for fact in facts:
            prompt += f"- [{fact.category}] {fact.description}\n"
            # Include source code snippets from facts
            if fact.code_snippets:
                for elem_name, code in list(fact.code_snippets.items())[:3]:
                    truncated = code[:500] + "..." if len(code) > 500 else code
                    prompt += (
                        f"  Actual source ({elem_name}):\n  ```\n  {truncated}\n  ```\n"
                    )

        if section.code_references:
            prompt += f"\nCode References: {', '.join(section.code_references)}\n"

        # Include source code from section plan (passed through from coordinator)
        if section.source_code:
            prompt += (
                "\n=== ACTUAL SOURCE CODE (use ONLY this code for references) ===\n"
            )
            for elem_name, code in list(section.source_code.items())[:5]:
                truncated = code[:500] + "..." if len(code) > 500 else code
                prompt += f"\n{elem_name}:\n```\n{truncated}\n```\n"
            prompt += "\n=== END SOURCE CODE ===\n"

        # Include before/after code comparisons from section plan
        if section.before_after_code:
            prompt += (
                "\n=== CODE CHANGES (before/after comparisons) ===\n"
                "Use these to accurately describe what changed. Reference the actual code.\n"
            )
            for elem_name, ba in list(section.before_after_code.items())[:5]:
                before = ba.get("before", "")
                after = ba.get("after", "")
                diff_text = ba.get("diff", "")
                if before and after:
                    # Modified element
                    before_trunc = before[:400] + "..." if len(before) > 400 else before
                    after_trunc = after[:400] + "..." if len(after) > 400 else after
                    prompt += f"\n--- {elem_name} (MODIFIED) ---\n"
                    prompt += f"BEFORE:\n```\n{before_trunc}\n```\n"
                    prompt += f"AFTER:\n```\n{after_trunc}\n```\n"
                    if diff_text:
                        diff_trunc = (
                            diff_text[:300] + "..."
                            if len(diff_text) > 300
                            else diff_text
                        )
                        prompt += f"DIFF:\n```diff\n{diff_trunc}\n```\n"
                elif after and not before:
                    # New element
                    after_trunc = after[:400] + "..." if len(after) > 400 else after
                    prompt += f"\n--- {elem_name} (NEW) ---\n```\n{after_trunc}\n```\n"
                elif before and not after:
                    # Deleted element
                    before_trunc = before[:400] + "..." if len(before) > 400 else before
                    prompt += (
                        f"\n--- {elem_name} (DELETED) ---\n```\n{before_trunc}\n```\n"
                    )
            prompt += "\n=== END CODE CHANGES ===\n"

        # Include usage examples (before and after call sites)
        if section.usages:
            prompt += (
                "\n=== USAGE EXAMPLES (real call sites from codebase) ===\n"
                "These show how the changed APIs are actually called in the codebase.\n"
            )
            for elem_name, usage_data in list(section.usages.items())[:5]:
                before_usages = usage_data.get("before_usages", [])
                after_usages = usage_data.get("after_usages", [])
                if before_usages:
                    prompt += f"\n--- {elem_name}: BEFORE CHANGE ---\n"
                    for usage in before_usages[:3]:
                        usage_trunc = usage[:300] + "..." if len(usage) > 300 else usage
                        prompt += f"```\n{usage_trunc}\n```\n"
                if after_usages:
                    prompt += f"\n--- {elem_name}: AFTER CHANGE ---\n"
                    for usage in after_usages[:3]:
                        usage_trunc = usage[:300] + "..." if len(usage) > 300 else usage
                        prompt += f"```\n{usage_trunc}\n```\n"
            prompt += "\n=== END USAGE EXAMPLES ===\n"

        prompt += """
Requirements:
- Write in clear, technical prose
- Use markdown formatting (headers, lists, code blocks)
- Include specific details from the facts
- Explain the "why" not just the "what"
- Keep it concise but comprehensive
- Use hierarchical headers (## for section title, ### for subsections)
- Keep paragraphs to 3-5 sentences maximum
- Use fenced code blocks with language identifiers
- IMPORTANT: Only include code blocks that match the ACTUAL SOURCE CODE provided above. Do NOT fabricate or hallucinate code. If you reference code, use the exact code shown in the source sections above.
- IMPORTANT: Only reference files, functions, and classes that are explicitly provided in your context. Never invent function names or file paths.

Write the section content now:"""

        if not self.conversation:
            raise RuntimeError("Conversation not initialized")

        self.conversation.add_user_message(prompt)
        context = self.conversation.get_context_for_llm()

        response = self.llm.chat(
            messages=context,
            temperature=0.4,
            max_tokens=4096,
        )

        self.conversation.add_assistant_message(response)

        return response

    def _build_markdown(
        self,
        plan: DocumentPlan,
        sections_content: list[tuple[str, str]],
        plan_diagrams: list[tuple[str, str, str]],
        auto_diagrams: list[tuple[str, Path, str]],
    ) -> str:
        """Build complete markdown document with integrated diagrams."""
        from datetime import datetime

        md_parts = []

        # YAML front matter
        md_parts.append("---")
        md_parts.append(f'title: "{plan.title}"')
        md_parts.append(f'audience: "{plan.audience}"')
        md_parts.append(f'analysis_id: "{self.analysis_id}"')
        md_parts.append(f'generated: "{datetime.now().isoformat()}"')
        md_parts.append("---")
        md_parts.append("")

        # Title
        md_parts.append(f"# {plan.title}")
        md_parts.append("")

        # Metadata
        md_parts.append(f"**Target Audience:** {plan.audience}")
        md_parts.append(f"**Analysis ID:** {self.analysis_id}")
        md_parts.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        md_parts.append("")

        # Executive summary section (if user context available)
        if self.user_context:
            md_parts.append("## Executive Summary")
            md_parts.append("")
            if "purpose" in self.user_context:
                md_parts.append(f"**Purpose:** {self.user_context['purpose']}")
            if "focus_areas" in self.user_context:
                md_parts.append(f"**Focus Areas:** {self.user_context['focus_areas']}")
            md_parts.append("")

        # Table of Contents
        md_parts.append("## Table of Contents")
        md_parts.append("")
        for i, (title, _) in enumerate(sections_content, 1):
            anchor = title.lower().replace(" ", "-").replace(".", "").replace(",", "")
            md_parts.append(f"{i}. [{title}](#{anchor})")

        # Add diagrams to TOC if we have them
        if auto_diagrams or plan_diagrams:
            md_parts.append(f"{len(sections_content) + 1}. [Diagrams](#diagrams)")

        md_parts.append("")
        md_parts.append("---")
        md_parts.append("")

        # Add sections
        for title, content in sections_content:
            md_parts.append(f"## {title}")
            md_parts.append("")
            md_parts.append(content)
            md_parts.append("")

        # Add diagrams section
        if auto_diagrams or plan_diagrams:
            md_parts.append("## Diagrams")
            md_parts.append("")
            md_parts.append(
                "Visual representations of the system architecture, data flows, and component relationships."
            )
            md_parts.append("")

            # Add auto-generated diagrams with image links
            for title, diagram_path, diagram_type in auto_diagrams:
                relative_path = diagram_path.relative_to(self.repo_path / "docs")
                md_parts.append(f"### {title}")
                md_parts.append("")
                md_parts.append(f"![{title}]({relative_path})")
                md_parts.append("")
                md_parts.append(f"*Type: {diagram_type}*")
                md_parts.append("")

            # Add plan diagrams as PlantUML code blocks
            if plan_diagrams:
                md_parts.append("### Additional Diagrams (PlantUML)")
                md_parts.append("")
                md_parts.append("The following diagrams can be rendered with PlantUML:")
                md_parts.append("")

                for title, plantuml, diagram_type in plan_diagrams:
                    md_parts.append(f"#### {title}")
                    md_parts.append("")
                    md_parts.append(f"Type: {diagram_type}")
                    md_parts.append("")
                    md_parts.append("```plantuml")
                    md_parts.append(plantuml)
                    md_parts.append("```")
                    md_parts.append("")

        # Add footer
        md_parts.append("---")
        md_parts.append("")
        md_parts.append(
            "*Generated by GGDes - Git-based Design Documentation Generator*"
        )
        md_parts.append(f"*Analysis ID: {self.analysis_id}*")

        return "\n".join(md_parts)

    def _save_markdown(self, content: str, plan: DocumentPlan) -> Path:
        """Save markdown to output directory."""
        # Determine output path
        output_dir = self.repo_path / "docs"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Clean filename from plan title
        safe_title = "".join(
            c if c.isalnum() or c in "-_ " else "_" for c in plan.title
        )
        safe_title = safe_title.replace(" ", "-").lower()

        output_file = output_dir / f"{self.analysis_id}-{safe_title}.md"
        output_file.write_text(content)

        return output_file
