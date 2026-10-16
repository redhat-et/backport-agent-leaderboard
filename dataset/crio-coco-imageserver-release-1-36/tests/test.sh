#!/bin/bash
# Independent verifier. Two possible inputs:
#
# 1. oracle: solve.sh left a worktree with golden.patch applied at
#    $workdir/${issue_id}_${sanitized_target}. Test that directly.
#
# 2. amalgamator agent: apply its candidate.patch to a fresh worktree at the
#    target branch, then build + test.
#
# Gate (design note -- this is a FEATURE backport whose API shape is part of
# the adaptation, so no API-independent injected test exists):
#   a) the PR's two new unit-test files must be present (tests were ported)
#   b) FULL-tree build must pass (API changes must be consistent everywhere)
#   c) FULL short unit-test suite must pass (agent's adaptation is
#      self-consistent: ported tests green against ported code)
set -u

case_file="/workspace/case.yaml"
command=$(yq -r '.build.command // ""' "$case_file")
test_command=$(yq -r '.build.test_command // ""' "$case_file")
source_path=$(yq -r '.repository.source_path' "$case_file")
workdir=$(yq -r '.repository.workdir' "$case_file")
issue_id=$(yq -r '.issue_id' "$case_file")
target_branch=$(yq -r '.branches.target' "$case_file")
sanitized_target=$(echo "$target_branch" | sed -e 's#^origin/##' -e 's#/#_#g')

amalgamator_dir="/workspace/amalgamator"

reward=0
mkdir -p /logs/verifier

oracle_worktree="$workdir/${issue_id}_${sanitized_target}"

if [ -e "$oracle_worktree/.git" ]; then
    echo "Found solve.sh worktree at $oracle_worktree -- testing it directly." >&2
    repo_dir="$oracle_worktree"
else
    run_dir=$(find "$amalgamator_dir/runs" -maxdepth 1 -type d -name 'case_*' 2>/dev/null | sort | tail -1)
    if [ -z "$run_dir" ]; then
        echo "No amalgamator run directory under $amalgamator_dir/runs and no solve.sh worktree -- agent likely never ran." >&2
        echo "$reward" > /logs/verifier/reward.txt
        exit 0
    fi

    patch_file="$run_dir/$sanitized_target/candidate.patch"
    if [ ! -f "$patch_file" ]; then
        echo "No candidate.patch found at $patch_file -- agent did not produce a patch." >&2
        echo "$reward" > /logs/verifier/reward.txt
        exit 0
    fi

    repo_dir="$workdir/${issue_id}_verify"
    rm -rf "$repo_dir"
    mkdir -p "$workdir"

    cd "$source_path" || exit 1
    git worktree add -b "amalgamator-verify-${sanitized_target}" "$repo_dir" "$target_branch" || exit 1

    cd "$repo_dir" || exit 1
    if ! git am --3way "$patch_file"; then
        echo "Failed to apply candidate.patch onto a fresh $target_branch worktree." >&2
        git am --abort 2>/dev/null
        echo "$reward" > /logs/verifier/reward.txt
        exit 0
    fi
fi

reward=1
cd "$repo_dir" || exit 1

# (a) Ported unit tests must exist -- the PR adds them; a backport that
# silently drops the tests is incomplete.
for f in internal/storage/image_mgr_test.go internal/storage/runtime_mgr_test.go; do
    if [ ! -f "$f" ]; then
        echo "MISSING required ported test file: $f" >&2
        reward=0
    fi
done

# (b) Full-tree build.
if [ "$reward" -eq 1 ] && [ -n "$command" ]; then
    if ! eval "$command"; then
        reward=0
    fi
fi

# (c) Full short unit-test suite.
if [ "$reward" -eq 1 ] && [ -n "$test_command" ]; then
    if ! eval "$test_command"; then
        reward=0
    fi
fi

echo "$reward" > /logs/verifier/reward.txt
