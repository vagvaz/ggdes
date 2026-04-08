"""Configuration management for GGDes."""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class StructuredOutputFormat(str, Enum):
    """Structured output format for LLM responses."""

    AUTO = "auto"  # Automatically choose based on provider
    JSON = "json"  # JSON format
    XML = "xml"  # XML format


class ModelConfig(BaseModel):
    """LLM model configuration."""

    provider: str = "anthropic"
    model_name: str = "claude-3-5-sonnet-20241022"
    api_key: str = "${ANTHROPIC_API_KEY}"
    base_url: Optional[str] = None  # For custom endpoints (Ollama, etc.)
    structured_format: StructuredOutputFormat = Field(
        default=StructuredOutputFormat.AUTO,
        description="Output format for structured responses: 'auto', 'json', or 'xml'",
    )

    @field_validator("api_key")
    @classmethod
    def resolve_api_key(cls, v: str) -> str:
        """Resolve API key from environment variable if prefixed with ${}."""
        if v.startswith("${") and v.endswith("}"):
            env_var = v[2:-1]
            api_key = os.getenv(env_var)
            if api_key:
                return api_key
            # Return original if env var not set (will error later)
        return v


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


class ParsingMode(str, Enum):
    """AST parsing mode."""

    FULL = "full"  # Parse all supported files in the repository
    INCREMENTAL = "incremental"  # Parse only changed and referenced files


class ParsingConfig(BaseModel):
    """AST parsing configuration."""

    mode: ParsingMode = Field(
        default=ParsingMode.FULL,
        description="Parsing mode: 'full' for all files, 'incremental' for changed + referenced only",
    )
    include_referenced: bool = Field(
        default=True,
        description="In incremental mode, also parse files that import/reference changed files",
    )
    max_referenced_depth: int = Field(
        default=1,
        ge=0,
        le=3,
        description="How many levels of references to follow (0 = only changed files, 1 = direct imports, etc.)",
    )


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
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
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
    cli_provider: Optional[str] = None,
    cli_model_name: Optional[str] = None,
    cli_api_key: Optional[str] = None,
) -> tuple[GGDesConfig, Path]:
    """Load configuration with CLI overrides.

    Resolution order (highest priority first):
    1. CLI arguments
    2. Project-local config (./ggdes.yaml)
    3. User global config (~/.ggdes/config.yaml)
    4. Defaults

    Args:
        cli_repo_path: Repository path from CLI
        cli_provider: Model provider from CLI
        cli_model_name: Model name from CLI
        cli_api_key: API key from CLI

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
    if cli_provider:
        config.model.provider = cli_provider
    if cli_model_name:
        config.model.model_name = cli_model_name
    if cli_api_key:
        config.model.api_key = cli_api_key

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
