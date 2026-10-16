#!/bin/bash
# Golden solution: build the same git worktree Amalgamator itself would
# build, then cherry-pick the known fix commit onto it. This is what
# tests/test.sh verifies. Per run_bug_fix.py:
#   worktree_path = os.path.join(workdir, f"{issue_id}_{sanitized_target}")
# where sanitized_target strips an "origin/" prefix and replaces "/" with
# "_" (config_loader.py's _sanitize_ref). Must match tests/test.sh exactly.
set -e

case_file="/workspace/case.yaml"
source_path=$(yq -r '.repository.source_path' "$case_file")
workdir=$(yq -r '.repository.workdir' "$case_file")
issue_id=$(yq -r '.issue_id' "$case_file")
target_branch=$(yq -r '.branches.target' "$case_file")
fix_commit=$(yq -r '.fix.commit' "$case_file")

sanitized_target=$(echo "$target_branch" | sed -e 's#^origin/##' -e 's#/#_#g')
repo_dir="$workdir/${issue_id}_${sanitized_target}"
local_branch="amalgamator-oracle-${sanitized_target}"

mkdir -p "$workdir"
cd "$source_path"
git worktree add -b "$local_branch" "$repo_dir" "$target_branch"

cd "$repo_dir"
git cherry-pick "$fix_commit"
