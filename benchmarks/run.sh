#!/usr/bin/env bash
#
# run.sh — Run GGDes benchmarks.
#
# Usage:
#   ./run.sh                          # Run all benchmarks sequentially
#   ./run.sh <benchmark-id>           # Run a single benchmark
#   ./run.sh --list                   # List available benchmarks
#   ./run.sh --dry-run [<id>]         # Print commands without executing
#
# Before running:
#   1. ./setup.sh has cloned repos
#   2. LLM provider is configured in ggdes.yaml
#
# Results: results/results.csv

set -euo pipefail
cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$SCRIPT_DIR/results"
GGDES="${GGDES:-uv run python main.py}"

# Project venv Python (has yaml)
PYTHON="${GGDES_PYTHON:-$(cd "$SCRIPT_DIR/.." && uv run python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo python3)}"

mkdir -p "$RESULTS_DIR"

list_benchmarks() {
  $PYTHON -c "
import yaml, json, sys
with open('$SCRIPT_DIR/benchmarks.yaml') as f:
    data = yaml.safe_load(f)
for b in data['benchmarks']:
    print(f\"{b['id']}|{b['type']}|{b['base_tag']}|{b['head_tag']}|{b['name']}\")
"
}

# ── Run one benchmark ──
run_one() {
  local id="$1"

  # Load all benchmark fields via Python -> bash eval
  eval "$($PYTHON -c "
import yaml, json, sys

with open('$SCRIPT_DIR/benchmarks.yaml') as f:
    data = yaml.safe_load(f)

for b in data['benchmarks']:
    if b['id'] == '$id':
        g = b.get('ggdes', {})
        print(f'REPO_DIR={json.dumps(b[\"dir\"], ensure_ascii=False)}')
        print(f'BASE_TAG={json.dumps(b[\"base_tag\"], ensure_ascii=False)}')
        print(f'HEAD_TAG={json.dumps(b[\"head_tag\"], ensure_ascii=False)}')
        print(f'BTYPE={json.dumps(b[\"type\"], ensure_ascii=False)}')
        print(f'BNAME={json.dumps(b[\"name\"], ensure_ascii=False)}')
        print(f'FEATURE={json.dumps(g.get(\"feature\", b[\"name\"]), ensure_ascii=False)}')
        print(f'FORMATS={json.dumps(g.get(\"formats\", \"markdown\"), ensure_ascii=False)}')
        print(f'STORAGE={json.dumps(g.get(\"storage\", \"summary\"), ensure_ascii=False)}')
        print(f'SEMANTIC_DIFF={json.dumps(str(g.get(\"semantic_diff\", True)).lower(), ensure_ascii=False)}')
        print(f'AUTO={json.dumps(str(g.get(\"auto\", True)).lower(), ensure_ascii=False)}')
        print(f'LLM_PROVIDER={json.dumps(g.get("provider", ""), ensure_ascii=False)}')
        print(f'LLM_MODEL={json.dumps(g.get("model_name", ""), ensure_ascii=False)}')
        print(f'LLM_API_KEY={json.dumps(g.get("api_key", ""), ensure_ascii=False)}')
        print(f'LLM_BASE_URL={json.dumps(g.get("base_url", ""), ensure_ascii=False)}')
        print(f'CONTEXT_FILE={json.dumps(g.get("context_file", ""), ensure_ascii=False)}')
        focus = g.get("focus_commits", [])
        print(f'FOCUS_COMMITS={json.dumps(\",\".join(focus) if focus else \"\", ensure_ascii=False)}')
        sys.exit(0)

print(f'Unknown benchmark: $id', file=sys.stderr)
sys.exit(1)
")"

  local repo_path="$SCRIPT_DIR/repos/$REPO_DIR"
  local commits="${BASE_TAG}..${HEAD_TAG}"

  if [ ! -d "$repo_path/.git" ]; then
    echo "  [SKIP] $id — repo not cloned. Run ./setup.sh first."
    return 1
  fi

  local start_time end_time elapsed status
  start_time=$(date +%s)

  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo "  Benchmark : $id"
  echo "  Name      : $BNAME"
  echo "  Type      : $BTYPE"
  echo "  Repo      : $repo_path"
  echo "  Commits   : $commits"
  echo "  Formats   : $FORMATS"
  echo "  Storage   : $STORAGE"
  echo "  Semantic  : $SEMANTIC_DIFF"
  if [ -n "$LLM_PROVIDER" ]; then echo "  LLM       : $LLM_PROVIDER/$LLM_MODEL"; fi
  if [ -n "$FOCUS_COMMITS" ]; then echo "  Focus     : $FOCUS_COMMITS"; fi
  if [ -n "$CONTEXT_FILE" ]; then echo "  Context   : $SCRIPT_DIR/$CONTEXT_FILE"; fi
  echo "───────────────────────────────────────────────────────────────"
  echo "  $FEATURE"
  echo "═══════════════════════════════════════════════════════════════"

  set +e
  if [ "${DRY_RUN:-}" = "true" ]; then
    echo ""
    echo "  # Dry-run — would execute from $PROJECT_ROOT:"
    echo "  $GGDES analyze \\"
    echo "    --feature \"$FEATURE\" \\"
    echo "    --commits \"$commits\" \\"
    echo "    --repo \"$repo_path\" \\"
    echo "    --formats \"$FORMATS\" \\"
    echo "    --storage \"$STORAGE\" \\"
    if [ -n "$LLM_PROVIDER" ]; then echo "    --provider \"$LLM_PROVIDER\" \\"; fi
    if [ -n "$LLM_MODEL" ]; then echo "    --model \"$LLM_MODEL\" \\"; fi
    if [ -n "$FOCUS_COMMITS" ]; then echo "    --focus \"$FOCUS_COMMITS\" \\"; fi
    if [ -n "$CONTEXT_FILE" ]; then echo "    --context-file \"$SCRIPT_DIR/$CONTEXT_FILE\" \\"; fi
    echo "    --auto"
    if [ "$SEMANTIC_DIFF" = "true" ]; then
      echo "    --semantic-diff"
    fi
    status=0
  else
    # Build args array safely
    args=(
      --feature "$FEATURE"
      --commits "$commits"
      --repo "$repo_path"
      --formats "$FORMATS"
      --storage "$STORAGE"
    )
    if [ "$AUTO" = "true" ]; then
      args+=(--auto)
    fi
    if [ "$SEMANTIC_DIFF" = "false" ]; then
      args+=(--no-semantic-diff)
    fi
    if [ -n "$LLM_PROVIDER" ]; then
      args+=(--provider "$LLM_PROVIDER")
    fi
    if [ -n "$LLM_MODEL" ]; then
      args+=(--model "$LLM_MODEL")
    fi
    if [ -n "$LLM_API_KEY" ]; then
      args+=(--api-key "$LLM_API_KEY")
    fi
    if [ -n "$CONTEXT_FILE" ]; then
      args+=(--context-file "$SCRIPT_DIR/$CONTEXT_FILE")
    fi
    if [ -n "$FOCUS_COMMITS" ]; then
      args+=(--focus "$FOCUS_COMMITS")
    fi

    (cd "$PROJECT_ROOT" && $GGDES analyze "${args[@]}")
    status=$?
  fi
  set -e

  end_time=$(date +%s)
  elapsed=$((end_time - start_time))

  # Append result
  if [ ! -f "$RESULTS_DIR/results.csv" ]; then
    echo "id,type,commits,status,duration_sec,feature,formats,storage,semantic_diff" > "$RESULTS_DIR/results.csv"
  fi
  echo "$id,$BTYPE,$commits,$status,$elapsed,$FEATURE,$FORMATS,$STORAGE,$SEMANTIC_DIFF" >> "$RESULTS_DIR/results.csv"

  if [ $status -eq 0 ]; then
    echo "  ✅ $id completed in ${elapsed}s"
  else
    echo "  ❌ $id failed (exit $status) after ${elapsed}s"
  fi
}

# ── Main ──
case "${1:-}" in
  --list)
    echo ""
    printf "  %-35s %-20s %s\n" "ID" "TYPE" "RANGE"
    printf "  %-35s %-20s %s\n" "--" "----" "-----"
    list_benchmarks | while IFS='|' read -r id btype base head name; do
      printf "  %-35s %-20s %s → %s  %s\n" "$id" "$btype" "$base" "$head" "$name"
    done
    exit 0
    ;;
  --dry-run)
    DRY_RUN=true
    if [ -n "${2:-}" ]; then
      run_one "$2"
    else
      list_benchmarks | while IFS='|' read -r id _; do
        DRY_RUN=true run_one "$id"
      done
    fi
    ;;
  -h|--help)
    echo "Usage: $0 [--list] [--dry-run [<id>]] [<benchmark-id>]"
    exit 0
    ;;
  "")
    list_benchmarks | while IFS='|' read -r id _; do
      run_one "$id"
    done
    ;;
  *)
    run_one "$1"
    ;;
esac

echo ""
echo "=== Done ==="
echo "Results: $RESULTS_DIR/results.csv"
