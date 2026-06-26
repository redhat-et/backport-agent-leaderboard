import subprocess
from pathlib import Path


def clone_or_fetch(repo_url: str, projects_dir: Path, dir_name: str) -> Path:
    project_path = Path(projects_dir) / dir_name
    if project_path.exists():
        subprocess.run(
            ["git", "fetch", "--all"],
            cwd=project_path, check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "clone", repo_url, str(project_path)],
            check=True, capture_output=True,
        )
    return project_path


def find_source_branch(project_path: Path, original_sha: str) -> str:
    result = subprocess.run(
        ["git", "branch", "-r", "--contains", original_sha],
        cwd=project_path, capture_output=True, text=True,
    )
    branches = []
    for line in result.stdout.splitlines():
        branch = line.strip()
        if "->" in branch:
            continue
        branches.append(branch)

    if not branches:
        result = subprocess.run(
            ["git", "branch", "--contains", original_sha],
            cwd=project_path, capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            branches.append(branch)

    for preferred in ("origin/main", "origin/master", "main", "master"):
        if preferred in branches:
            return preferred

    if branches:
        return sorted(branches, key=len)[0]

    raise RuntimeError(f"No branch contains commit {original_sha}")


def setup_target_branch(project_path: Path, backport_sha: str) -> None:
    parent = subprocess.run(
        ["git", "rev-parse", f"{backport_sha}^"],
        cwd=project_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "branch", "target", parent],
        cwd=project_path, check=True, capture_output=True,
    )


def create_worktree(project_path: Path, branch: str, worktree_path: Path) -> None:
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), branch],
        cwd=project_path, check=True, capture_output=True,
    )


def extract_diff(project_path: Path, commit_sha: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{commit_sha}^..{commit_sha}"],
        cwd=project_path, capture_output=True, text=True, check=True,
    )
    return result.stdout


def cleanup(project_path: Path, run_key: str) -> None:
    wt_path = project_path / ".worktrees" / run_key
    if wt_path.exists():
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=project_path, capture_output=True,
        )
    subprocess.run(
        ["git", "branch", "-D", "target"],
        cwd=project_path, capture_output=True,
    )
