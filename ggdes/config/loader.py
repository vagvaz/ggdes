"""Configuration management for GGDes."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class ModelConfig(BaseModel):
    """LLM model configuration."""

    default: str = "anthropic/claude-3-5-sonnet-20241022"
    # Future: per-agent overrides


class PathsConfig(BaseModel):
    """Path configuration."""

    knowledge_base: str = "~/ggdes-kb"
    worktrees: str = "~/ggdes-worktrees"

    @field_validator("knowledge_base", "worktrees")
    @classmethod
    def expand_user(cls, v: str) -> str:
        """Expand ~ to home directory."""
        return os.path.expanduser(v)


class FeaturesConfig(BaseModel):
    """Feature flags configuration."""

    dual_state_analysis: bool = False
    auto_cleanup: bool = True
    worktree_retention_days: int = 7


class OutputConfig(BaseModel):
    """Output configuration."""

    default_format: str = "markdown"
    formats: list[str] = Field(
        default_factory=lambda: ["markdown", "docx", "pptx", "pdf"]
    )


class RepoConfig(BaseModel):
    """Repository configuration."""

    path: Optional[str] = None


class GGDesConfig(BaseModel):
    """Main GGDes configuration."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    repo: RepoConfig = Field(default_factory=RepoConfig)

    @classmethod
    def from_file(cls, path: Path) -> "GGDesConfig":
        """Load configuration from YAML file."""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def save(self, path: Path) -> None:
        """Save configuration to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)


def load_config(
    cli_repo_path: Optional[str] = None,
    cli_model: Optional[str] = None,
) -> tuple[GGDesConfig, Path]:
    """Load configuration with CLI overrides.

    Resolution order (highest priority first):
    1. CLI arguments
    2. Project-local config (./ggdes.yaml)
    3. User global config (~/.ggdes/config.yaml)
    4. Defaults

    Args:
        cli_repo_path: Repository path from CLI
        cli_model: Model from CLI

    Returns:
        Tuple of (resolved config, resolved repo path)
    """
    # Start with defaults
    config = GGDesConfig()

    # Load global config if exists
    global_config_path = Path.home() / ".ggdes" / "config.yaml"
    if global_config_path.exists():
        global_config = GGDesConfig.from_file(global_config_path)
        # Merge (global overrides defaults)
        config = merge_configs(config, global_config)

    # Load project-local config if exists
    local_config_path = Path("ggdes.yaml")
    if local_config_path.exists():
        local_config = GGDesConfig.from_file(local_config_path)
        # Merge (local overrides global)
        config = merge_configs(config, local_config)

    # Apply CLI overrides (highest priority)
    if cli_repo_path:
        config.repo.path = cli_repo_path
    if cli_model:
        config.model.default = cli_model

    # Resolve repo path
    if config.repo.path:
        repo_path = Path(config.repo.path).resolve()
    else:
        # Default to current directory
        repo_path = Path.cwd()

    config.repo.path = str(repo_path)

    return config, repo_path


def merge_configs(base: GGDesConfig, override: GGDesConfig) -> GGDesConfig:
    """Merge two configurations, with override taking precedence."""
    base_dict = base.model_dump()
    override_dict = override.model_dump()

    def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = deep_merge(result[key], value)
            elif value is not None:
                result[key] = value
        return result

    merged = deep_merge(base_dict, override_dict)
    return GGDesConfig(**merged)


def get_kb_path(config: GGDesConfig, analysis_id: str) -> Path:
    """Get knowledge base path for an analysis."""
    kb_base = Path(config.paths.knowledge_base).expanduser()
    return kb_base / "analyses" / analysis_id


def get_worktrees_path(config: GGDesConfig, analysis_id: str) -> Path:
    """Get worktrees path for an analysis."""
    wt_base = Path(config.paths.worktrees).expanduser()
    return wt_base / analysis_id
