"""Markdown output agent for generating markdown documentation."""

from pathlib import Path
from typing import Optional

from ggdes.llm import LLMFactory, ConversationContext
from ggdes.prompts import get_prompt
from ggdes.schemas import (
    DiagramSpec,
    DocumentPlan,
    SectionPlan,
    StoragePolicy,
    TechnicalFact,
)


class MarkdownAgent:
    """Generate markdown documentation from document plan."""

    def __init__(
        self,
        repo_path: Path,
        config,
        analysis_id: str,
    ):
        """Initialize markdown agent.

        Args:
            repo_path: Path to git repository
            config: GGDesConfig instance
            analysis_id: Analysis ID for reading from KB
        """
        self.repo_path = repo_path
        self.config = config
        self.analysis_id = analysis_id
        self.llm = LLMFactory.from_config(config)
        self.conversation: Optional[ConversationContext] = None

    def _init_conversation(
        self, storage_policy: StoragePolicy = StoragePolicy.SUMMARY
    ) -> None:
        """Initialize conversation context."""
        self.conversation = ConversationContext(
            system_prompt=get_prompt("output", "markdown_system"),
            storage_policy=storage_policy,
            max_tokens=50000,
        )

    def _load_facts(self, fact_ids: list[str]) -> list[TechnicalFact]:
        """Load specific technical facts from KB."""
        from ggdes.config import get_kb_path
        import json

        facts_dir = get_kb_path(self.config, self.analysis_id) / "technical_facts"
        facts = []

        for fact_id in fact_ids:
            fact_file = facts_dir / f"{fact_id}.json"
            if fact_file.exists():
                data = json.loads(fact_file.read_text())
                facts.append(TechnicalFact(**data))

        return facts

    def _load_plan(self) -> Optional[DocumentPlan]:
        """Load document plan from KB."""
        from ggdes.config import get_kb_path
        import json

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
            return self._generate_architecture_diagram(diagram)
        elif diagram.diagram_type == "flow":
            return self._generate_flow_diagram(diagram)
        elif diagram.diagram_type == "sequence":
            return self._generate_sequence_diagram(diagram)
        elif diagram.diagram_type == "class":
            return self._generate_class_diagram(diagram)
        else:
            return f"@startuml\ntitle {diagram.title}\n{diagram.description}\n@enduml"

    def _generate_architecture_diagram(self, diagram: DiagramSpec) -> str:
        """Generate architecture diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}

package "System" {{
"""

        for element in diagram.elements_to_include[:10]:
            uml += f'  component "{element}"\n'

        uml += """}

note right
  {description}
end note

@enduml""".format(description=diagram.description)

        return uml

    def _generate_flow_diagram(self, diagram: DiagramSpec) -> str:
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

    def _generate_sequence_diagram(self, diagram: DiagramSpec) -> str:
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

    def _generate_class_diagram(self, diagram: DiagramSpec) -> str:
        """Generate class diagram PlantUML."""
        uml = f"""@startuml
!theme plain
title {diagram.title}
"""

        for element in diagram.elements_to_include[:10]:
            uml += f'class "{element}"\n'

        uml += """@enduml"""

        return uml

    async def generate(
        self,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
    ) -> Path:
        """Generate markdown document.

        Args:
            storage_policy: How to persist conversation

        Returns:
            Path to generated markdown file
        """
        # Initialize conversation
        self._init_conversation(storage_policy)

        # Load document plan
        plan = self._load_plan()
        if not plan:
            raise ValueError(f"No markdown plan found for {self.analysis_id}")

        # Generate document content
        sections_content = []

        for section in plan.sections:
            content = await self._generate_section(section)
            sections_content.append((section.title, content))

        # Generate diagrams
        diagrams_content = []
        for diagram in plan.diagrams:
            plantuml = self._generate_plantuml(diagram)
            diagrams_content.append((diagram.title, plantuml, diagram.diagram_type))

        # Build complete markdown
        markdown = self._build_markdown(plan, sections_content, diagrams_content)

        # Save to output directory
        output_path = self._save_markdown(markdown, plan)

        # Save conversation
        from ggdes.config import get_kb_path

        kb_path = (
            get_kb_path(self.config, self.analysis_id)
            / "conversations"
            / "markdown_agent"
        )
        self.conversation.save(kb_path)

        return output_path

    async def _generate_section(self, section: SectionPlan) -> str:
        """Generate content for a document section."""
        # Load relevant facts
        facts = self._load_facts(section.technical_facts)

        # Build prompt
        prompt = f"""Write the "{section.title}" section for a design document.

Section Description: {section.description}

Technical Facts to Include:
"""
        for fact in facts:
            prompt += f"- [{fact.category}] {fact.description}\n"

        if section.code_references:
            prompt += f"\nCode References: {', '.join(section.code_references)}\n"

        prompt += """
Requirements:
- Write in clear, technical prose
- Use markdown formatting (headers, lists, code blocks)
- Include specific details from the facts
- Explain the "why" not just the "what"
- Keep it concise but comprehensive

Write the section content now:"""

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
        diagrams_content: list[tuple[str, str, str]],
    ) -> str:
        """Build complete markdown document."""
        md = f"""# {plan.title}

**Target Audience:** {plan.audience}  
**Analysis ID:** {self.analysis_id}

## Table of Contents

"""

        # Add TOC
        for i, (title, _) in enumerate(sections_content, 1):
            md += f"{i}. [{title}](#{title.lower().replace(' ', '-')})\n"

        md += "\n---\n\n"

        # Add sections
        for title, content in sections_content:
            md += f"## {title}\n\n{content}\n\n"

        # Add diagrams section if any
        if diagrams_content:
            md += "## Diagrams\n\n"
            for title, plantuml, diagram_type in diagrams_content:
                md += f"### {title}\n\n"
                md += f"Type: {diagram_type}\n\n"
                md += f"```plantuml\n{plantuml}\n```\n\n"

        # Add footer
        md += f"""---

*Generated by GGDes - Git-based Design Documentation Generator*  
*Analysis: {self.analysis_id}*
"""

        return md

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
