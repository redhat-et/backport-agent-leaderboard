import os
import subprocess
from pathlib import Path

import pytest

from backport_bench.git_ops import (
    cleanup,
    clone_or_fetch,
    create_worktree,
    extract_diff,
    find_source_branch,
    setup_target_branch,
)


@pytest.fixture
def local_git_repo(tmp_path):
    """Create a local bare repo with two branches and commits."""
    bare = tmp_path / "bare_repo.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, capture_output=True)

    (work / "file.txt").write_text("initial")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "initial"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )

    (work / "file.txt").write_text("fixed")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "fix: original"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    orig_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    subprocess.run(["git", "-C", str(work), "branch", "release-1.0", "HEAD~1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "release-1.0"], check=True, capture_output=True)

    (work / "file.txt").write_text("fixed")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "fix: backport"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    backport_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    subprocess.run(["git", "-C", str(work), "push", "origin", "--all"], check=True, capture_output=True)

    return {
        "bare": bare,
        "work": work,
        "orig_sha": orig_sha,
        "backport_sha": backport_sha,
    }


class TestCloneOrFetch:
    def test_clones_new_repo(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        assert (project_path / ".git").exists() or (project_path / "HEAD").exists()

    def test_fetch_existing_repo(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        path1 = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        path2 = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        assert path1 == path2


class TestFindSourceBranch:
    def test_finds_main_branch(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        branch = find_source_branch(project_path, local_git_repo["orig_sha"])
        assert branch in ("origin/main", "origin/master", "main", "master")


class TestExtractDiff:
    def test_extracts_diff(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        diff = extract_diff(project_path, local_git_repo["orig_sha"])
        assert "fixed" in diff
        assert "initial" in diff


class TestSetupTargetBranch:
    def test_creates_target_branch(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        setup_target_branch(project_path, local_git_repo["backport_sha"])
        result = subprocess.run(
            ["git", "-C", str(project_path), "branch", "--list", "target"],
            capture_output=True, text=True,
        )
        assert "target" in result.stdout


class TestCreateWorktree:
    def test_creates_worktree_dir(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        setup_target_branch(project_path, local_git_repo["backport_sha"])
        wt_path = project_path / ".worktrees" / "test-run"
        create_worktree(project_path, "target", wt_path)
        assert wt_path.exists()
        assert (wt_path / "file.txt").exists()


class TestCleanup:
    def test_removes_worktree_and_branch(self, local_git_repo, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        project_path = clone_or_fetch(str(local_git_repo["bare"]), projects_dir, "test__repo")
        setup_target_branch(project_path, local_git_repo["backport_sha"])
        wt_path = project_path / ".worktrees" / "test-run"
        create_worktree(project_path, "target", wt_path)
        cleanup(project_path, "test-run")
        assert not wt_path.exists()
