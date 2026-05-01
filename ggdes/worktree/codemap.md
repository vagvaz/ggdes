# ggdes/worktree/ — Git Worktree Management

## Responsibility

Creates and manages **isolated git worktrees** so that the system can inspect old and new code simultaneously. Each analysis gets a pair of worktrees: one for the **base** (pre-change) commit and one for the **head** (post-change) commit. The module also handles cleanup of stale worktrees to reclaim disk space.

This is a **stand-alone module** — it depends only on `ggdes.config` for path resolution and has no knowledge of the pipeline, stages, or KB.

## Design

### Key Types

| Type | Role |
|---|---|
| `WorktreePair` (dataclass) | Holds `base: Path`, `head: Path`, `analysis_id: str`. Has a `cleanup()` method that removes both worktrees. |
| `WorktreeManager` | Main class. Wraps `git worktree add` / `git worktree remove` commands. |

### WorktreeManager API

| Method | Description |
|---|---|
| `__init__(config, repo_path)` | Resolves config, stores repo path and worktrees base directory. |
| `create_for_analysis(analysis_id, base_commit, head_commit) → WorktreePair` | Creates `{worktrees_base}/{analysis_id}/base` and `{worktrees_base}/{analysis_id}/head` directories, checks out the specified commits via `git worktree add`. Removes pre-existing worktrees first. Returns a `WorktreePair`. |
| `get_existing(analysis_id) → WorktreePair | None` | Checks if both base/head directories exist already, returns them if so. |
| `cleanup(analysis_id)` | Removes the worktree pair for an analysis. Deletes the parent directory if empty. |
| `cleanup_old_worktrees(max_age_days, dry_run) → list[tuple]` | Iterates all worktree directories, compares `st_mtime` against cutoff, and removes those older than `max_age_days`. Honors `config.worktree_retention_days` if set. Returns list of `(analysis_id, path, age_days)` tuples. |
| `get_worktree_age(analysis_id) → float | None` | Returns age in days of the analysis's worktree directory. |
| `list_all() → list[tuple[str, Path, Path]]` | Lists all existing worktree pairs as `(analysis_id, base_path, head_path)`. |

### Private Module Functions

| Function | Description |
|---|---|
| `_create_worktree(repo_path, worktree_path, commit)` | Shells out to `git -C <repo> worktree add <path> <commit>`. Raises `CalledProcessError` on failure. |
| `_remove_worktree(worktree_path)` | First tries `git -C <path> worktree remove -f <path>`. If that fails, falls back to `shutil.rmtree`. |

### Worktree Directory Layout

```
{worktrees_base}/{analysis_id}/
├── base/     → checked out at base_commit
└── head/     → checked out at head_commit
```

The `worktrees_base` path comes from `config.paths.worktrees` (typically `{project_root}/.ggdes/worktrees/`).

### Cleanup Logic

`cleanup_old_worktrees()` works by:
1. Computing a cutoff date (`now - max_age_days`).
2. Walking `worktrees_base/` for subdirectories.
3. Checking `st_mtime` of each directory.
4. If older than cutoff: calling `self.cleanup(analysis_id)` which removes both worktrees via `git worktree remove -f` (with `shutil.rmtree` fallback).
5. Supports `dry_run=True` to preview without deleting.

The config key `worktree_retention_days` (default 7) controls the cutoff.

## Flow

```
create_for_analysis(id, base, head):
  path = worktrees_base / id
  path.mkdir(parents=True)
  remove existing base/head if present
  _create_worktree(repo, path/base, base_commit)
  _create_worktree(repo, path/head, head_commit)
  verify both exist
  return WorktreePair(base, head, id)

cleanup(id):
  _remove_worktree(path/base)
  _remove_worktree(path/head)
  rmdir(path) if empty

cleanup_old_worktrees(days, dry_run):
  for each dir in worktrees_base:
    if dir is older than (now - days):
      if dry_run: record
      else: cleanup(dir.name)
```

## Integration

- **`ggdes.config`**: Uses `config.paths.worktrees` for root path. `get_worktrees_path(config, analysis_id)` resolves the full path for an analysis.
- **`ggdes.kb`**: Not used directly. Worktree creation is a prerequisite that happens before KB stage tracking.
- **`ggdes.pipeline`**: `AnalysisPipeline` calls `WorktreeManager.create_for_analysis()` during the `worktree_setup` stage.
- **`ggdes.web.routes.worktrees`**: Uses `WorktreeManager` for stats, cleanup-preview, and cleanup endpoints.
- **`ggdes.tui`**: `GGDesTUI._delete_analysis()` uses `WorktreeManager.cleanup()` before deleting from KB.
- **Stand-alone**: Can be imported and used independently without instantiating the pipeline.

### File: `manager.py` (381 lines)

Single-file module. Exports `WorktreePair` and `WorktreeManager`. Depends only on `ggdes.config` (no pipeline/KB imports).
