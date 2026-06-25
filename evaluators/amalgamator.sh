#!/bin/bash
# amalgamator.sh — Amalgamator pipeline backport evaluator.
#
# Runs the full auto_bug_fix pipeline (triage, cherry-pick, conflict resolution,
# build-test-fix loop) and extracts the generated diff.
#
# Required env vars:
#   REPO_PATH       — path to the local git clone
#   ORIG_SHA        — original fix commit SHA
#   TARGET_BRANCH   — target branch name
#   TARGET_SHA      — BACKPORT_SHA~1 (used to create the target branch)
#   OUTPUT_DIFF     — where to write the generated diff
#   AMALGAMATOR_DIR — path to the amalgamator repo
#   RUN_KEY         — unique key for this run (e.g. orig_sha-backport_sha)

set -e

: "${REPO_PATH:?REPO_PATH not set}"
: "${ORIG_SHA:?ORIG_SHA not set}"
: "${TARGET_SHA:?TARGET_SHA not set}"
: "${TARGET_BRANCH:?TARGET_BRANCH not set}"
: "${OUTPUT_DIFF:?OUTPUT_DIFF not set}"
: "${RUN_KEY:?RUN_KEY not set}"
: "${AMALGAMATOR_DIR:=/amalgamator}"

WORKDIR="/tmp/amalgamator-workdir/${RUN_KEY}"
CONFIG_FILE="/tmp/${RUN_KEY}-pipeline-config.yaml"
TEMP_BRANCH="eval-target-${RUN_KEY:0:12}"

echo "=== Amalgamator Pipeline Evaluator ==="
echo "Repo:          $REPO_PATH"
echo "Orig SHA:      $ORIG_SHA"
echo "Target Branch: $TARGET_BRANCH"
echo "Output:        $OUTPUT_DIFF"
echo ""

# Create the target branch at BACKPORT_SHA~1
git -C "$REPO_PATH" branch -D "$TEMP_BRANCH" 2>/dev/null || true
git -C "$REPO_PATH" branch "$TEMP_BRANCH" "$TARGET_SHA"

# Write pipeline config
cat > "$CONFIG_FILE" <<EOF
issue_id: "${RUN_KEY}"
bug_description: "Benchmark: backport ${ORIG_SHA:0:12} to ${TARGET_BRANCH}"
repository:
  source_path: "${REPO_PATH}"
  workdir: "${WORKDIR}"
branches:
  source: "origin/${TARGET_BRANCH}"
  target: "${TEMP_BRANCH}"
fix:
  commit: "${ORIG_SHA}"
build:
  command: ""
  test_command: ""
model: "claude-opus-4-6"
advanced:
  max_resolution_retries: 2
  max_build_test_retries: 2
EOF

# Run the pipeline
cd "$AMALGAMATOR_DIR"
uv run python -m auto_bug_fix.run_bug_fix "$CONFIG_FILE"

# Extract the generated diff from the pipeline worktree
WORKTREE="${WORKDIR}/${RUN_KEY}"
if [ -d "$WORKTREE" ]; then
    git -C "$WORKTREE" diff HEAD~1 HEAD > "$OUTPUT_DIFF"
    echo "Pipeline diff written to $OUTPUT_DIFF ($(wc -l < "$OUTPUT_DIFF") lines)"
else
    echo "ERROR: pipeline worktree not found at $WORKTREE"
    exit 1
fi

# Cleanup
git -C "$REPO_PATH" branch -D "$TEMP_BRANCH" 2>/dev/null || true
