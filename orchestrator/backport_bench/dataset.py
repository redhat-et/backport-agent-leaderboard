import csv
import difflib
import re
from dataclasses import dataclass
from pathlib import Path


def parse_reason(reason: str) -> dict:
    defaults = {
        "similarity": 0.0,
        "file_overlap": 0.0,
        "size_ratio": 0.0,
        "orig_files": 0,
        "back_files": 0,
    }
    if not reason.strip():
        return defaults
    for part in reason.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in ("orig_files", "back_files"):
            defaults[key] = int(value)
        elif key in defaults:
            defaults[key] = float(value)
    return defaults


@dataclass
class RepoMetadata:
    build: str
    test: str
    guidelines: str


@dataclass
class BackportEntry:
    repo: str
    original_commit: str
    backport_commit: str
    classification: str
    similarity: float
    file_overlap: float
    size_ratio: float
    orig_files: int
    back_files: int

    @classmethod
    def from_csv_row(cls, row: dict) -> "BackportEntry":
        metrics = parse_reason(row["Reason"])
        return cls(
            repo=row["repo"],
            original_commit=row["Original Commit"],
            backport_commit=row["Backport Commit"],
            classification=row["Classification"],
            similarity=metrics["similarity"],
            file_overlap=metrics["file_overlap"],
            size_ratio=metrics["size_ratio"],
            orig_files=metrics["orig_files"],
            back_files=metrics["back_files"],
        )

    def to_reason_string(self) -> str:
        return (
            f"similarity={self.similarity:.2f}; "
            f"file_overlap={self.file_overlap:.2f}; "
            f"size_ratio={self.size_ratio:.2f}; "
            f"orig_files={self.orig_files}; "
            f"back_files={self.back_files}"
        )


def load_dataset(path: Path) -> list[BackportEntry]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    entries = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(BackportEntry.from_csv_row(row))
    return entries


def filter_dataset(
    entries: list[BackportEntry],
    *,
    repo: str | None = None,
    classification: str | None = None,
    original: str | None = None,
    backport: str | None = None,
    limit: int | None = None,
) -> list[BackportEntry]:
    filtered = list(entries)
    if repo is not None:
        filtered = [e for e in filtered if e.repo == repo]
    if classification is not None:
        filtered = [e for e in filtered if e.classification == classification]
    if original is not None:
        filtered = [e for e in filtered if e.original_commit == original]
    if backport is not None:
        filtered = [e for e in filtered if e.backport_commit == backport]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def classify_backport(*, similarity: float, file_overlap: float) -> str:
    if similarity >= 0.90 and file_overlap >= 0.80:
        return "Easy"
    if similarity >= 0.50 or file_overlap >= 0.50:
        return "Medium"
    return "Hard"


def _extract_files_from_diff(diff_text: str) -> set[str]:
    files = set()
    for line in diff_text.splitlines():
        match = re.match(r"^(?:---|\+\+\+) [ab]/(.+)$", line)
        if match:
            files.add(match.group(1))
    return files


def _normalize_diff(diff_text: str) -> str:
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("@@") or line.startswith("diff --git"):
            continue
        if line.startswith("index "):
            continue
        lines.append(line)
    return "\n".join(lines)


def _count_changed_lines(diff_text: str) -> int:
    return sum(1 for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


def compute_metrics(original_diff: str, backport_diff: str) -> dict:
    orig_norm = _normalize_diff(original_diff)
    back_norm = _normalize_diff(backport_diff)

    similarity = difflib.SequenceMatcher(None, orig_norm, back_norm).ratio()

    orig_files = _extract_files_from_diff(original_diff)
    back_files = _extract_files_from_diff(backport_diff)
    union = orig_files | back_files
    intersection = orig_files & back_files
    file_overlap = len(intersection) / len(union) if union else 1.0

    orig_lines = _count_changed_lines(original_diff)
    back_lines = _count_changed_lines(backport_diff)
    if max(orig_lines, back_lines) == 0:
        size_ratio = 1.0
    else:
        size_ratio = min(orig_lines, back_lines) / max(orig_lines, back_lines)

    return {
        "similarity": round(similarity, 2),
        "file_overlap": round(file_overlap, 2),
        "size_ratio": round(size_ratio, 2),
        "orig_files": len(orig_files),
        "back_files": len(back_files),
    }


def parse_repos_md(path: Path) -> dict[str, RepoMetadata]:
    path = Path(path)
    if not path.exists():
        return {}

    text = path.read_text()
    result = {}
    in_table = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if len(cells) < 6:
            continue
        if cells[0] in ("Repo", "---", "") or all(c.startswith("-") for c in cells):
            in_table = True
            continue
        if in_table:
            repo = cells[0].strip()
            build = cells[3].strip().strip("`")
            test = cells[4].strip().strip("`")
            guidelines = cells[5].strip()
            result[repo] = RepoMetadata(build=build, test=test, guidelines=guidelines)

    return result


def validate_commit_reachable(project_path: Path, sha: str) -> bool:
    import subprocess
    result = subprocess.run(
        ["git", "branch", "-r", "--contains", sha],
        cwd=project_path, capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def append_backport(entry: BackportEntry, csv_path: Path) -> None:
    csv_path = Path(csv_path)
    row = {
        "repo": entry.repo,
        "Original Commit": entry.original_commit,
        "Backport Commit": entry.backport_commit,
        "Classification": entry.classification,
        "Reason": entry.to_reason_string(),
    }
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["repo", "Original Commit", "Backport Commit", "Classification", "Reason"],
        )
        writer.writerow(row)
