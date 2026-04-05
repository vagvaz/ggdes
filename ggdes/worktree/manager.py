"""Worktree management for isolated git operations."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ggdes.config import GGDesConfig, get_worktrees_path


@dataclass
class WorktreePair:
    """Pair of worktrees for base and head commits."""

    base: Path
    head: Path
    analysis_id: str

    def cleanup(self) -> None:
        """Remove both worktrees."""
        _remove_worktree(self.base)
        _remove_worktree(self.head)


class WorktreeManager:
    """Manage git worktrees for analysis isolation."""

    def __init__(self, config: GGDesConfig, repo_path: Path):
        """Initialize worktree manager.

        Args:
            config: GGDes configuration
            repo_path: Path to the git repository
        """
        self.config = config
        self.repo_path = repo_path.resolve()
        self.worktrees_base = Path(config.paths.worktrees).expanduser()

    def create_for_analysis(
        self,
        analysis_id: str,
        base_commit: str,
        head_commit: str,
    ) -> WorktreePair:
        """Create BASE and HEAD worktrees for an analysis.

        Args:
            analysis_id: Unique identifier for the analysis
            base_commit: Git commit/branch for base state
            head_commit: Git commit/branch for head state

        Returns:
            WorktreePair with paths to base and head worktrees

        Raises:
            RuntimeError: If worktree creation fails
        """
        import subprocess

        # Use absolute paths for everything
        analysis_wt_path = get_worktrees_path(self.config, analysis_id).resolve()
        base_path = analysis_wt_path / "base"
        head_path = analysis_wt_path / "head"

        # Resolve repo path to absolute
        repo_path = self.repo_path.resolve()

        print(f"[worktree] Analysis worktree path: {analysis_wt_path}")
        print(f"[worktree] Repository path: {repo_path}")
        print(f"[worktree] Base commit: {base_commit}")
        print(f"[worktree] Head commit: {head_commit}")

        # Create parent directory
        analysis_wt_path.mkdir(parents=True, exist_ok=True)

        # Remove existing worktrees if they exist (cleanup from previous run)
        if base_path.exists():
            print(f"[worktree] Removing existing base worktree: {base_path}")
            try:
                _remove_worktree(base_path)
            except Exception as e:
                print(
                    f"[worktree] Warning: Failed to remove existing base worktree: {e}"
                )
                # Force remove manually if git worktree remove fails
                import shutil

                if base_path.exists():
                    shutil.rmtree(base_path, ignore_errors=True)

        if head_path.exists():
            print(f"[worktree] Removing existing head worktree: {head_path}")
            try:
                _remove_worktree(head_path)
            except Exception as e:
                print(
                    f"[worktree] Warning: Failed to remove existing head worktree: {e}"
                )
                import shutil

                if head_path.exists():
                    shutil.rmtree(head_path, ignore_errors=True)

        # Create worktrees with better error handling
        print(
            f"[worktree] Creating base worktree at {base_path} for commit {base_commit}"
        )
        try:
            _create_worktree(repo_path, base_path, base_commit)
        except subprocess.CalledProcessError as e:
            error_msg = (
                f"Failed to create base worktree: {e.stderr if e.stderr else str(e)}"
            )
            print(f"[worktree] {error_msg}")
            raise RuntimeError(error_msg) from e

        print(
            f"[worktree] Creating head worktree at {head_path} for commit {head_commit}"
        )
        try:
            _create_worktree(repo_path, head_path, head_commit)
        except subprocess.CalledProcessError as e:
            error_msg = (
                f"Failed to create head worktree: {e.stderr if e.stderr else str(e)}"
            )
            print(f"[worktree] {error_msg}")
            # Clean up base worktree if head fails
            if base_path.exists():
                try:
                    _remove_worktree(base_path)
                except:
                    pass
            raise RuntimeError(error_msg) from e

        # Verify worktrees were created
        if not base_path.exists():
            # Try to debug - maybe git created it elsewhere
            print(
                f"[worktree] ERROR: Base worktree directory not created at expected path: {base_path}"
            )
            print(f"[worktree] Checking if parent exists: {analysis_wt_path.exists()}")
            if analysis_wt_path.exists():
                print(
                    f"[worktree] Contents of parent: {list(analysis_wt_path.iterdir())}"
                )

            # Check git worktree list
            try:
                import subprocess

                result = subprocess.run(
                    ["git", "-C", str(repo_path), "worktree", "list"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                print(f"[worktree] Git worktree list:\n{result.stdout}")
                if result.stderr:
                    print(f"[worktree] Git worktree list stderr: {result.stderr}")
            except Exception as e:
                print(f"[worktree] Could not get worktree list: {e}")

            raise RuntimeError(f"Base worktree directory not created: {base_path}")

        if not head_path.exists():
            print(
                f"[worktree] ERROR: Head worktree directory not created at expected path: {head_path}"
            )
            raise RuntimeError(f"Head worktree directory not created: {head_path}")

        print(f"[worktree] Successfully created worktrees")

        return WorktreePair(
            base=base_path,
            head=head_path,
            analysis_id=analysis_id,
        )

    def get_existing(self, analysis_id: str) -> WorktreePair | None:
        """Get existing worktrees for an analysis if they exist.

        Args:
            analysis_id: Analysis identifier

        Returns:
            WorktreePair if exists, None otherwise
        """
        analysis_wt_path = get_worktrees_path(self.config, analysis_id)
        base_path = analysis_wt_path / "base"
        head_path = analysis_wt_path / "head"

        if base_path.exists() and head_path.exists():
            return WorktreePair(
                base=base_path,
                head=head_path,
                analysis_id=analysis_id,
            )
        return None

    def cleanup(self, analysis_id: str) -> None:
        """Remove worktrees for an analysis.

        Args:
            analysis_id: Analysis identifier
        """
        analysis_wt_path = get_worktrees_path(self.config, analysis_id)
        base_path = analysis_wt_path / "base"
        head_path = analysis_wt_path / "head"

        if base_path.exists():
            _remove_worktree(base_path)
        if head_path.exists():
            _remove_worktree(head_path)

        # Clean up empty analysis directory
        if analysis_wt_path.exists() and not any(analysis_wt_path.iterdir()):
            analysis_wt_path.rmdir()

    def list_all(self) -> list[tuple[str, Path, Path]]:
        """List all worktree pairs in the worktrees directory.

        Returns:
            List of (analysis_id, base_path, head_path) tuples
        """
        result = []

        if not self.worktrees_base.exists():
            return result

        for analysis_dir in self.worktrees_base.iterdir():
            if analysis_dir.is_dir():
                base_path = analysis_dir / "base"
                head_path = analysis_dir / "head"
                if base_path.exists() and head_path.exists():
                    result.append((analysis_dir.name, base_path, head_path))

        return result


def _create_worktree(repo_path: Path, worktree_path: Path, commit: str) -> None:
    """Create a git worktree.

    Args:
        repo_path: Path to the main repository
        worktree_path: Path where worktree should be created
        commit: Commit, branch, or ref to checkout

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    import subprocess

    cmd = ["git", "-C", str(repo_path), "worktree", "add", str(worktree_path), commit]
    print(f"[worktree] Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        error_msg = f"Git worktree add failed:\n"
        error_msg += f"  Command: {' '.join(cmd)}\n"
        error_msg += f"  Exit code: {result.returncode}\n"
        if result.stderr:
            error_msg += f"  Stderr: {result.stderr}\n"
        if result.stdout:
            error_msg += f"  Stdout: {result.stdout}\n"
        print(f"[worktree] {error_msg}")
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )

    if result.stdout:
        print(f"[worktree] {result.stdout.strip()}")


def _remove_worktree(worktree_path: Path) -> None:
    """Remove a git worktree.

    Args:
        worktree_path: Path to the worktree

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    try:
        # First try git worktree remove
        cmd = [
            "git",
            "-C",
            str(worktree_path),
            "worktree",
            "remove",
            "-f",
            str(worktree_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        # If that fails, force remove manually
        import shutil

        if worktree_path.exists():
            shutil.rmtree(worktree_path)
