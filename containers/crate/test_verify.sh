#!/bin/bash
# test_verify.sh — Apply a backport diff to crate/crate and verify via unit tests.
#
# Usage:
#   ./test_verify.sh <repo_path> <diff_path> <result_json_path>
#
# Exits 0 (PASS) if unit tests pass after applying the diff.
# Exits 1 (FAIL) if tests fail or diff doesn't apply cleanly.

set -e

REPO_PATH="${1:?Usage: $0 <repo_path> <diff_path> <result_json_path>}"
DIFF_PATH="${2:?}"
RESULT_PATH="${3:?}"

IMAGE="crate-backport-test:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_TIME=$(date +%s)

echo "=== crate/crate backport test_verify ==="
echo "Repo:   $REPO_PATH"
echo "Diff:   $DIFF_PATH"
echo "Result: $RESULT_PATH"
echo ""

write_result() {
    local RESULT="$1"
    local REASON="$2"
    local END_TIME=$(date +%s)
    mkdir -p "$(dirname "$RESULT_PATH")"
    cat > "$RESULT_PATH" <<EOF
{
  "result": "$RESULT",
  "reason": "$REASON",
  "test_command": "./mvnw test -DskipBlackboxTests=true",
  "duration_s": $((END_TIME - START_TIME)),
  "diff_path": "$DIFF_PATH"
}
EOF
    echo "$RESULT: $REASON"
}

# Build image
echo "=== Building container image ==="
podman build -t "$IMAGE" "$SCRIPT_DIR" -q

# Step 1: Check diff applies
echo "=== Checking if diff applies cleanly ==="
if ! git -C "$REPO_PATH" apply --check "$DIFF_PATH" 2>&1; then
    write_result "FAIL" "diff_does_not_apply"
    exit 1
fi

# Step 2: Apply diff
git -C "$REPO_PATH" apply "$DIFF_PATH"
echo "Diff applied."

# Step 3: Run unit tests in container
echo ""
echo "=== Running unit tests in Podman ==="
TEST_EXIT=0
podman run --rm \
    -v "$REPO_PATH":/workspace:z \
    -v crate-maven-cache:/root/.m2:z \
    -w /workspace \
    "$IMAGE" 2>&1 || TEST_EXIT=$?

# Step 4: Write result
if [ "$TEST_EXIT" -eq 0 ]; then
    write_result "PASS" "tests_passed"
else
    write_result "FAIL" "tests_failed"
fi

# Step 5: Reset repo
git -C "$REPO_PATH" checkout -- .

exit $TEST_EXIT
