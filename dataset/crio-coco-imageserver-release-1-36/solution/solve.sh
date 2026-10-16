#!/bin/bash
# Golden solution (oracle). No official human backport of PR #9907 exists on
# release-1.36, so the golden is the previously human-verified amalgamator run
# (see task.toml note). golden.patch is a squashed diff from target -> that
# result; it applies clean to target (verified). It includes the adapted unit
# tests (image_mgr_test.go / runtime_mgr_test.go).
set -e

case_file="/workspace/case.yaml"
source_path=$(yq -r '.repository.source_path' "$case_file")
workdir=$(yq -r '.repository.workdir' "$case_file")
issue_id=$(yq -r '.issue_id' "$case_file")
target_branch=$(yq -r '.branches.target' "$case_file")

sanitized_target=$(echo "$target_branch" | sed -e 's#^origin/##' -e 's#/#_#g')
repo_dir="$workdir/${issue_id}_${sanitized_target}"
local_branch="amalgamator-oracle-${sanitized_target}"

mkdir -p "$workdir"
cd "$source_path"
git worktree add -b "$local_branch" "$repo_dir" "$target_branch"
cd "$repo_dir"

git apply /solution/golden.patch
git add -A
git commit -m "Backport PR #9907 (CoCO image-server support) to release-1.36 [golden]"
