#!/usr/bin/env bash
#
# setup.sh — Clone benchmark repos and checkout their tag pairs.
#
# Usage:
#   ./setup.sh                        # Clone all repos
#   ./setup.sh --shallow              # Shallow clone (faster, no full history)
#   ./setup.sh <id>                   # Clone a single benchmark's repo
#   ./setup.sh --shallow <id>         # Shallow clone a single benchmark
#
# Each repo is cloned into benchmarks/repos/<name>/ and both tags
# are fetched so the commit range is available for analysis.

set -euo pipefail
cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
REPOS_DIR="$SCRIPT_DIR/repos"

# Use project's venv Python (has yaml)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${GGDES_PYTHON:-$(cd "$PROJECT_ROOT" && uv run python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo python3)}"

usage() {
  echo "Usage: $0 [--shallow] [<benchmark-id>]"
  echo ""
  echo "  --shallow   Shallow clone (faster, no full history)"
  echo "  <id>        Only setup the repo for a specific benchmark"
  exit 1
}

SHALLOW=false
TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --shallow) SHALLOW=true; shift ;;
    -h|--help) usage ;;
    *) TARGET="$1"; shift ;;
  esac
done

# ── Parse YAML and output unique repos as JSON ──
parse_repos() {
  $PYTHON -c "
import yaml, json, sys

with open('$SCRIPT_DIR/benchmarks.yaml') as f:
    data = yaml.safe_load(f)

target = '$TARGET'

# Deduplicate by directory — each physical repo cloned once
seen = {}
for b in data['benchmarks']:
    key = b['dir']
    if target and target not in b['id'] and target not in key:
        continue
    if key not in seen:
        seen[key] = {
            'repo': b['repo'],
            'dir': key,
            'base_tag': b['base_tag'],
            'head_tag': b['head_tag'],
        }

if not seen:
    sys.stderr.write('Error: no benchmarks matched')
    sys.exit(1)

print(json.dumps(list(seen.values()), indent=2))
"
}

echo "=== GGDes Benchmark Setup ==="
echo ""

repos_json=$(parse_repos)
echo "$repos_json" | $PYTHON -c "
import json, sys
repos = json.load(sys.stdin)
for r in repos:
    print(f'  {r[\"dir\"]:30s} {r[\"base_tag\"]:20s} \u2192 {r[\"head_tag\"]}')
"
echo ""

# ── Clone / fetch each repo ──
echo "$repos_json" | $PYTHON -c "
import json, subprocess, os, sys

repos = json.load(sys.stdin)
shallow = '${SHALLOW}' == 'true'
repos_dir = '$REPOS_DIR'

for r in repos:
    repo_url = r['repo']
    repo_dir = r['dir']
    base_tag = r['base_tag']
    head_tag = r['head_tag']
    dest = os.path.join(repos_dir, repo_dir)

    print(f'--- {repo_dir} ---')

    if os.path.isdir(os.path.join(dest, '.git')):
        print(f'  Already cloned at {dest}')
        print(f'  Fetching tags...')
        subprocess.run(['git', '-C', dest, 'fetch', '--tags', 'origin'],
                       capture_output=True, check=True)
    else:
        parent = os.path.dirname(dest)
        os.makedirs(parent, exist_ok=True)
        print(f'  Cloning {repo_url} ...')
        cmd = ['git', 'clone']
        if shallow:
            cmd += ['--depth', '1']
        cmd += [repo_url, dest]
        subprocess.run(cmd, check=True)

    # Fetch specific tags if shallow (fix for depth=1 clones)
    if shallow:
        for tag in [base_tag, head_tag]:
            print(f'  Fetching tag {tag}...')
            subprocess.run(
                ['git', '-C', dest, 'fetch', '--depth', '1', 'origin',
                 f'refs/tags/{tag}:refs/tags/{tag}'],
                capture_output=True, check=True,
            )

    # Resolve and display tag SHAs
    for tag in [base_tag, head_tag]:
        sha = subprocess.run(
            ['git', '-C', dest, 'rev-parse', tag],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        print(f'  {tag}: {sha[:12]}')

    print()
"
