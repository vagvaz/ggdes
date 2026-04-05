"""Storage policy enum for conversation persistence."""

from enum import Enum


class StoragePolicy(str, Enum):
    """How to persist agent conversations."""

    RAW = "raw"  # Save every turn (for debugging)
    SUMMARY = "summary"  # Save summaries only (default)
    NONE = "none"  # Don't persist (save tokens/disk)
