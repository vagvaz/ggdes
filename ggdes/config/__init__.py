"""Configuration management for GGDes."""

from ggdes.config.loader import (
    GGDesConfig,
    FeaturesConfig,
    ModelConfig,
    OutputConfig,
    PathsConfig,
    RepoConfig,
    get_kb_path,
    get_worktrees_path,
    load_config,
    merge_configs,
)

__all__ = [
    "GGDesConfig",
    "FeaturesConfig",
    "ModelConfig",
    "OutputConfig",
    "PathsConfig",
    "RepoConfig",
    "get_kb_path",
    "get_worktrees_path",
    "load_config",
    "merge_configs",
]
