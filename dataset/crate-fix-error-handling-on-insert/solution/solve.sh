#!/bin/bash
# Oracle: apply the real human backport (golden.patch = diff backport^..backport)
# to a fresh worktree at target, exactly where Amalgamator would build its own.
set -e

case_file="/workspace/case.yaml"
source_path=$(yq -r '.repository.source_path' "$case_file")
workdir=$(yq -r '.repository.workdir' "$case_file")
issue_id=$(yq -r '.issue_id' "$case_file")
target_branch=$(yq -r '.branches.target' "$case_file")

sanitized_target=$(echo "$target_branch" | sed -e 's#^origin/##' -e 's#/#_#g')
repo_dir="$workdir/${issue_id}_${sanitized_target}"

mkdir -p "$workdir"
cd "$source_path"
git worktree add -b "amalgamator-oracle-${sanitized_target}" "$repo_dir" "$target_branch"

cd "$repo_dir"
git apply /solution/golden.patch
git add -A
git commit -q -m "Oracle: human backport ee82e9c6"
