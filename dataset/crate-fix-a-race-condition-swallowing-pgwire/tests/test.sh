#!/bin/bash
# Independent verifier. Two possible agents produced changes we need to
# test:
#
# 1. oracle (`-a oracle`): runs solution/solve.sh directly, which leaves a
#    worktree checked out (with the fix cherry-picked) at
#    $workdir/${issue_id}_${sanitized_target}. Just build+test that.
#
# 2. amalgamator (the real agent): tears down its own scratch worktree once
#    the pipeline finishes (see run_bug_fix.py's cleanup_worktree()) and
#    only leaves behind a `candidate.patch` (git format-patch) under
#    /workspace/amalgamator/runs/<run>/<sanitized_target>/. We build our OWN
#    fresh worktree at the target branch and apply that patch to it.
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
    # solve.sh already built and cherry-picked into this worktree -- test
    # it directly, no patch application needed.
    echo "Found solve.sh worktree at $oracle_worktree -- testing it directly." >&2
    repo_dir="$oracle_worktree"
else
    # No solve.sh worktree -- look for the real agent's candidate.patch and
    # apply it to a fresh worktree ourselves.
    run_dir=$(find "$amalgamator_dir/runs" -maxdepth 1 -type d -name 'case_*' 2>/dev/null | sort | tail -1)
    if [ -z "$run_dir" ]; then
        echo "No amalgamator run directory found under $amalgamator_dir/runs, and no solve.sh worktree at $oracle_worktree -- agent likely never ran." >&2
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

# Run the build command, if it's not empty. A non-zero exit fails the case.
if [ -n "$command" ]; then
    if ! eval "$command"; then
        reward=0
    fi
fi

# Run the test command, if it's not empty and the build (if any) passed.
if [ "$reward" -eq 1 ] && [ -n "$test_command" ]; then
    if ! eval "$test_command"; then
        reward=0
    fi
fi

echo "$reward" > /logs/verifier/reward.txt
