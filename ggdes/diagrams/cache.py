"""Diagram caching for GGDes.

Provides caching for generated diagrams to avoid regeneration when facts haven't changed.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ggdes.schemas import TechnicalFact


@dataclass
class DiagramCacheEntry:
    """Cache entry for a generated diagram."""

    diagram_path: Path
    facts_hash: str
    diagram_type: str
    created_at: str


class DiagramCache:
    """Cache for generated diagrams.

    Diagrams are cached based on the hash of the technical facts used to generate them.
    If the facts haven't changed, the cached diagram is reused.
    """

    def __init__(self, cache_dir: Path):
        """Initialize diagram cache.

        Args:
            cache_dir: Directory to store cached diagrams and metadata
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self.cache_dir / "cache_index.json"
        self._index: dict[str, dict] = self._load_index()

    def _load_index(self) -> dict[str, dict]:
        """Load cache index from disk."""
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_index(self) -> None:
        """Save cache index to disk."""
        with open(self._cache_file, "w") as f:
            json.dump(self._index, f, indent=2)

    def _compute_facts_hash(self, facts: list[TechnicalFact]) -> str:
        """Compute a hash of the technical facts.

        Args:
            facts: List of technical facts

        Returns:
            Hash string representing the facts
        """
        # Create a deterministic string representation of the facts
        fact_data = []
        for fact in sorted(facts, key=lambda f: f.fact_id):
            fact_data.append(
                {
                    "fact_id": fact.fact_id,
                    "category": fact.category,
                    "description": fact.description,
                    "source_elements": sorted(fact.source_elements),
                    "source_file": fact.source_file,
                }
            )

        facts_str = json.dumps(fact_data, sort_keys=True)
        return hashlib.sha256(facts_str.encode()).hexdigest()[:16]

    def get_cached_diagram(
        self,
        analysis_id: str,
        diagram_type: str,
        facts: list[TechnicalFact],
    ) -> Optional[Path]:
        """Check if a cached diagram exists for the given facts.

        Args:
            analysis_id: Analysis identifier
            diagram_type: Type of diagram (architecture, flow, class, etc.)
            facts: List of technical facts used to generate the diagram

        Returns:
            Path to cached diagram if exists and is valid, None otherwise
        """
        cache_key = f"{analysis_id}_{diagram_type}"
        current_hash = self._compute_facts_hash(facts)

        if cache_key in self._index:
            entry = self._index[cache_key]
            # Check if facts hash matches (diagram is still valid)
            if entry.get("facts_hash") == current_hash:
                diagram_path = Path(entry.get("diagram_path"))
                if diagram_path.exists():
                    return diagram_path
                else:
                    # Cached file doesn't exist, remove from index
                    del self._index[cache_key]
                    self._save_index()

        return None

    def cache_diagram(
        self,
        analysis_id: str,
        diagram_type: str,
        facts: list[TechnicalFact],
        diagram_path: Path,
    ) -> None:
        """Cache a generated diagram.

        Args:
            analysis_id: Analysis identifier
            diagram_type: Type of diagram
            facts: List of technical facts used to generate the diagram
            diagram_path: Path to the generated diagram file
        """
        from datetime import datetime

        cache_key = f"{analysis_id}_{diagram_type}"
        facts_hash = self._compute_facts_hash(facts)

        self._index[cache_key] = {
            "diagram_path": str(diagram_path),
            "facts_hash": facts_hash,
            "diagram_type": diagram_type,
            "created_at": datetime.now().isoformat(),
        }

        self._save_index()

    def invalidate_cache(self, analysis_id: str) -> None:
        """Invalidate all cached diagrams for an analysis.

        Args:
            analysis_id: Analysis identifier
        """
        keys_to_remove = [
            key for key in self._index.keys() if key.startswith(f"{analysis_id}_")
        ]

        for key in keys_to_remove:
            # Optionally delete the cached file
            diagram_path = Path(self._index[key].get("diagram_path", ""))
            if diagram_path.exists():
                diagram_path.unlink()
            del self._index[key]

        if keys_to_remove:
            self._save_index()

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        total_entries = len(self._index)
        valid_entries = 0
        invalid_entries = 0

        for entry in self._index.values():
            diagram_path = Path(entry.get("diagram_path", ""))
            if diagram_path.exists():
                valid_entries += 1
            else:
                invalid_entries += 1

        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "invalid_entries": invalid_entries,
            "cache_dir": str(self.cache_dir),
        }

    def cleanup(self, max_age_days: int = 30) -> int:
        """Clean up old cached diagrams.

        Args:
            max_age_days: Maximum age of cache entries in days

        Returns:
            Number of entries removed
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=max_age_days)
        keys_to_remove = []

        for key, entry in self._index.items():
            created_at = datetime.fromisoformat(entry.get("created_at", "2000-01-01"))
            if created_at < cutoff:
                # Delete the cached file
                diagram_path = Path(entry.get("diagram_path", ""))
                if diagram_path.exists():
                    diagram_path.unlink()
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._index[key]

        if keys_to_remove:
            self._save_index()

        return len(keys_to_remove)
