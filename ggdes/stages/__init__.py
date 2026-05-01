"""Stage modules for the GGDes analysis pipeline.

This module is the canonical source for stage name constants.
The KnowledgeBaseManager and pipeline import them from here.
"""

from ggdes.stages.base import Stage, StageResult
from ggdes.stages.worktree_setup import WorktreeSetupStage

# Stage name constants (canonical source — update here to rename a stage)
STAGE_WORKTREE_SETUP = "worktree_setup"
STAGE_GIT_ANALYSIS = "git_analysis"
STAGE_CHANGE_FILTER = "change_filter"
STAGE_AST_PARSING_BASE = "ast_parsing_base"
STAGE_AST_PARSING_HEAD = "ast_parsing_head"
STAGE_SEMANTIC_DIFF = "semantic_diff"
STAGE_TECHNICAL_AUTHOR = "technical_author"
STAGE_COORDINATOR_PLAN = "coordinator_plan"
STAGE_OUTPUT_GENERATION = "output_generation"

ALL_STAGES = [
    STAGE_WORKTREE_SETUP,
    STAGE_GIT_ANALYSIS,
    STAGE_CHANGE_FILTER,
    STAGE_AST_PARSING_BASE,
    STAGE_AST_PARSING_HEAD,
    STAGE_SEMANTIC_DIFF,
    STAGE_TECHNICAL_AUTHOR,
    STAGE_COORDINATOR_PLAN,
    STAGE_OUTPUT_GENERATION,
]

STAGE_REGISTRY: dict[str, type[Stage]] = {
    WorktreeSetupStage.name: WorktreeSetupStage,
}


def get_stage(name: str) -> type[Stage] | None:
    """Get a stage class by name. Returns None if not found."""
    return STAGE_REGISTRY.get(name)


def register_stage(stage_class: type[Stage]) -> None:
    """Register a stage class so the pipeline can find it by name."""
    STAGE_REGISTRY[stage_class.name] = stage_class


__all__ = [
    "Stage",
    "StageResult",
    "WorktreeSetupStage",
    "STAGE_REGISTRY",
    "STAGE_WORKTREE_SETUP",
    "STAGE_GIT_ANALYSIS",
    "STAGE_CHANGE_FILTER",
    "STAGE_AST_PARSING_BASE",
    "STAGE_AST_PARSING_HEAD",
    "STAGE_SEMANTIC_DIFF",
    "STAGE_TECHNICAL_AUTHOR",
    "STAGE_COORDINATOR_PLAN",
    "STAGE_OUTPUT_GENERATION",
    "ALL_STAGES",
    "get_stage",
    "register_stage",
]
