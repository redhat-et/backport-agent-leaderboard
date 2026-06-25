#!/bin/bash
# run_eval.sh — Main orchestrator for backport evaluation.
#
# For each case in backports.csv (filtered by REPO):
#   1. Runs Raw Claude evaluator → generates diff
#   2. Runs Amalgamator evaluator → generates diff
#   3. Runs test_verify.sh for each diff inside Podman
#   4. Saves result JSON to results/<repo>/
#
# Usage:
#   ./run_eval.sh [--repo cri-o/cri-o] [--limit 3] [--evaluator raw_claude|amalgamator|both]
#
# Env vars:
#   AMALGAMATOR_DIR   — path to amalgamator repo (default: ../amalgamator)
#   REPOS_DIR         — path to cloned project repos (default: ../benchmark-repos)
#   RESULTS_DIR       — where to write results (default: ./results)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AMALGAMATOR_DIR="${AMALGAMATOR_DIR:-$(dirname "$SCRIPT_DIR")/amalgamator}"
REPOS_DIR="${REPOS_DIR:-$(dirname "$SCRIPT_DIR")/benchmark-repos}"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"
EVALUATOR="both"
REPO_FILTER=""
LIMIT=999

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo)        REPO_FILTER="$2";  shift 2 ;;
        --limit)       LIMIT="$2";        shift 2 ;;
        --evaluator)   EVALUATOR="$2";    shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo " Backport Agent Leaderboard — Evaluation"
echo "=========================================="
echo "Repo filter:  ${REPO_FILTER:-all}"
echo "Evaluator:    $EVALUATOR"
echo "Limit:        $LIMIT"
echo "Results dir:  $RESULTS_DIR"
echo ""

COUNT=0

# Read backports.csv, skip header
tail -n +2 "$SCRIPT_DIR/backports.csv" | while IFS=',' read -r REPO ORIG_SHA BACKPORT_SHA CLASSIFICATION REASON; do

    # Apply repo filter
    if [ -n "$REPO_FILTER" ] && [ "$REPO" != "$REPO_FILTER" ]; then
        continue
    fi

    COUNT=$((COUNT + 1))
    [ "$COUNT" -gt "$LIMIT" ] && break

    # Derive short names and paths
    REPO_NAME=$(basename "$REPO")
    RUN_KEY="${ORIG_SHA:0:12}-${BACKPORT_SHA:0:12}"
    REPO_PATH="$REPOS_DIR/$REPO_NAME"
    TARGET_SHA=$(git -C "$REPO_PATH" rev-parse "${BACKPORT_SHA}~1" 2>/dev/null || echo "")
    RESULT_DIR="$RESULTS_DIR/$REPO_NAME/$RUN_KEY"
    mkdir -p "$RESULT_DIR"

    echo "------------------------------------------"
    echo "Case $COUNT: $REPO | $CLASSIFICATION"
    echo "  orig=$ORIG_SHA | backport=$BACKPORT_SHA"
    echo ""

    if [ -z "$TARGET_SHA" ]; then
        echo "  SKIP: could not resolve BACKPORT_SHA~1"
        continue
    fi

    # Determine target branch from git
    TARGET_BRANCH=$(git -C "$REPO_PATH" branch -r --contains "$BACKPORT_SHA" | grep -v HEAD | head -1 | sed 's|origin/||' | xargs)

    run_evaluator() {
        local EVAL_NAME="$1"
        local OUTPUT_DIFF="$RESULT_DIR/${EVAL_NAME}.diff"
        local TEST_RESULT="$RESULT_DIR/${EVAL_NAME}_test.json"

        echo "  ▶ Evaluator: $EVAL_NAME"

        # Skip if already done
        if [ -f "$TEST_RESULT" ]; then
            echo "    Already done — skipping"
            return
        fi

        # Generate diff
        REPO_PATH="$REPO_PATH" \
        ORIG_SHA="$ORIG_SHA" \
        TARGET_SHA="$TARGET_SHA" \
        TARGET_BRANCH="$TARGET_BRANCH" \
        OUTPUT_DIFF="$OUTPUT_DIFF" \
        RUN_KEY="$RUN_KEY" \
        AMALGAMATOR_DIR="$AMALGAMATOR_DIR" \
        "$SCRIPT_DIR/evaluators/${EVAL_NAME}.sh" 2>&1 | tee "$RESULT_DIR/${EVAL_NAME}_generate.log"

        if [ ! -f "$OUTPUT_DIFF" ] || [ ! -s "$OUTPUT_DIFF" ]; then
            echo "    FAIL: no diff generated"
            echo '{"result":"ERROR","reason":"no_diff_generated"}' > "$TEST_RESULT"
            return
        fi

        # Run test verification in Podman
        "$SCRIPT_DIR/containers/$REPO_NAME/test_verify.sh" \
            "$REPO_PATH" \
            "$OUTPUT_DIFF" \
            "$TEST_RESULT" 2>&1 | tee "$RESULT_DIR/${EVAL_NAME}_test.log"

        RESULT=$(python3 -c "import json; print(json.load(open('$TEST_RESULT'))['result'])" 2>/dev/null || echo "UNKNOWN")
        echo "    Result: $RESULT"
    }

    # Run selected evaluators
    if [ "$EVALUATOR" = "raw_claude" ] || [ "$EVALUATOR" = "both" ]; then
        run_evaluator "raw_claude"
    fi
    if [ "$EVALUATOR" = "amalgamator" ] || [ "$EVALUATOR" = "both" ]; then
        run_evaluator "amalgamator"
    fi

done

echo ""
echo "=========================================="
echo " Evaluation complete. Results in: $RESULTS_DIR"
echo "=========================================="

# Print summary
python3 - <<'PYEOF'
import json, os, glob, sys

results_dir = os.environ.get("RESULTS_DIR", "results")
rows = []
for f in glob.glob(f"{results_dir}/**/*_test.json", recursive=True):
    try:
        d = json.load(open(f))
        parts = f.split("/")
        evaluator = parts[-1].replace("_test.json", "")
        rows.append({"evaluator": evaluator, "result": d.get("result", "?"), "file": f})
    except: pass

if not rows:
    print("No results found.")
    sys.exit(0)

from collections import Counter
for ev in sorted(set(r["evaluator"] for r in rows)):
    ev_rows = [r for r in rows if r["evaluator"] == ev]
    counts = Counter(r["result"] for r in ev_rows)
    total = len(ev_rows)
    passed = counts.get("PASS", 0)
    print(f"  {ev}: {passed}/{total} PASS ({100*passed//total if total else 0}%)")
PYEOF
