# ggdes/utils/

## Responsibility

Shared utility modules providing cross-cutting infrastructure for the GGDes system.
Currently houses the analysis locking mechanism that prevents concurrent analysis
runs on the same repository.

## Design

### File Layout

| File | Key Exports | Responsibility |
|---|---|---|
| `lock.py` | `AnalysisLock`, `LockInfo`, `LockContext` | File-based mutex lock to serialize analysis runs per repository |

### AnalysisLock (`lock.py`)

Simple file-based mutex lock stored at `{repo_path}/.lock-ggdes-analysis`.

**Lock file format:**
```
<PID>
<ISO timestamp>
<analysis_id>  (optional, on second line)
```

**State machine:**

| State | Condition |
|---|---|
| Unlocked | Lock file does not exist |
| Active (same process) | Lock file exists, PID matches `os.getpid()` — re-entrant, allowed |
| Active (other process) | Lock file exists, PID differs, not stale — blocked |
| Stale | Lock file exists but `age > LOCK_TIMEOUT_HOURS` (1 hour) — auto-cleaned |

**Key methods:**

| Method | Behavior |
|---|---|
| `acquire(analysis_id)` | Checks lock → if stale, cleans → if active other process, returns error → writes new lock |
| `release()` | Removes lock file only if held by current process |
| `is_locked()` | Returns True if active lock exists (auto-cleans stale) |
| `get_lock_info()` | Returns `LockInfo` or None (auto-cleans stale) |
| `force_acquire(analysis_id)` | Sends `SIGTERM` to existing lock holder, waits 0.5s, removes lock, acquires fresh |

### LockInfo

```python
@dataclass
class LockInfo:
    pid: int
    timestamp: datetime
    analysis_id: str | None
    # property: is_stale → age > 1 hour
```

### LockContext

Context manager that wraps `AnalysisLock` for use with `with` statements:

```python
class LockContext:
    def __init__(self, repo_path, analysis_id=None, force=False)
    def __enter__(self) -> LockContext  # Acquires lock
    def __exit__(self, ...)             # Releases lock
```

- If `force=True`, calls `lock.force_acquire()` (kills existing process)
- If `force=False`, calls `lock.acquire()`
- Raises `RuntimeError` with descriptive message if acquire fails
- Tracks `self.acquired` to only release if we actually hold the lock

## Flow

```
analyze command (ggdes/cli/commands/analyze.py)
    ↓
with LockContext(repo_path, analysis_id, force=force):
    ↓
  LockContext.__enter__()
    ↓
  AnalysisLock.acquire() or .force_acquire()
    ↓
  If stale lock → auto clean
  If active other process → raise RuntimeError
    ↓
  Write .lock-ggdes-analysis with PID, timestamp, analysis_id
    ↓
  ... run analysis pipeline ...
    ↓
LockContext.__exit__()
    ↓
AnalysisLock.release() → remove lock file
```

## Integration

- **`LockContext`** is imported and used by `ggdes/cli/commands/analyze.py` and
  `ggdes/cli/commands/resume.py` to prevent concurrent analysis runs.
- **`AnalysisLock`**, **`LockContext`**, and **`LockInfo`** are re-exported from
  `ggdes/utils/__init__.py`.
- **Consumers:** CLI commands only. The pipeline itself does not manage locks.
- **Thread safety:** Relies on atomic filesystem operations; lock timeout of
  1 hour prevents permanent locks from crashed processes.
