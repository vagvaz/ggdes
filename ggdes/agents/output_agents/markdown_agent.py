"""Markdown output agent for generating markdown documentation."""

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from ggdes.agents.output_agents.base import OutputAgent
from ggdes.config import GGDesConfig, get_kb_path
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
        review_feedback: str | None = None,
    ):
        """Initialize markdown agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
            review_feedback: Optional feedback from review session to incorporate during regeneration.
        """
        super().__init__(
            repo_path, config, analysis_id, review_feedback=review_feedback
        )
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

        if self.review_feedback:
            system_prompt += (
                f"\n\n=== REVIEW FEEDBACK ===\n"
                f"{self._build_review_feedback_block()}\n"
                f"=== END REVIEW FEEDBACK ==="
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

        facts_dir = get_kb_path(self.config, self.analysis_id) / "technical_facts"
        facts = []

        for fact_id in fact_ids:
            fact_file = facts_dir / f"{fact_id}.json"
            if fact_file.exists():
                data = json.loads(fact_file.read_text())
                facts.append(TechnicalFact(**data))

        return facts

    def _load_all_facts(self) -> list[TechnicalFact]:
        """Load every technical fact from the combined facts file."""
        import json

        facts_file = (
            get_kb_path(self.config, self.analysis_id)
            / "technical_facts"
            / "facts.json"
        )
        if not facts_file.exists():
            return []
        data = json.loads(facts_file.read_text())
        return [TechnicalFact(**fact_data) for fact_data in data]

    def _load_plan(self) -> DocumentPlan | None:
        """Load document plan from KB."""
        import json

        plan_file = (
            get_kb_path(self.config, self.analysis_id) / "plans" / "plan_markdown.json"
        )

        if not plan_file.exists():
            return None

        data = json.loads(plan_file.read_text())
        return DocumentPlan(**data)

    def _ensure_plan(self) -> DocumentPlan:
        """Return a plan — loading from disk first, generating via LLM otherwise.

        Calls :meth:`_load_plan` and, if no plan file exists, calls
        :meth:`_generate_plan` to create one from the shared context.
        The generated plan is saved to disk for downstream consumers such
        as diagram generation.
        """
        plan = self._load_plan()
        if plan is not None:
            return plan
        return self._generate_plan()

    def _generate_plan(self) -> DocumentPlan:
        """Generate a document plan from technical facts via the LLM.

        Loads the shared context written by the programmatic coordinator,
        asks the LLM to propose a section structure, and saves the result
        as ``plan_markdown.json`` so that downstream machinery
        (diagram generation, etc.) can load it.
        """
        import json

        from rich.console import Console

        from ggdes.agents.coordinator import Coordinator

        plan_console = Console()
        plan_console.print("  [dim]Generating markdown document plan via LLM...[/dim]")
        logger.info(
            "MarkdownAgent: generating plan | analysis={}",
            self.analysis_id,
        )

        # Load shared context
        kb_path = get_kb_path(self.config, self.analysis_id)
        shared = Coordinator.load_shared_context(kb_path) or {}
        facts_data = shared.get("technical_facts", [])
        facts = [TechnicalFact(**fd) for fd in facts_data]
        facts_by_category: dict[str, list[TechnicalFact]] = {}
        for f in facts:
            facts_by_category.setdefault(f.category, []).append(f)

        user_context = shared.get("user_context", {}) or {}
        semantic_diff = shared.get("semantic_diff")

        # Build dynamic sections for the YAML template
        facts_lines: list[str] = []
        for cat, cat_facts in facts_by_category.items():
            facts_lines.append(f"\n{cat.upper()} ({len(cat_facts)} facts):")
            for fact in cat_facts[:5]:
                desc = fact.description[:200]
                facts_lines.append(f"  - {fact.fact_id}: {desc}")
                if fact.code_snippets:
                    for elem, code in list(fact.code_snippets.items())[:1]:
                        facts_lines.append(f"    Source ({elem}):")
                        facts_lines.append(f"    ```\n    {code[:300]}\n    ```")
                if fact.before_after_code:
                    for elem, ba in list(fact.before_after_code.items())[:1]:
                        before = (ba.get("before") or "")[:150]
                        after = (ba.get("after") or "")[:150]
                        facts_lines.append(f"    Changed ({elem}):")
                        facts_lines.append(f"      Before: {before}")
                        facts_lines.append(f"      After:  {after}")

        facts_summary = "\n".join(facts_lines)

        focus = user_context.get("focus", user_context.get("focus_areas", ""))
        focus_line = f"- Focus Areas: {focus}" if focus else ""

        purposes = user_context.get("purpose", [])
        if isinstance(purposes, list):
            purposes = ", ".join(purposes)
        purpose_line = f"- Document Purpose: {purposes}" if purposes else ""

        semantic_diff_section = ""
        if semantic_diff:
            summary = semantic_diff.get("summary", {})
            semantic_diff_section = (
                f"Semantic Diff Analysis:\n"
                f"- Total changes: {summary.get('total_changes', 0)}\n"
                f"- Breaking changes: {summary.get('breaking_changes', 0)}\n"
            )

        prompt = get_prompt("output", "markdown_plan").format(
            total_facts=len(facts),
            facts_summary=facts_summary,
            audience=user_context.get("audience", "developers"),
            detail_level=user_context.get("detail_level", "medium"),
            include_diagrams=user_context.get("include_diagrams", True),
            focus_line=focus_line,
            purpose_line=purpose_line,
            semantic_diff_section=semantic_diff_section,
        )

        # Call LLM
        from ggdes.schemas import StoragePolicy as _SP

        self._init_conversation(
            shared.get("storage_policy", _SP.SUMMARY) or _SP.SUMMARY
        )
        if not self.conversation:
            raise RuntimeError("Conversation not initialized")
        self.conversation.add_user_message(prompt)
        context = self.conversation.get_context_for_llm()

        response = self.llm.chat(
            messages=context,
            temperature=0.4,
            max_tokens=4096,
        )

        plan_data = self._extract_json(response)
        if not plan_data:
            logger.warning(
                "MarkdownAgent: LLM plan not valid JSON, using category-based fallback"
            )
            plan_data = self._build_fallback_plan(facts)

        sections = []
        for i, sec_data in enumerate(plan_data.get("sections", [])):
            section_source_code: dict[str, str] = {}
            section_before_after: dict[str, dict[str, str]] = {}
            section_usages: dict[str, dict[str, list[str]]] = {}
            for fid in sec_data.get("technical_facts", []):
                m = next((f for f in facts if f.fact_id == fid), None)
                if m:
                    if m.code_snippets:
                        section_source_code.update(m.code_snippets)
                    if m.before_after_code:
                        section_before_after.update(m.before_after_code)
                    if m.usages:
                        section_usages.update(m.usages)

            sections.append(
                SectionPlan(
                    title=sec_data.get("title", f"Section {i + 1}"),
                    description=sec_data.get("description", ""),
                    technical_facts=sec_data.get("technical_facts", []),
                    code_references=sec_data.get("code_references", []),
                    diagrams=sec_data.get("diagrams", []),
                    source_code=section_source_code,
                    before_after_code=section_before_after,
                    usages=section_usages,
                )
            )

        diagrams = []
        for diag_data in plan_data.get("diagrams", []):
            diagrams.append(
                DiagramSpec(
                    diagram_type=diag_data.get("type", "architecture"),
                    title=diag_data.get("title", f"Diagram"),
                    description=diag_data.get("description", ""),
                    elements_to_include=diag_data.get("elements", []),
                    format="plantuml",
                )
            )

        title = plan_data.get(
            "title",
            user_context.get("purpose", f"Design Document - {self.analysis_id}"),
        )
        if isinstance(title, list):
            title = ", ".join(title)

        plan = DocumentPlan(
            analysis_id=self.analysis_id,
            format="markdown",
            title=title,
            audience=user_context.get("audience", "developers"),
            sections=sections,
            diagrams=diagrams,
            template=None,
            user_context=user_context,
        )

        # Persist so downstream code (diagram gen, etc.) can load it
        plans_dir = kb_path / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "plan_markdown.json").write_text(
            json.dumps(plan.model_dump(), indent=2, default=str)
        )

        plan_console.print(
            f"  [green]✓[/green] Markdown plan: {len(sections)} sections, "
            f"{len(diagrams)} diagrams"
        )
        return plan

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract a JSON object from an LLM response using multiple strategies."""
        import json

        text = text.strip()

        # Strategy 1: raw
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: ```json fence
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass

        # Strategy 3: outermost { … }
        brace_start = text.find("{")
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    @staticmethod
    def _build_fallback_plan(facts: list[TechnicalFact]) -> dict[str, Any]:
        """Build a simple plan from facts when the LLM response is not valid JSON."""
        sections = []
        added = set()
        for cat, label in [
            ("api", "API Changes"),
            ("behavior", "Behavioral Changes"),
            ("architecture", "Architecture Changes"),
            ("data_flow", "Data Flow Changes"),
            ("dependency", "Dependency Changes"),
        ]:
            cf = [f for f in facts if f.category == cat]
            if cf:
                fids = [f.fact_id for f in cf]
                added.update(fids)
                sections.append({
                    "title": label,
                    "description": f"{len(cf)} {cat} change(s)",
                    "technical_facts": fids,
                    "code_references": list(
                        {e for f in cf for e in f.source_elements}
                    ),
                    "diagrams": [],
                })
        remaining = [f for f in facts if f.fact_id not in added]
        if remaining:
            sections.append({
                "title": "Other Changes",
                "description": f"{len(remaining)} additional change(s)",
                "technical_facts": [f.fact_id for f in remaining],
                "code_references": [],
                "diagrams": [],
            })
        if not sections:
            sections.append({
                "title": "Overview",
                "description": "Summary of changes",
                "technical_facts": [],
                "code_references": [],
                "diagrams": [],
            })
        return {"title": "Design Document", "sections": sections, "diagrams": []}

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

        # Load or generate document plan
        plan = self._ensure_plan()

        console.print(
            f"\n[bold blue]Generating Markdown Document:[/bold blue] {plan.title}"
        )

        # Generate document content — all sections in parallel
        sections_content = list(
            zip(
                [s.title for s in plan.sections],
                asyncio.run(self._generate_sections_parallel(plan.sections)),
            )
        )

        # Generate diagrams directory
        output_dir = self.output_dir / "diagrams"
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
                    output_dir=self.output_dir / "diagrams"
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

        kb_path = (
            get_kb_path(self.config, self.analysis_id)
            / "conversations"
            / "markdown_agent"
        )
        if self.conversation:
            self.conversation.save(kb_path)

        return output_path

    async def _generate_sections_parallel(
        self, sections: list[SectionPlan]
    ) -> list[str]:
        """Generate all document sections in parallel.

        Each section is an independent LLM call with its own facts and
        code references. Running them concurrently cuts document
        generation time from N×latency to 1×latency.

        Args:
            sections: List of section plans to generate

        Returns:
            List of markdown content strings, one per section (same order)
        """
        tasks = [self._generate_section(s) for s in sections]
        return await asyncio.gather(*tasks)

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

        # Inject section-specific feedback from TUI
        section_feedback = self._get_section_feedback(section.title)
        if section_feedback:
            prompt += (
                "\n╔══════════════════════════════════════════════════════════════════╗\n"
                "║         ⚠️  SECTION FEEDBACK (MUST INCORPORATE)  ⚠️              ║\n"
                "╚══════════════════════════════════════════════════════════════════╝\n\n"
                f"The following feedback was provided for this section. You MUST incorporate it:\n\n"
                f"{section_feedback}\n\n"
            )

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
                # Use just the filename since diagrams are in a sibling directory
                relative_path = f"diagrams/{diagram_path.name}"
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

            # Check for failed diagrams saved for manual debugging
            failed_diagrams = (
                sorted((self.output_dir / "diagrams").glob("failed_*.puml"))
                if (self.output_dir / "diagrams").exists()
                else []
            )
            if failed_diagrams:
                md_parts.append("### ⚠ Diagrams Needing Debugging")
                md_parts.append("")
                md_parts.append(
                    "The following diagrams could not be rendered automatically. "
                    "Their PlantUML source has been saved for manual inspection and fixing:"
                )
                md_parts.append("")
                for fd in failed_diagrams:
                    diagram_name = fd.stem.replace("failed_", "").replace(
                        f"{self.analysis_id}_", ""
                    )
                    md_parts.append(
                        f"- **{diagram_name}**: `{fd.relative_to(self.output_dir)}`"
                    )
                md_parts.append("")
                md_parts.append(
                    "Fix the PlantUML code and render with: "
                    "`java -jar plantuml.jar <file>`"
                )
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
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Clean filename from plan title
        safe_title = "".join(
            c if c.isalnum() or c in "-_ " else "_" for c in plan.title
        )
        safe_title = safe_title.replace(" ", "-").lower()

        output_file = output_dir / f"{self.analysis_id}-{safe_title}.md"
        output_file.write_text(content)

        return output_file
