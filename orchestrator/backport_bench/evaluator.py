import difflib
import json
import re
from pathlib import Path


def parse_json_output(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    depth = 0
    start = None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    start = None

    return None


def run_semantic_diff(stdout: str) -> tuple[str | None, str | None]:
    parsed = parse_json_output(stdout)
    if parsed is None:
        return None, f"Failed to parse output: {stdout[:200]}"
    if parsed.get("equivalent") is True:
        return "PASS", None
    return "FAIL", parsed.get("reason", "No reason provided")


def run_guideline_check(stdout: str) -> tuple[str | None, str | None]:
    parsed = parse_json_output(stdout)
    if parsed is None:
        return None, f"Failed to parse output: {stdout[:200]}"
    if parsed.get("adheres") is True:
        return "PASS", None
    return "FAIL", parsed.get("reason", "No reason provided")


def _normalize_diff_for_comparison(diff_text: str) -> list[str]:
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("@@") or line.startswith("diff --git") or line.startswith("index "):
            continue
        lines.append(line)
    return lines


def compute_diff_lines(original_path: Path, pipeline_path: Path) -> int:
    try:
        orig_lines = _normalize_diff_for_comparison(Path(original_path).read_text())
    except FileNotFoundError:
        orig_lines = []
    try:
        pipe_lines = _normalize_diff_for_comparison(Path(pipeline_path).read_text())
    except FileNotFoundError:
        pipe_lines = []

    delta = list(difflib.unified_diff(orig_lines, pipe_lines, lineterm=""))
    return len([line for line in delta if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))])
