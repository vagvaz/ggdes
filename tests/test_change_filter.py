"""Tests for semantic change filter module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ggdes.agents.change_filter import (
    ChangeFilter,
    DiffHunk,
    FileClassification,
    ChangeFilterResult,
    group_hunks_by_file,
    parse_diff_into_hunks,
)
from ggdes.config import GGDesConfig
from ggdes.schemas import ChangeSummary, ChangeType, FileChange, ImpactLevel


# ============================================================
# Diff Parsing Tests
# ============================================================


class TestParseDiffIntoHunks:
    """Test parse_diff_into_hunks function."""

    def test_empty_diff(self):
        """Empty diff returns no hunks."""
        hunks = parse_diff_into_hunks("")
        assert hunks == []

    def test_single_file_single_hunk(self):
        """Single file with one hunk."""
        diff = """diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ class App:
     def __init__(self):
         self.name = 'app'
 
+    def new_feature(self):
+        return True
+
     def run(self):
         pass
"""
        hunks = parse_diff_into_hunks(diff)
        assert len(hunks) == 1
        assert hunks[0].file_path == "src/main.py"
        assert hunks[0].start_line == 10
        assert hunks[0].lines_added >= 2  # At least the two added lines

    def test_multiple_files(self):
        """Multiple files in diff."""
        diff = """diff --git a/src/main.py b/src/main.py
index abc..def 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 import os
 
+import sys
 
 def main():
diff --git a/src/utils.py b/src/utils.py
index 789..012 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -5,3 +5,5 @@ def helper():
     pass
 
+def new_helper():
+    pass
"""
        hunks = parse_diff_into_hunks(diff)
        assert len(hunks) == 2
        file_paths = [h.file_path for h in hunks]
        assert "src/main.py" in file_paths
        assert "src/utils.py" in file_paths

    def test_multiple_hunks_same_file(self):
        """Multiple hunks in the same file."""
        diff = """diff --git a/app.py b/app.py
index abc..def 100644
--- a/app.py
+++ b/app.py
@@ -5,3 +5,5 @@ class App:
     def method1(self):
         pass
 
+    def new_method1(self):
+        pass
@@ -20,3 +22,5 @@ class App:
     def method2(self):
         pass
 
+    def new_method2(self):
+        pass
"""
        hunks = parse_diff_into_hunks(diff)
        assert len(hunks) == 2
        assert all(h.file_path == "app.py" for h in hunks)

    def test_deletion_only_hunk(self):
        """Hunk with only deletions."""
        diff = """diff --git a/old.py b/old.py
index abc..def 100644
--- a/old.py
+++ b/old.py
@@ -5,5 +5,3 @@ def function():
     x = 1
-    y = 2
-    z = 3
     return x
"""
        hunks = parse_diff_into_hunks(diff)
        assert len(hunks) == 1
        assert hunks[0].lines_deleted == 2

    def test_binary_file_skipped(self):
        """Binary files don't have hunks."""
        diff = """diff --git a/image.png b/image.png
Binary files /dev/null and b/image.png differ
"""
        hunks = parse_diff_into_hunks(diff)
        # Binary file has no hunk headers, so no hunks
        assert len(hunks) == 0


class TestGroupHunksByFile:
    """Test group_hunks_by_file function."""

    def test_group_single_file(self):
        """Group hunks for a single file."""
        hunks = [
            DiffHunk("src/main.py", 10, 20, "content", 5, 2),
        ]
        by_file = group_hunks_by_file(hunks)
        assert "src/main.py" in by_file
        assert len(by_file["src/main.py"]) == 1

    def test_group_multiple_files(self):
        """Group hunks across multiple files."""
        hunks = [
            DiffHunk("src/main.py", 10, 20, "content1", 5, 2),
            DiffHunk("src/main.py", 30, 40, "content2", 3, 1),
            DiffHunk("src/utils.py", 5, 10, "content3", 2, 0),
        ]
        by_file = group_hunks_by_file(hunks)
        assert len(by_file) == 2
        assert len(by_file["src/main.py"]) == 2
        assert len(by_file["src/utils.py"]) == 1

    def test_empty_hunks(self):
        """Empty hunks list returns empty dict."""
        by_file = group_hunks_by_file([])
        assert by_file == {}


# ============================================================
# ChangeFilter Tests
# ============================================================


class TestChangeFilter:
    """Test ChangeFilter class."""

    def _make_config(self):
        """Create a mock config for testing."""
        config = MagicMock()
        config.model.provider = "openai"
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.structured_format = "auto"
        config.model.max_retries = 3
        config.model.initial_delay = 1.0
        return config

    def _make_change_summary(self, files=None):
        """Create a test ChangeSummary."""
        if files is None:
            files = [
                FileChange(
                    path="src/main.py",
                    change_type="modified",
                    lines_added=10,
                    lines_deleted=5,
                    summary="Added new feature",
                ),
                FileChange(
                    path="src/utils.py",
                    change_type="modified",
                    lines_added=3,
                    lines_deleted=1,
                    summary="Added helper function",
                ),
                FileChange(
                    path=".github/workflows/ci.yml",
                    change_type="modified",
                    lines_added=2,
                    lines_deleted=0,
                    summary="Updated CI config",
                ),
            ]
        return ChangeSummary(
            commit_hash="abc123",
            commit_range="abc123..def456",
            change_type=ChangeType.FEATURE,
            description="Added new feature",
            intent="Implement feature X",
            impact="Core functionality",
            impact_level=ImpactLevel.MEDIUM,
            files_changed=files,
        )

    def test_no_feature_description_returns_original(self):
        """Without feature description, returns original summary unchanged."""
        config = self._make_config()
        change_filter = ChangeFilter(config=config, feature_description="")
        summary = self._make_change_summary()
        result = change_filter.filter_changes(summary, "some diff")
        assert result is summary  # Same object returned

    def test_empty_diff_returns_original(self):
        """With empty diff, returns original summary unchanged."""
        config = self._make_config()
        change_filter = ChangeFilter(config=config, feature_description="test feature")
        summary = self._make_change_summary()
        result = change_filter.filter_changes(summary, "")
        assert result is summary

    def test_filter_changes_with_llm_classification(self):
        """Test that filter_changes uses LLM classification to filter files."""
        config = self._make_config()
        change_filter = ChangeFilter(config=config, feature_description="new feature X")

        # Mock the LLM to return a classification
        mock_result = ChangeFilterResult(
            classifications=[
                FileClassification(
                    file_path="src/main.py",
                    is_relevant=True,
                    relevant_line_ranges=[(10, 20)],
                    reason="Directly implements feature X",
                ),
                FileClassification(
                    file_path="src/utils.py",
                    is_relevant=True,
                    relevant_line_ranges=[],
                    reason="Helper function used by feature X",
                ),
                FileClassification(
                    file_path=".github/workflows/ci.yml",
                    is_relevant=False,
                    relevant_line_ranges=[],
                    reason="CI config unrelated to feature X",
                ),
            ],
            feature_description="new feature X",
        )

        with patch.object(
            change_filter.llm, "generate_structured", return_value=mock_result
        ):
            diff = """diff --git a/src/main.py b/src/main.py
index abc..def 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ class App:
     def __init__(self):
+    def new_feature(self):
+        return True
"""
            summary = self._make_change_summary()
            result = change_filter.filter_changes(summary, diff)

        # CI file should be filtered out
        assert len(result.files_changed) == 2
        assert result.is_filtered is True
        assert result.feature_description == "new feature X"
        file_paths = [f.path for f in result.files_changed]
        assert "src/main.py" in file_paths
        assert "src/utils.py" in file_paths
        assert ".github/workflows/ci.yml" not in file_paths

        # Check relevant_line_ranges
        main_file = next(f for f in result.files_changed if f.path == "src/main.py")
        assert main_file.relevant_line_ranges == [(10, 20)]

    def test_filter_changes_llm_failure_returns_original(self):
        """If LLM classification fails, returns original summary."""
        config = self._make_config()
        change_filter = ChangeFilter(config=config, feature_description="test feature")

        with patch.object(
            change_filter.llm,
            "generate_structured",
            side_effect=Exception("LLM error"),
        ):
            diff = """diff --git a/src/main.py b/src/main.py
index abc..def 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ class App:
     def __init__(self):
+    def new_feature(self):
+        return True
"""
            summary = self._make_change_summary()
            result = change_filter.filter_changes(summary, diff)

        # Should return original on failure
        assert len(result.files_changed) == 3
        assert result.is_filtered is False

    def test_filter_preserves_non_classified_files(self):
        """Files not in classification (e.g., binary) are kept."""
        config = self._make_config()
        change_filter = ChangeFilter(config=config, feature_description="test feature")

        files = [
            FileChange(
                path="src/main.py",
                change_type="modified",
                lines_added=10,
                lines_deleted=5,
                summary="Added new feature",
            ),
            FileChange(
                path="assets/image.png",
                change_type="added",
                lines_added=0,
                lines_deleted=0,
                summary="Binary file",
            ),
        ]

        mock_result = ChangeFilterResult(
            classifications=[
                FileClassification(
                    file_path="src/main.py",
                    is_relevant=True,
                    relevant_line_ranges=[],
                    reason="Directly implements feature",
                ),
                # Note: no classification for assets/image.png
            ],
            feature_description="test feature",
        )

        with patch.object(
            change_filter.llm, "generate_structured", return_value=mock_result
        ):
            diff = """diff --git a/src/main.py b/src/main.py
index abc..def 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ class App:
+    def new_feature(self):
+        return True
"""
            summary = self._make_change_summary(files=files)
            result = change_filter.filter_changes(summary, diff)

        # Binary file should be kept (not classified)
        assert len(result.files_changed) == 2
        file_paths = [f.path for f in result.files_changed]
        assert "assets/image.png" in file_paths


# ============================================================
# Schema Tests
# ============================================================


class TestChangeSummarySchema:
    """Test ChangeSummary schema with new fields."""

    def test_default_values(self):
        """Test default values for new fields."""
        cs = ChangeSummary(
            change_type=ChangeType.FEATURE,
            description="test",
            intent="test",
            impact="test",
        )
        assert cs.feature_description is None
        assert cs.is_filtered is False

    def test_with_feature_description(self):
        """Test setting feature_description."""
        cs = ChangeSummary(
            change_type=ChangeType.FEATURE,
            description="test",
            intent="test",
            impact="test",
            feature_description="my feature",
            is_filtered=True,
        )
        assert cs.feature_description == "my feature"
        assert cs.is_filtered is True

    def test_serialization_roundtrip(self):
        """Test JSON serialization roundtrip with new fields."""
        cs = ChangeSummary(
            commit_hash="abc123",
            commit_range="abc..def",
            change_type=ChangeType.FEATURE,
            description="test",
            intent="test",
            impact="test",
            feature_description="my feature",
            is_filtered=True,
            files_changed=[
                FileChange(
                    path="src/main.py",
                    change_type="modified",
                    lines_added=10,
                    lines_deleted=5,
                    summary="test",
                    relevant_line_ranges=[(10, 20), (30, 40)],
                ),
            ],
        )
        # Serialize
        data = cs.model_dump()
        json_str = json.dumps(data)

        # Deserialize
        data2 = json.loads(json_str)
        cs2 = ChangeSummary(**data2)

        assert cs2.feature_description == "my feature"
        assert cs2.is_filtered is True
        assert cs2.files_changed[0].relevant_line_ranges == [(10, 20), (30, 40)]


class TestFileChangeSchema:
    """Test FileChange schema with relevant_line_ranges."""

    def test_default_relevant_line_ranges(self):
        """Test default value is None."""
        fc = FileChange(
            path="test.py",
            change_type="modified",
            summary="test",
        )
        assert fc.relevant_line_ranges is None

    def test_with_relevant_line_ranges(self):
        """Test setting relevant_line_ranges."""
        fc = FileChange(
            path="test.py",
            change_type="modified",
            summary="test",
            relevant_line_ranges=[(1, 10), (20, 30)],
        )
        assert fc.relevant_line_ranges == [(1, 10), (20, 30)]

    def test_empty_relevant_line_ranges(self):
        """Test empty list means entire file is relevant."""
        fc = FileChange(
            path="test.py",
            change_type="modified",
            summary="test",
            relevant_line_ranges=[],
        )
        assert fc.relevant_line_ranges == []
