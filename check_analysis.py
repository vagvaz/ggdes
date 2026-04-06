#!/usr/bin/env python3
"""Diagnostic script to check analysis state and identify issues."""

import json
import os
import sys
from pathlib import Path


def check_analysis(analysis_id: str, kb_base: str = None):
    """Check the state of an analysis."""
    # Try multiple locations
    possible_paths = [
        Path(kb_base).expanduser() if kb_base else None,
        Path(".ggdes-local/kb"),  # Current directory
        Path.home() / ".ggdes-local/kb",  # Home directory
    ]

    kb_path = None
    for base in possible_paths:
        if base is None:
            continue
        test_path = base / "analyses" / analysis_id
        if test_path.exists():
            kb_path = test_path
            break

    if kb_path is None:
        # Try to find it
        print(f"🔍 Searching for analysis: {analysis_id}")
        search_paths = [
            Path("."),
            Path.home(),
        ]
        for search_root in search_paths:
            if not search_root.exists():
                continue
            for root, dirs, files in os.walk(search_root):
                if analysis_id in dirs:
                    kb_path = Path(root) / analysis_id
                    print(f"   Found at: {kb_path}")
                    break
            if kb_path:
                break

    if not kb_path or not kb_path.exists():
        print(f"❌ Analysis not found: {analysis_id}")
        print(f"   Searched in common locations")
        return

    print(f"🔍 Checking analysis: {analysis_id}")
    print(f"📁 KB Path: {kb_path}")
    print()

    # Check metadata
    metadata_file = kb_path / "metadata.yaml"
    if metadata_file.exists():
        print(f"✅ metadata.yaml exists")
        import yaml

        metadata = yaml.safe_load(metadata_file.read_text())
        print(f"   Name: {metadata.get('name', 'N/A')}")
        print(f"   Repo: {metadata.get('repo_path', 'N/A')}")
        print(f"   Commits: {metadata.get('commit_range', 'N/A')}")
        print(f"   Formats: {metadata.get('target_formats', 'N/A')}")
        print()

        # Check stages
        stages = metadata.get("stages", {})
        print(f"📊 Stages ({len(stages)} total):")
        for stage_name, stage_info in stages.items():
            status = stage_info.get("status", "unknown")
            icon = (
                "✅" if status == "completed" else "❌" if status == "failed" else "⏳"
            )
            print(f"   {icon} {stage_name}: {status}")
            if status == "failed" and stage_info.get("error_message"):
                print(f"      Error: {stage_info.get('error_message')}")
        print()
    else:
        print(f"❌ metadata.yaml not found")
        return

    # Check git analysis
    git_analysis = kb_path / "git_analysis" / "summary.json"
    if git_analysis.exists():
        print(f"✅ git_analysis/summary.json exists")
        data = json.loads(git_analysis.read_text())
        print(f"   Files changed: {len(data.get('files_changed', []))}")
        print(f"   Change type: {data.get('change_type', 'N/A')}")
        print()
    else:
        print(f"❌ git_analysis/summary.json not found")

    # Check AST data
    ast_base = kb_path / "ast_base"
    ast_head = kb_path / "ast_head"
    if ast_base.exists():
        files = list(ast_base.glob("*.json"))
        print(f"✅ ast_base/ exists with {len(files)} parsed files")
    else:
        print(f"❌ ast_base/ not found")

    if ast_head.exists():
        files = list(ast_head.glob("*.json"))
        print(f"✅ ast_head/ exists with {len(files)} parsed files")
    else:
        print(f"❌ ast_head/ not found")
    print()

    # Check technical facts
    facts_file = kb_path / "technical_facts" / "facts.json"
    if facts_file.exists():
        print(f"✅ technical_facts/facts.json exists")
        data = json.loads(facts_file.read_text())
        print(f"   Facts count: {len(data)}")
        if data:
            categories = set(f.get("category", "unknown") for f in data)
            print(f"   Categories: {', '.join(categories)}")
        print()
    else:
        print(f"❌ technical_facts/facts.json not found")
        print()

    # Check plans
    plans_dir = kb_path / "plans"
    if plans_dir.exists():
        plans = list(plans_dir.glob("plan_*.json"))
        print(f"✅ plans/ exists with {len(plans)} plans:")
        for plan in plans:
            print(f"   - {plan.name}")

        index = plans_dir / "index.json"
        if index.exists():
            data = json.loads(index.read_text())
            print(
                f"   Available formats: {', '.join(data.get('available_formats', []))}"
            )
        print()
    else:
        print(f"❌ plans/ directory not found")
        print()

    # Check worktrees
    wt_base = Path("~/.ggdes-local/worktrees").expanduser() / analysis_id
    if wt_base.exists():
        base_wt = wt_base / "base"
        head_wt = wt_base / "head"
        print(f"✅ Worktrees exist:")
        if base_wt.exists():
            items = len(list(base_wt.iterdir())) if base_wt.is_dir() else 0
            print(f"   - base: {items} items")
        else:
            print(f"   ❌ base worktree missing")
        if head_wt.exists():
            items = len(list(head_wt.iterdir())) if head_wt.is_dir() else 0
            print(f"   - head: {items} items")
        else:
            print(f"   ❌ head worktree missing")
    else:
        print(f"❌ Worktrees not found at {wt_base}")

    print()
    print("📋 Summary:")
    print("   Run 'ggdes resume {analysis_id} --retry-failed' to retry failed stages")
    print(f"   Log file: {kb_path / 'analysis.log'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_analysis.py <analysis_id>")
        print("Example: python check_analysis.py flat_vec-20260406-010116-8b71bfc8")
        sys.exit(1)

    analysis_id = sys.argv[1]
    check_analysis(analysis_id)
