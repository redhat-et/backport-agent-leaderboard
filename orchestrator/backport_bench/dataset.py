import csv
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
