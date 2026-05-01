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
        from ggdes.schemas import StoragePolicy

        self._init_conversation(
            shared.get("storage_policy", StoragePolicy.SUMMARY) or StoragePolicy.SUMMARY
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
                    title=diag_data.get("title", "Diagram"),
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
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

        # Strategy 2: ```json fence
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                try:
                    return json.loads(text[start:end].strip())  # type: ignore[no-any-return]
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
                            return json.loads(text[brace_start : i + 1])  # type: ignore[no-any-return]
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
                strict=False,
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
        code references. When the provider supports ``async_chat`` this
        provides real concurrency — N sections in ~1× latency.
        """
        tasks = [self._generate_section(s) for s in sections]
        return await asyncio.gather(*tasks)

    async def _generate_section(self, section: SectionPlan) -> str:
        """Generate content for a document section.

        Pipeline::

            load facts → build prompt chunks → check cache (hash)
            └→ if miss: estimate tokens → chunk if needed → call LLM
               → validate with CodeReferenceValidator → cache → return
        """
        import hashlib

        logger.info(
            "MarkdownAgent: generating section | title={} facts={} model={}",
            section.title,
            len(section.technical_facts),
            self.llm.model_name,
        )

        # --- 1. Load facts ---
        facts = self._load_facts(section.technical_facts)

        # --- 2. Build the fact summary block (shared between cache key & prompt) ---
        fact_lines: list[str] = []
        for fact in facts:
            fact_lines.append(f"- [{fact.category}] {fact.description}\n")
            if fact.code_snippets:
                for elem_name, code in list(fact.code_snippets.items())[:3]:
                    truncated = code[:500] + "..." if len(code) > 500 else code
                    fact_lines.append(
                        f"  Actual source ({elem_name}):\n  ```\n  {truncated}\n  ```\n"
                    )
        fact_summaries = "".join(fact_lines)

        code_references_block = (
            f"\nCode References: {', '.join(section.code_references)}\n"
            if section.code_references
            else ""
        )

        source_code_block = self._build_source_code_block(section, max_chars=2500)
        before_after_block = self._build_before_after_block(section, max_chars=2000)
        usage_examples_block = self._build_usage_examples_block(section, max_chars=1500)

        section_feedback = self._get_section_feedback(section.title)
        section_feedback_block = (
            (
                "\n╔══════════════════════════════════════════════════════════════════╗\n"
                "║         ⚠️  SECTION FEEDBACK (MUST INCORPORATE)  ⚠️              ║\n"
                "╚══════════════════════════════════════════════════════════════════╝\n\n"
                f"{section_feedback}\n\n"
            )
            if section_feedback
            else ""
        )

        # --- 3. Check content cache ---
        cache_key_raw = (
            section.title
            + "|"
            + "|".join(sorted(fact.fact_id for fact in facts))
            + "|"
            + "|".join(section.code_references or [])
        )
        cache_key = hashlib.sha256(cache_key_raw.encode()).hexdigest()[:20]
        cached = self._load_cached_section(cache_key)
        if cached:
            logger.info(
                "MarkdownAgent: using cached section | title={}", section.title
            )
            return cached

        # --- 4. Format via YAML template ---
        prompt_template = get_prompt("output", "markdown_section")
        full_prompt = prompt_template.format(
            section_title=section.title,
            section_description=section.description,
            fact_summaries=fact_summaries,
            code_references_block=code_references_block,
            source_code_block=source_code_block,
            before_after_block=before_after_block,
            usage_examples_block=usage_examples_block,
            section_feedback_block=section_feedback_block,
        )

        # --- 5. Estimate token count & chunk if necessary ---
        estimated_tokens = len(full_prompt) // 4  # rough: ~4 chars/token
        max_tok = self.config.output.max_section_tokens  # from ggdes.yaml
        if estimated_tokens > max_tok and len(facts) > 3:
            logger.warning(
                "MarkdownAgent: section prompt ~{} tokens, chunking | title={}",
                estimated_tokens,
                section.title,
            )
            return await self._generate_section_chunked(
                section, facts, max_tok
            )

        # --- 6. Call LLM with error handling ---
        response = await self._call_llm_with_remediation(
            full_prompt, section.title
        )

        # --- 7. Validate with CodeReferenceValidator ---
        response = await self._validate_section_output(response, section)

        # --- 8. Cache ---
        self._save_cached_section(cache_key, response)

        return response

    async def _call_llm_with_remediation(
        self, prompt: str, section_title: str
    ) -> str:
        """Call the LLM with retry and fallback.

        Uses the provider's ``chat()`` (or ``async_chat()`` if available).
        On failure: retries once with a correction prompt.
        On double failure: returns a minimal fact summary instead of crashing.
        """
        import time

        if not self.conversation:
            raise RuntimeError("Conversation not initialised")

        self.conversation.add_user_message(prompt)
        context = self.conversation.get_context_for_llm()

        for attempt in range(2):
            try:
                if hasattr(self.llm, "async_chat"):
                    response = await self.llm.async_chat(
                        messages=context,
                        temperature=0.4,
                        max_tokens=4096,
                    )
                else:
                    response = self.llm.chat(
                        messages=context,
                        temperature=0.4,
                        max_tokens=4096,
                    )

                self.conversation.add_assistant_message(response)

                if response.strip():
                    return response

                # Empty response — retry
                logger.warning(
                    "MarkdownAgent: empty response for '{}' (attempt {})",
                    section_title,
                    attempt + 1,
                )
                time.sleep(1)

            except Exception as exc:
                logger.warning(
                    "MarkdownAgent: LLM call failed for '{}' (attempt {}): {}",
                    section_title,
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    time.sleep(2)
                continue

        # Both attempts failed — return a minimal fallback
        logger.error(
            "MarkdownAgent: LLM failed for '{}' after 2 attempts, "
            "using fallback",
            section_title,
        )
        return (
            f"## {section_title}\n\n"
            f"_This section could not be generated due to an LLM error._\n"
        )

    async def _validate_section_output(
        self, response: str, section: SectionPlan
    ) -> str:
        """Run generated section through CodeReferenceValidator.

        Only validates when the validator module is available.  On
        validation failure a warning is emitted and the model is asked
        to correct just the problematic chunk (not the whole section).
        """
        try:
            from ggdes.validation.code_references import CodeReferenceValidator

            kb_path = get_kb_path(self.config, self.analysis_id)
            diffs_dir = kb_path / "git_analysis"
            diff_file = diffs_dir / "diff.txt"
            diff_content = diff_file.read_text() if diff_file.exists() else ""

            validator = CodeReferenceValidator(
                repo_path=self.repo_path,
                changed_files=section.code_references or [],
                code_elements={},
                diff_content=diff_content,
            )
            validated = validator.validate_and_correct(
                llm_output=response,
                llm_provider=self.llm,
                max_corrections=1,
            )
            if validated != response:
                logger.info(
                    "MarkdownAgent: validator corrected '{}' references",
                    section.title,
                )
            return validated
        except Exception as exc:
            logger.debug(
                "MarkdownAgent: validation skipped for '{}': {}",
                section.title,
                exc,
            )
            return response

    def _build_source_code_block(
        self, section: SectionPlan, max_chars: int = 2500
    ) -> str:
        """Build the ``=== ACTUAL SOURCE CODE ===`` block, respecting a
        total character budget."""
        if not section.source_code:
            return ""
        lines = [
            "\n=== ACTUAL SOURCE CODE (use ONLY this code for references) ===\n"
        ]
        budget = max_chars
        for elem_name, code in section.source_code.items():
            if budget <= 0:
                break
            snippet = code[: budget - 100]
            lines.append(f"\n{elem_name}:\n```\n{snippet}\n```\n")
            budget -= len(snippet) + 60
        lines.append("\n=== END SOURCE CODE ===\n")
        return "".join(lines)

    def _build_before_after_block(
        self, section: SectionPlan, max_chars: int = 2000
    ) -> str:
        """Build the ``=== CODE CHANGES ===`` block."""
        if not section.before_after_code:
            return ""
        lines = [
            "\n=== CODE CHANGES (before/after comparisons) ===\n"
            "Use these to accurately describe what changed. Reference the actual code.\n"
        ]
        budget = max_chars
        for elem_name, ba in section.before_after_code.items():
            if budget <= 0:
                break
            before = ba.get("before", "")
            after = ba.get("after", "")
            diff_text = ba.get("diff", "")
            if before and after:
                budget -= 500
                if budget < 0:
                    break
                lines.append(f"\n--- {elem_name} (MODIFIED) ---\n")
                lines.append(
                    f"BEFORE:\n```\n{before[:400]}\n```\n"
                    f"AFTER:\n```\n{after[:400]}\n```\n"
                )
                if diff_text:
                    lines.append(f"DIFF:\n```diff\n{diff_text[:300]}\n```\n")
            elif after and not before:
                lines.append(f"\n--- {elem_name} (NEW) ---\n```\n{after[:400]}\n```\n")
            elif before and not after:
                lines.append(
                    f"\n--- {elem_name} (DELETED) ---\n```\n{before[:400]}\n```\n"
                )
        lines.append("\n=== END CODE CHANGES ===\n")
        return "".join(lines)

    def _build_usage_examples_block(
        self, section: SectionPlan, max_chars: int = 1500
    ) -> str:
        """Build the ``=== USAGE EXAMPLES ===`` block."""
        if not section.usages:
            return ""
        lines = [
            "\n=== USAGE EXAMPLES (real call sites from codebase) ===\n"
            "These show how the changed APIs are actually called in the codebase.\n"
        ]
        budget = max_chars
        for elem_name, usage_data in section.usages.items():
            if budget <= 0:
                break
            before_usages = usage_data.get("before_usages", [])
            after_usages = usage_data.get("after_usages", [])
            if before_usages:
                budget -= 400
                if budget < 0:
                    break
                lines.append(f"\n--- {elem_name}: BEFORE CHANGE ---\n")
                for usage in before_usages[:3]:
                    lines.append(f"```\n{usage[:300]}\n```\n")
            if after_usages:
                budget -= 400
                if budget < 0:
                    break
                lines.append(f"\n--- {elem_name}: AFTER CHANGE ---\n")
                for usage in after_usages[:3]:
                    lines.append(f"```\n{usage[:300]}\n```\n")
        lines.append("\n=== END USAGE EXAMPLES ===\n")
        return "".join(lines)

    async def _generate_section_chunked(
        self,
        section: SectionPlan,
        facts: list[TechnicalFact],
        max_tokens: int,
    ) -> str:
        """Split a large section into chunks and generate each separately.

        Each chunk gets a subset of facts and a short preamble telling the
        model it's part N of M.  Results are concatenated with chunk
        separators.
        """
        chunk_size = 4  # facts per chunk
        chunks: list[str] = []
        n_chunks = (len(facts) + chunk_size - 1) // chunk_size

        for i in range(0, len(facts), chunk_size):
            chunk_num = (i // chunk_size) + 1
            sub_facts = facts[i : i + chunk_size]

            fact_lines: list[str] = []
            for fact in sub_facts:
                fact_lines.append(f"- [{fact.category}] {fact.description}\n")
                if fact.code_snippets:
                    for elem_name, code in list(fact.code_snippets.items())[:1]:
                        truncated = code[:400] + "..." if len(code) > 400 else code
                        fact_lines.append(
                            f"  Source ({elem_name}):\n  ```\n  {truncated}\n  ```\n"
                        )
            fact_summaries = "".join(fact_lines)

            prompt = get_prompt("output", "markdown_section").format(
                section_title=f"{section.title} (part {chunk_num}/{n_chunks})",
                section_description=(
                    f"{section.description} — part {chunk_num} of {n_chunks}"
                ),
                fact_summaries=fact_summaries,
                code_references_block="",
                source_code_block="",
                before_after_block="",
                usage_examples_block="",
                section_feedback_block="",
            )

            chunk_content = await self._call_llm_with_remediation(
                prompt, f"{section.title} (chunk {chunk_num})"
            )
            chunks.append(chunk_content)

        return "\n\n---\n\n".join(chunks)

    # ------------------------------------------------------------------
    # Section content cache
    # ------------------------------------------------------------------

    def _cache_dir(self) -> Path:
        """Directory where section content caches are stored."""
        p = (
            get_kb_path(self.config, self.analysis_id)
            / "cache"
            / "sections"
        )
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _load_cached_section(self, cache_key: str) -> str | None:
        """Return cached section content, or ``None``."""
        cache_file = self._cache_dir() / f"{cache_key}.txt"
        if cache_file.exists():
            return cache_file.read_text()
        return None

    def _save_cached_section(self, cache_key: str, content: str) -> None:
        """Persist generated section content so it can be reused."""
        cache_file = self._cache_dir() / f"{cache_key}.txt"
        cache_file.write_text(content)

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
