"""Stage modules for the GGDes analysis pipeline.

This module is the canonical source for stage name constants.
The KnowledgeBaseManager and pipeline import them from here.
"""

from collections import defaultdict, deque

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

# Stage dependency graph: each stage lists the stages it depends on.
# The pipeline scheduler uses this to compute execution order and parallelism.
# Key for parallelism: stages with no dependency on each other can run concurrently.
STAGE_DEPENDENCIES: dict[str, list[str]] = {
    STAGE_WORKTREE_SETUP: [],
    STAGE_GIT_ANALYSIS: [STAGE_WORKTREE_SETUP],
    STAGE_CHANGE_FILTER: [STAGE_GIT_ANALYSIS],
    STAGE_AST_PARSING_BASE: [STAGE_WORKTREE_SETUP],
    STAGE_AST_PARSING_HEAD: [STAGE_WORKTREE_SETUP],
    STAGE_SEMANTIC_DIFF: [STAGE_GIT_ANALYSIS],
    STAGE_TECHNICAL_AUTHOR: [
        STAGE_GIT_ANALYSIS,
        STAGE_AST_PARSING_BASE,
        STAGE_AST_PARSING_HEAD,
        STAGE_SEMANTIC_DIFF,
    ],
    STAGE_COORDINATOR_PLAN: [STAGE_TECHNICAL_AUTHOR],
    STAGE_OUTPUT_GENERATION: [STAGE_COORDINATOR_PLAN],
}

STAGE_REGISTRY: dict[str, type[Stage]] = {
    WorktreeSetupStage.name: WorktreeSetupStage,
}


def get_stage(name: str) -> type[Stage] | None:
    """Get a stage class by name. Returns None if not found."""
    return STAGE_REGISTRY.get(name)


def register_stage(stage_class: type[Stage]) -> None:
    """Register a stage class so the pipeline can find it by name."""
    STAGE_REGISTRY[stage_class.name] = stage_class


def resolve_stage_order(
    deps: dict[str, list[str]] | None = None,
) -> list[list[str]]:
    """Topological sort of stages into parallel-compatible execution layers.

    Uses Kahn's algorithm. Each inner list is a layer of stages that can
    run in parallel. Outer list is in dependency order.

    Args:
        deps: Dependency graph (name → list of prerequisite names).
              Defaults to ``STAGE_DEPENDENCIES``.

    Returns:
        List of layers, each layer being a list of stage names that can
        run concurrently. Example::

            [
                ["worktree_setup"],                    # layer 0
                ["git_analysis", "ast_parsing_base"],   # layer 1 (parallel)
                ["semantic_diff", "ast_parsing_head"],  # layer 2 (parallel)
                ["technical_author"],                   # layer 3
                ["coordinator_plan"],                   # layer 4
                ["output_generation"],                  # layer 5
            ]
    """
    graph = deps or STAGE_DEPENDENCIES

    # Compute in-degree (number of unresolved dependencies) per stage
    in_degree: dict[str, int] = dict.fromkeys(graph, 0)
    for stage, prereqs in graph.items():
        in_degree[stage] = len(prereqs)

    # Track reverse dependencies so we can decrement in_degree when a stage completes
    dependents: dict[str, list[str]] = defaultdict(list)
    for stage, prereqs in graph.items():
        for p in prereqs:
            dependents[p].append(stage)

    layers: list[list[str]] = []
    queue = deque([s for s, deg in in_degree.items() if deg == 0])

    while queue:
        current_layer: list[str] = []
        for _ in range(len(queue)):
            stage = queue.popleft()
            current_layer.append(stage)
            for dependent in dependents.get(stage, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        layers.append(sorted(current_layer))

    # Verify all stages were ordered (no cycles)
    ordered = {s for layer in layers for s in layer}
    missing = set(graph.keys()) - ordered
    if missing:
        raise ValueError(
            f"Circular dependency detected among stages: {missing}"
        )

    return layers


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
    "STAGE_DEPENDENCIES",
    "get_stage",
    "register_stage",
    "resolve_stage_order",
]
