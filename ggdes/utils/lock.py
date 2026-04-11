"""Lock system for preventing concurrent analysis on the same repository."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

LOCK_FILE_NAME = ".lock-ggdes-analysis"
LOCK_TIMEOUT_HOURS = 1  # Consider lock stale after 1 hour


@dataclass
class LockInfo:
    """Information about a lock."""

    pid: int
    timestamp: datetime
    analysis_id: str | None = None

    @property
    def is_stale(self) -> bool:
        """Check if the lock is stale (timeout exceeded)."""
        age = datetime.now() - self.timestamp
        return age > timedelta(hours=LOCK_TIMEOUT_HOURS)


class AnalysisLock:
    """Lock manager for preventing concurrent analyses."""

    def __init__(self, repo_path: Path):
        """Initialize lock manager.

        Args:
            repo_path: Path to the git repository
        """
        self.repo_path = repo_path.resolve()
        self.lock_file = self.repo_path / LOCK_FILE_NAME

    def acquire(self, analysis_id: str | None = None) -> tuple[bool, str | None]:
        """Attempt to acquire the lock.

        Args:
            analysis_id: Optional analysis identifier to store in lock

        Returns:
            Tuple of (success, error_message_if_failed)
        """
        # Check if lock exists
        if self.lock_file.exists():
            lock_info = self._read_lock()

            if lock_info and not lock_info.is_stale:
                # Lock is active
                if lock_info.pid == os.getpid():
                    # Same process, allow (re-entrant)
                    return True, None

                return (
                    False,
                    f"Analysis already in progress (PID: {lock_info.pid}, "
                    f"Analysis: {lock_info.analysis_id or 'unknown'}). "
                    f"Use --force to override (kills other process).",
                )

            # Lock is stale, clean it up
            self._remove_lock()

        # Create lock
        try:
            self._write_lock(analysis_id)
            return True, None
        except Exception as e:
            return False, f"Failed to create lock: {e}"

    def release(self) -> bool:
        """Release the lock.

        Returns:
            True if lock was released, False if not held
        """
        if not self.lock_file.exists():
            return False

        lock_info = self._read_lock()
        if lock_info and lock_info.pid != os.getpid():
            # Lock is held by another process
            return False

        return self._remove_lock()

    def is_locked(self) -> bool:
        """Check if the repository is currently locked.

        Returns:
            True if locked by active process, False otherwise
        """
        if not self.lock_file.exists():
            return False

        lock_info = self._read_lock()
        if not lock_info:
            return False

        if lock_info.is_stale:
            # Clean up stale lock
            self._remove_lock()
            return False

        return True

    def get_lock_info(self) -> LockInfo | None:
        """Get information about the current lock.

        Returns:
            LockInfo if locked, None otherwise
        """
        if not self.lock_file.exists():
            return None

        lock_info = self._read_lock()
        if lock_info and lock_info.is_stale:
            self._remove_lock()
            return None

        return lock_info

    def force_acquire(self, analysis_id: str | None = None) -> tuple[bool, str | None]:
        """Force acquire the lock, killing any existing lock holder.

        Args:
            analysis_id: Optional analysis identifier

        Returns:
            Tuple of (success, error_message_if_failed)
        """
        # Check if another process holds the lock
        lock_info = self._read_lock()
        if lock_info and lock_info.pid != os.getpid():
            # Try to kill the process
            try:
                import signal

                os.kill(lock_info.pid, signal.SIGTERM)
                # Give it a moment to terminate
                import time

                time.sleep(0.5)
            except (ProcessLookupError, PermissionError):
                # Process doesn't exist or can't kill it
                pass

        # Remove existing lock
        self._remove_lock()

        # Create new lock
        return self.acquire(analysis_id)

    def _read_lock(self) -> LockInfo | None:
        """Read lock file contents."""
        try:
            with open(self.lock_file) as f:
                lines = f.read().strip().split("\n")

            pid = int(lines[0])
            timestamp = (
                datetime.fromisoformat(lines[1]) if len(lines) > 1 else datetime.now()
            )
            analysis_id = lines[2] if len(lines) > 2 else None

            return LockInfo(pid=pid, timestamp=timestamp, analysis_id=analysis_id)
        except (ValueError, IndexError, FileNotFoundError):
            return None

    def _write_lock(self, analysis_id: str | None = None) -> None:
        """Write lock file."""
        content = f"{os.getpid()}\n{datetime.now().isoformat()}"
        if analysis_id:
            content += f"\n{analysis_id}"

        with open(self.lock_file, "w") as f:
            f.write(content)

    def _remove_lock(self) -> bool:
        """Remove lock file.

        Returns:
            True if removed or didn't exist, False on error
        """
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
            return True
        except Exception:
            return False


class LockContext:
    """Context manager for analysis locks."""

    def __init__(
        self, repo_path: Path, analysis_id: str | None = None, force: bool = False
    ):
        """Initialize lock context.

        Args:
            repo_path: Path to the repository
            analysis_id: Analysis identifier
            force: Force acquire even if locked
        """
        self.lock = AnalysisLock(repo_path)
        self.analysis_id = analysis_id
        self.force = force
        self.acquired = False

    def __enter__(self) -> "LockContext":
        """Acquire lock on enter."""
        if self.force:
            success, error = self.lock.force_acquire(self.analysis_id)
        else:
            success, error = self.lock.acquire(self.analysis_id)

        if not success:
            raise RuntimeError(error)

        self.acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Release lock on exit."""
        if self.acquired:
            self.lock.release()
