#!/bin/bash
# raw_claude.sh — Single-shot Claude backport evaluator.
#
# Generates a backport diff using a single Claude API call (no pipeline, no iteration).
#
# Required env vars (set by run_eval.sh or OpenShift Job):
#   REPO_PATH       — path to the local git clone
#   ORIG_SHA        — original fix commit SHA
#   TARGET_SHA      — BACKPORT_SHA~1 (pre-fix state on target branch)
#   TARGET_BRANCH   — target branch name (e.g. "release-1.33")
#   OUTPUT_DIFF     — where to write the generated diff
#   AMALGAMATOR_DIR — path to the amalgamator repo (contains generic_claude_backport.py)
#
# Exits 0 on success, 1 on failure.

set -e

: "${REPO_PATH:?REPO_PATH not set}"
: "${ORIG_SHA:?ORIG_SHA not set}"
: "${TARGET_SHA:?TARGET_SHA not set}"
: "${TARGET_BRANCH:?TARGET_BRANCH not set}"
: "${OUTPUT_DIFF:?OUTPUT_DIFF not set}"
: "${AMALGAMATOR_DIR:=/amalgamator}"

echo "=== Raw Claude Evaluator ==="
echo "Repo:          $REPO_PATH"
echo "Orig SHA:      $ORIG_SHA"
echo "Target SHA:    $TARGET_SHA"
echo "Target Branch: $TARGET_BRANCH"
echo "Output:        $OUTPUT_DIFF"
echo ""

cd "$AMALGAMATOR_DIR"

uv run python -m benchmark.generic_claude_backport \
    --repo          "$REPO_PATH" \
    --orig          "$ORIG_SHA" \
    --target-sha    "$TARGET_SHA" \
    --target-branch "$TARGET_BRANCH" \
    --model         "claude-opus-4-6" \
    --out           "$OUTPUT_DIFF"

echo "Raw Claude diff written to $OUTPUT_DIFF"
