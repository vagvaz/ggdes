"""Stage modules for the GGDes analysis pipeline."""

from ggdes.stages.base import Stage, StageResult
from ggdes.stages.worktree_setup import WorktreeSetupStage

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
    "get_stage",
    "register_stage",
]
