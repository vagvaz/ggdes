"""Prompt management with versioning for GGDes."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml


class PromptLoader:
    """Load and manage versioned prompts."""

    def __init__(self, version: Optional[str] = None):
        """Initialize prompt loader.

        Args:
            version: Prompt version to use. If None, uses 'current' symlink.
        """
        self.prompts_dir = Path(__file__).parent
        self.version = version or "current"
        self._cache: dict[str, dict[str, Any]] = {}

    def _get_version_path(self) -> Path:
        """Get path to versioned prompts directory."""
        version_path = self.prompts_dir / self.version
        if not version_path.exists():
            raise ValueError(f"Prompt version '{self.version}' not found")
        return version_path

    def load_agent_prompts(self, agent_name: str) -> dict[str, Any]:
        """Load all prompts for an agent.

        Args:
            agent_name: Name of the agent (e.g., 'git_analyzer')

        Returns:
            Dictionary of prompt key -> prompt text
        """
        if agent_name in self._cache:
            return self._cache[agent_name]

        version_path = self._get_version_path()
        prompt_file = version_path / f"{agent_name}.yaml"

        if not prompt_file.exists():
            raise ValueError(
                f"No prompts found for agent '{agent_name}' in version '{self.version}'"
            )

        with open(prompt_file) as f:
            prompts = yaml.safe_load(f)

        self._cache[agent_name] = prompts
        return prompts

    def get_prompt(self, agent_name: str, prompt_key: str, **format_kwargs) -> str:
        """Get a specific prompt with optional formatting.

        Args:
            agent_name: Name of the agent
            prompt_key: Key of the prompt (e.g., 'system', 'analyze_diff')
            **format_kwargs: Values to substitute into the prompt

        Returns:
            Formatted prompt text
        """
        prompts = self.load_agent_prompts(agent_name)

        if prompt_key not in prompts:
            raise ValueError(
                f"Prompt key '{prompt_key}' not found for agent '{agent_name}'"
            )

        prompt_text = prompts[prompt_key]

        if format_kwargs:
            # Use safe substitution to avoid errors for missing keys
            # that might be filled later
            try:
                prompt_text = prompt_text.format(**format_kwargs)
            except KeyError:
                # Return unformatted if keys are missing
                pass

        return prompt_text

    def get_system_prompt(self, agent_name: str) -> str:
        """Get the system prompt for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            System prompt text
        """
        return self.get_prompt(agent_name, "system")

    def list_available_agents(self) -> list[str]:
        """List all agents with prompts in current version.

        Returns:
            List of agent names
        """
        version_path = self._get_version_path()
        agents = []

        for file in version_path.glob("*.yaml"):
            if file.name != "__init__.yaml":
                agents.append(file.stem)

        return sorted(agents)

    def list_available_versions(self) -> list[str]:
        """List all available prompt versions.

        Returns:
            List of version names
        """
        versions = []

        for item in self.prompts_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                versions.append(item.name)

        return sorted(versions)


def get_default_loader() -> PromptLoader:
    """Get a prompt loader using the default version (current)."""
    return PromptLoader()


def get_prompt(
    agent_name: str, prompt_key: str, version: Optional[str] = None, **format_kwargs
) -> str:
    """Convenience function to get a single prompt.

    Args:
        agent_name: Name of the agent
        prompt_key: Key of the prompt
        version: Optional version override
        **format_kwargs: Format arguments

    Returns:
        Formatted prompt text
    """
    loader = PromptLoader(version=version)
    return loader.get_prompt(agent_name, prompt_key, **format_kwargs)
