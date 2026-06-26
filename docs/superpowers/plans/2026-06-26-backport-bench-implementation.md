# Backport Agent Leaderboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a benchmarking platform with two packages — a Python CLI orchestrator that runs backporting tools against a curated dataset and stores results, and a standalone Gradio leaderboard app that visualizes them.

**Architecture:** Two independent Python packages sharing a `results/` directory. The orchestrator (Click CLI + Pydantic config + subprocess-based git/tool execution) writes per-run JSON results and aggregated files. The leaderboard (Gradio app) reads only the aggregated JSON files. No code dependency between the two packages.

**Tech Stack:** Python 3.12+, Click (CLI), Pydantic v2 (config validation), PyYAML (config parsing), pytest (testing), Gradio (leaderboard UI), pandas (data aggregation in leaderboard).

**Design Spec:** `docs/superpowers/specs/2026-06-26-backport-bench-design.md`
**PRD:** `PRD.md`

---

## File Structure

### Orchestrator Package (`orchestrator/`)

| File | Responsibility |
|---|---|
| `orchestrator/pyproject.toml` | Package metadata, dependencies (click, pyyaml, pydantic), console script `backport-bench` |
| `orchestrator/backport_bench/__init__.py` | Package init, version string |
| `orchestrator/backport_bench/cli.py` | Click CLI entry point with subcommands: `run`, `results`, `leaderboard`, `add-backport` |
| `orchestrator/backport_bench/config.py` | YAML parsing into Pydantic v2 models: `BenchmarkConfig`, `ToolDefinition`, `ToolCommands`, `SemanticDiffConfig`, `GuidelineCheckConfig` |
| `orchestrator/backport_bench/dataset.py` | CSV loading/filtering/writing, `BackportEntry` dataclass, classification computation, metric extraction from `reason` string |
| `orchestrator/backport_bench/git_ops.py` | Git subprocess wrappers: clone/fetch, branch detection, worktree management, diff extraction, cleanup |
| `orchestrator/backport_bench/variables.py` | Environment variable dict builder — merges orchestrator, tool config, and evaluation model variables |
| `orchestrator/backport_bench/evaluator.py` | Runs semantic diff and guideline check commands, parses JSON output, computes diff line count |
| `orchestrator/backport_bench/runner.py` | Single-run orchestration pipeline (`execute_run`), command execution, timeout handling, error resilience |
| `orchestrator/backport_bench/results.py` | `RunResult` dataclass, per-run JSON read/write, resume check (`has_result`), aggregation logic |

### Orchestrator Tests (`orchestrator/tests/`)

| File | Responsibility |
|---|---|
| `orchestrator/tests/conftest.py` | Shared fixtures: temp dirs, sample CSV data, sample YAML config, mock git repos |
| `orchestrator/tests/test_config.py` | Config parsing, validation, edge cases |
| `orchestrator/tests/test_dataset.py` | CSV loading, filtering, classification, metric parsing, add-backport logic |
| `orchestrator/tests/test_git_ops.py` | Git operations against real temp repos (integration tests) |
| `orchestrator/tests/test_variables.py` | Variable dict building and merging |
| `orchestrator/tests/test_evaluator.py` | JSON parsing, semantic diff/guideline check result mapping |
| `orchestrator/tests/test_results.py` | Result serialization, resume check, aggregation |
| `orchestrator/tests/test_runner.py` | Pipeline orchestration with mocked subprocess calls |
| `orchestrator/tests/test_cli.py` | Click CLI integration tests using `CliRunner` |
| `orchestrator/tests/bdd/` | BDD feature files and step definitions (see Task 16) |

### Leaderboard Package (`leaderboard/`)

| File | Responsibility |
|---|---|
| `leaderboard/pyproject.toml` | Package metadata, dependencies (gradio, pandas) |
| `leaderboard/app.py` | Gradio app: tabs, dataframes, filters, auto-refresh |
| `leaderboard/data_loader.py` | Reads `results/aggregated/*.json`, builds leaderboard and runs DataFrames |
| `leaderboard/about.md` | Content for the About tab |
| `leaderboard/tests/test_data_loader.py` | Data loading and DataFrame construction tests |
| `leaderboard/tests/test_app.py` | Gradio app layout and interaction tests |

---

## Phase 1: Orchestrator Core (Tasks 1–12)

### Task 1: Project Scaffolding — Orchestrator Package

**Files:**
- Create: `orchestrator/pyproject.toml`
- Create: `orchestrator/backport_bench/__init__.py`
- Create: `orchestrator/tests/__init__.py`
- Create: `orchestrator/tests/conftest.py`

- [ ] **Step 1: Create `orchestrator/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "backport-bench"
version = "0.1.0"
description = "Benchmark orchestrator for automated backporting tools"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-bdd>=7.0",
]

[project.scripts]
backport-bench = "backport_bench.cli:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `orchestrator/backport_bench/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `orchestrator/tests/__init__.py`**

Empty file.

- [ ] **Step 4: Create `orchestrator/tests/conftest.py` with foundational fixtures**

```python
import csv
import os
import textwrap
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_results_dir(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "aggregated").mkdir()
    return results_dir


@pytest.fixture
def tmp_projects_dir(tmp_path):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return projects_dir


@pytest.fixture
def tmp_diffs_dir(tmp_path):
    diffs_dir = tmp_path / "diffs"
    diffs_dir.mkdir()
    return diffs_dir


@pytest.fixture
def sample_csv_path(tmp_path):
    csv_path = tmp_path / "backports.csv"
    rows = [
        {
            "repo": "owner/repo-a",
            "Original Commit": "aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
            "Backport Commit": "bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
            "Classification": "Easy",
            "Reason": "similarity=1.00; file_overlap=1.00; size_ratio=1.00; orig_files=2; back_files=2",
        },
        {
            "repo": "owner/repo-a",
            "Original Commit": "cccc3333cccc3333cccc3333cccc3333cccc3333",
            "Backport Commit": "dddd4444dddd4444dddd4444dddd4444dddd4444",
            "Classification": "Medium",
            "Reason": "similarity=0.75; file_overlap=0.60; size_ratio=0.80; orig_files=4; back_files=3",
        },
        {
            "repo": "other/repo-b",
            "Original Commit": "eeee5555eeee5555eeee5555eeee5555eeee5555",
            "Backport Commit": "ffff6666ffff6666ffff6666ffff6666ffff6666",
            "Classification": "Hard",
            "Reason": "similarity=0.30; file_overlap=0.40; size_ratio=0.50; orig_files=6; back_files=4",
        },
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["repo", "Original Commit", "Backport Commit", "Classification", "Reason"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def sample_repos_md(tmp_path):
    repos_md = tmp_path / "repos.md"
    repos_md.write_text(textwrap.dedent("""\
        # Key Repos

        | Repo | Technology | Prerequisites | Build | Test | Guidelines |
        |---|--------|-----|---|---|-----|
        | owner/repo-a | Python (100%). | Python >= 3.12. | `pip install .` | `pytest` | PEP 8, Black. |
    """))
    return repos_md


@pytest.fixture
def sample_config_dict():
    return {
        "semantic_diff": {
            "model": "claude-opus-4-6",
            "command": 'echo \'{"equivalent": true}\'',
        },
        "guideline_check": {
            "model": "claude-opus-4-6",
            "command": 'echo \'{"adheres": true}\'',
        },
        "default_tool": "test-tool",
        "timeout": 60,
        "verify_tests": False,
        "tools": {
            "test-tool": {
                "display_name": "Test Tool / Default",
                "model": "claude-opus-4-6",
                "config": {"workdir": "/tmp/test"},
                "commands": {
                    "generate_diff": "echo 'mock diff' > ${PIPELINE_DIFF_PATH}",
                },
            },
        },
    }


@pytest.fixture
def sample_config_path(tmp_path, sample_config_dict):
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)
    return config_path
```

- [ ] **Step 5: Install the package in dev mode and verify pytest runs**

Run: `cd orchestrator && pip install -e ".[dev]" && pytest --co`
Expected: Collected 0 items (no tests yet, no errors)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/
git commit -m "feat: scaffold orchestrator package with pyproject.toml and test fixtures"
```

---

### Task 2: Configuration System (`config.py`)

**Files:**
- Create: `orchestrator/backport_bench/config.py`
- Create: `orchestrator/tests/test_config.py`

- [ ] **Step 1: Write failing tests for config parsing**

```python
# orchestrator/tests/test_config.py
import pytest
import yaml

from backport_bench.config import (
    BenchmarkConfig,
    GuidelineCheckConfig,
    SemanticDiffConfig,
    ToolCommands,
    ToolDefinition,
    load_config,
)


class TestToolCommands:
    def test_generate_diff_required(self):
        tc = ToolCommands(generate_diff="echo hello")
        assert tc.generate_diff == "echo hello"
        assert tc.setup is None
        assert tc.get_stats is None

    def test_all_commands(self):
        tc = ToolCommands(
            setup="echo setup",
            generate_diff="echo diff",
            get_stats="echo stats",
        )
        assert tc.setup == "echo setup"
        assert tc.generate_diff == "echo diff"
        assert tc.get_stats == "echo stats"


class TestToolDefinition:
    def test_minimal(self):
        td = ToolDefinition(
            display_name="My Tool",
            commands=ToolCommands(generate_diff="echo diff"),
        )
        assert td.display_name == "My Tool"
        assert td.model is None
        assert td.config == {}

    def test_with_model_and_config(self):
        td = ToolDefinition(
            display_name="My Tool",
            model="claude-opus-4-6",
            config={"workdir": "/tmp", "tool_location": "/opt/tool"},
            commands=ToolCommands(generate_diff="echo diff"),
        )
        assert td.model == "claude-opus-4-6"
        assert td.config["workdir"] == "/tmp"
        assert td.config["tool_location"] == "/opt/tool"


class TestSemanticDiffConfig:
    def test_fields(self):
        sdc = SemanticDiffConfig(model="claude-opus-4-6", command="echo test")
        assert sdc.model == "claude-opus-4-6"
        assert sdc.command == "echo test"


class TestGuidelineCheckConfig:
    def test_fields(self):
        gcc = GuidelineCheckConfig(model="claude-opus-4-6", command="echo test")
        assert gcc.model == "claude-opus-4-6"
        assert gcc.command == "echo test"


class TestBenchmarkConfig:
    def test_defaults(self, sample_config_dict):
        config = BenchmarkConfig(**sample_config_dict)
        assert config.timeout == 60
        assert config.verify_tests is False
        assert config.default_tool == "test-tool"

    def test_tool_access(self, sample_config_dict):
        config = BenchmarkConfig(**sample_config_dict)
        tool = config.tools["test-tool"]
        assert tool.display_name == "Test Tool / Default"
        assert tool.model == "claude-opus-4-6"

    def test_default_timeout(self):
        minimal = {
            "semantic_diff": {"model": "m", "command": "c"},
            "guideline_check": {"model": "m", "command": "c"},
            "default_tool": "t",
            "tools": {
                "t": {
                    "display_name": "T",
                    "commands": {"generate_diff": "echo"},
                },
            },
        }
        config = BenchmarkConfig(**minimal)
        assert config.timeout == 1800
        assert config.verify_tests is False


class TestLoadConfig:
    def test_load_from_yaml(self, sample_config_path):
        config = load_config(sample_config_path)
        assert isinstance(config, BenchmarkConfig)
        assert config.default_tool == "test-tool"
        assert "test-tool" in config.tools

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: valid: yaml: {{{}}")
        with pytest.raises(Exception):
            load_config(bad)

    def test_missing_required_field_raises(self, tmp_path):
        incomplete = tmp_path / "incomplete.yaml"
        incomplete.write_text(yaml.dump({"timeout": 60}))
        with pytest.raises(Exception):
            load_config(incomplete)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.config'`

- [ ] **Step 3: Implement `config.py`**

```python
# orchestrator/backport_bench/config.py
from pathlib import Path

import yaml
from pydantic import BaseModel


class SemanticDiffConfig(BaseModel):
    model: str
    command: str


class GuidelineCheckConfig(BaseModel):
    model: str
    command: str


class ToolCommands(BaseModel):
    setup: str | None = None
    generate_diff: str
    get_stats: str | None = None


class ToolDefinition(BaseModel):
    display_name: str
    model: str | None = None
    config: dict[str, str] = {}
    commands: ToolCommands


class BenchmarkConfig(BaseModel):
    semantic_diff: SemanticDiffConfig
    guideline_check: GuidelineCheckConfig
    default_tool: str
    timeout: int = 1800
    verify_tests: bool = False
    tools: dict[str, ToolDefinition]


def load_config(path: Path) -> BenchmarkConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return BenchmarkConfig(**raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/config.py orchestrator/tests/test_config.py
git commit -m "feat: add config parsing with Pydantic v2 models"
```

---

### Task 3: Dataset Management — Data Model and Loading (`dataset.py`)

**Files:**
- Create: `orchestrator/backport_bench/dataset.py`
- Create: `orchestrator/tests/test_dataset.py`

- [ ] **Step 1: Write failing tests for BackportEntry and CSV loading**

```python
# orchestrator/tests/test_dataset.py
import csv
from pathlib import Path

import pytest

from backport_bench.dataset import BackportEntry, load_dataset, parse_reason


class TestParseReason:
    def test_full_reason_string(self):
        reason = "similarity=0.95; file_overlap=0.60; size_ratio=0.97; orig_files=5; back_files=3"
        result = parse_reason(reason)
        assert result["similarity"] == 0.95
        assert result["file_overlap"] == 0.60
        assert result["size_ratio"] == 0.97
        assert result["orig_files"] == 5
        assert result["back_files"] == 3

    def test_whitespace_tolerance(self):
        reason = "similarity=1.00;file_overlap=1.00;size_ratio=1.00;orig_files=2;back_files=2"
        result = parse_reason(reason)
        assert result["similarity"] == 1.00

    def test_empty_reason(self):
        result = parse_reason("")
        assert result["similarity"] == 0.0
        assert result["orig_files"] == 0


class TestBackportEntry:
    def test_from_csv_row(self):
        row = {
            "repo": "owner/repo",
            "Original Commit": "aaaa1111" * 5,
            "Backport Commit": "bbbb2222" * 5,
            "Classification": "Easy",
            "Reason": "similarity=1.00; file_overlap=1.00; size_ratio=1.00; orig_files=2; back_files=2",
        }
        entry = BackportEntry.from_csv_row(row)
        assert entry.repo == "owner/repo"
        assert entry.original_commit == "aaaa1111" * 5
        assert entry.classification == "Easy"
        assert entry.similarity == 1.00
        assert entry.file_overlap == 1.00
        assert entry.orig_files == 2

    def test_to_reason_string(self):
        entry = BackportEntry(
            repo="owner/repo",
            original_commit="a" * 40,
            backport_commit="b" * 40,
            classification="Easy",
            similarity=0.95,
            file_overlap=0.60,
            size_ratio=0.97,
            orig_files=5,
            back_files=3,
        )
        reason = entry.to_reason_string()
        assert "similarity=0.95" in reason
        assert "file_overlap=0.60" in reason
        assert "orig_files=5" in reason

    def test_roundtrip_reason(self):
        original = "similarity=0.95; file_overlap=0.60; size_ratio=0.97; orig_files=5; back_files=3"
        row = {
            "repo": "o/r",
            "Original Commit": "a" * 40,
            "Backport Commit": "b" * 40,
            "Classification": "Medium",
            "Reason": original,
        }
        entry = BackportEntry.from_csv_row(row)
        roundtripped = entry.to_reason_string()
        reparsed = parse_reason(roundtripped)
        assert reparsed["similarity"] == 0.95
        assert reparsed["orig_files"] == 5


class TestLoadDataset:
    def test_loads_all_entries(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        assert len(entries) == 3

    def test_entry_fields(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        assert entries[0].repo == "owner/repo-a"
        assert entries[0].classification == "Easy"
        assert entries[0].similarity == 1.00

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_dataset(tmp_path / "missing.csv")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.dataset'`

- [ ] **Step 3: Implement `dataset.py` — data model and loading**

```python
# orchestrator/backport_bench/dataset.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/dataset.py orchestrator/tests/test_dataset.py
git commit -m "feat: add BackportEntry dataclass and CSV loading"
```

---

### Task 4: Dataset Filtering

**Files:**
- Modify: `orchestrator/backport_bench/dataset.py`
- Modify: `orchestrator/tests/test_dataset.py`

- [ ] **Step 1: Write failing tests for filtering**

Append to `orchestrator/tests/test_dataset.py`:

```python
from backport_bench.dataset import filter_dataset


class TestFilterDataset:
    def test_filter_by_repo(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, repo="owner/repo-a")
        assert len(filtered) == 2
        assert all(e.repo == "owner/repo-a" for e in filtered)

    def test_filter_by_classification(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, classification="Hard")
        assert len(filtered) == 1
        assert filtered[0].classification == "Hard"

    def test_filter_by_original_sha(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(
            entries, original="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
        )
        assert len(filtered) == 1

    def test_filter_by_backport_sha(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(
            entries, backport="dddd4444dddd4444dddd4444dddd4444dddd4444"
        )
        assert len(filtered) == 1

    def test_filter_combined_original_and_backport(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(
            entries,
            original="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
            backport="bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
        )
        assert len(filtered) == 1

    def test_filter_with_limit(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, limit=1)
        assert len(filtered) == 1

    def test_no_filters_returns_all(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries)
        assert len(filtered) == 3

    def test_filter_no_match(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, repo="nonexistent/repo")
        assert len(filtered) == 0

    def test_filter_order_preserved(self, sample_csv_path):
        """Filters apply in order: repo, classification, SHA, then limit."""
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, repo="owner/repo-a", limit=1)
        assert len(filtered) == 1
        assert filtered[0].classification == "Easy"
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `cd orchestrator && pytest tests/test_dataset.py::TestFilterDataset -v`
Expected: FAIL — `ImportError: cannot import name 'filter_dataset'`

- [ ] **Step 3: Implement `filter_dataset` in `dataset.py`**

Add to `orchestrator/backport_bench/dataset.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/dataset.py orchestrator/tests/test_dataset.py
git commit -m "feat: add dataset filtering by repo, classification, SHA, and limit"
```

---

### Task 5: Dataset Classification and Metrics Computation

**Files:**
- Modify: `orchestrator/backport_bench/dataset.py`
- Modify: `orchestrator/tests/test_dataset.py`

- [ ] **Step 1: Write failing tests for classification logic**

Append to `orchestrator/tests/test_dataset.py`:

```python
from backport_bench.dataset import classify_backport, compute_metrics
import difflib


class TestClassifyBackport:
    def test_easy_high_similarity_high_overlap(self):
        assert classify_backport(similarity=0.95, file_overlap=0.90) == "Easy"

    def test_easy_boundary(self):
        assert classify_backport(similarity=0.90, file_overlap=0.80) == "Easy"

    def test_medium_high_similarity_low_overlap(self):
        assert classify_backport(similarity=0.95, file_overlap=0.50) == "Medium"

    def test_medium_low_similarity_high_overlap(self):
        assert classify_backport(similarity=0.50, file_overlap=0.40) == "Medium"

    def test_medium_boundary(self):
        assert classify_backport(similarity=0.50, file_overlap=0.30) == "Medium"

    def test_hard(self):
        assert classify_backport(similarity=0.30, file_overlap=0.30) == "Hard"

    def test_hard_just_below_medium(self):
        assert classify_backport(similarity=0.49, file_overlap=0.49) == "Hard"


class TestComputeMetrics:
    def test_identical_diffs(self):
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n-old\n+new\n"
        metrics = compute_metrics(diff, diff)
        assert metrics["similarity"] == 1.0
        assert metrics["file_overlap"] == 1.0
        assert metrics["size_ratio"] == 1.0

    def test_different_files(self):
        diff_a = "--- a/file_a.py\n+++ b/file_a.py\n@@ -1 +1 @@\n-old\n+new\n"
        diff_b = "--- a/file_b.py\n+++ b/file_b.py\n@@ -1 +1 @@\n-old\n+new\n"
        metrics = compute_metrics(diff_a, diff_b)
        assert metrics["file_overlap"] == 0.0

    def test_partial_file_overlap(self):
        diff_a = "--- a/shared.py\n+++ b/shared.py\n@@ -1 +1 @@\n-old\n+new\n--- a/only_a.py\n+++ b/only_a.py\n@@ -1 +1 @@\n-x\n+y\n"
        diff_b = "--- a/shared.py\n+++ b/shared.py\n@@ -1 +1 @@\n-old\n+new\n--- a/only_b.py\n+++ b/only_b.py\n@@ -1 +1 @@\n-x\n+y\n"
        metrics = compute_metrics(diff_a, diff_b)
        assert 0.3 < metrics["file_overlap"] < 0.7

    def test_counts_files(self):
        diff = "--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n-a\n+b\n--- a/two.py\n+++ b/two.py\n@@ -1 +1 @@\n-c\n+d\n"
        metrics = compute_metrics(diff, diff)
        assert metrics["orig_files"] == 2
        assert metrics["back_files"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_dataset.py::TestClassifyBackport tests/test_dataset.py::TestComputeMetrics -v`
Expected: FAIL — `ImportError: cannot import name 'classify_backport'`

- [ ] **Step 3: Implement classification and metrics in `dataset.py`**

Add to `orchestrator/backport_bench/dataset.py`:

```python
import difflib
import re


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/dataset.py orchestrator/tests/test_dataset.py
git commit -m "feat: add classification logic and diff metrics computation"
```

---

### Task 6: Repo Metadata Parsing

**Files:**
- Modify: `orchestrator/backport_bench/dataset.py`
- Modify: `orchestrator/tests/test_dataset.py`

- [ ] **Step 1: Write failing tests for repos.md parsing**

Append to `orchestrator/tests/test_dataset.py`:

```python
from backport_bench.dataset import parse_repos_md, RepoMetadata


class TestParseReposMd:
    def test_parses_known_repo(self, sample_repos_md):
        repos = parse_repos_md(sample_repos_md)
        assert "owner/repo-a" in repos
        meta = repos["owner/repo-a"]
        assert meta.build == "pip install ."
        assert meta.test == "pytest"
        assert "PEP 8" in meta.guidelines

    def test_unknown_repo_not_in_result(self, sample_repos_md):
        repos = parse_repos_md(sample_repos_md)
        assert "unknown/repo" not in repos

    def test_missing_file_returns_empty(self, tmp_path):
        repos = parse_repos_md(tmp_path / "nonexistent.md")
        assert repos == {}

    def test_strips_backticks_from_commands(self, sample_repos_md):
        repos = parse_repos_md(sample_repos_md)
        meta = repos["owner/repo-a"]
        assert "`" not in meta.build
        assert "`" not in meta.test
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_dataset.py::TestParseReposMd -v`
Expected: FAIL — `ImportError: cannot import name 'parse_repos_md'`

- [ ] **Step 3: Implement `parse_repos_md` in `dataset.py`**

Add to `orchestrator/backport_bench/dataset.py`:

```python
@dataclass
class RepoMetadata:
    build: str
    test: str
    guidelines: str


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/dataset.py orchestrator/tests/test_dataset.py
git commit -m "feat: add repos.md markdown table parser"
```

---

### Task 7: Variable Building (`variables.py`)

**Files:**
- Create: `orchestrator/backport_bench/variables.py`
- Create: `orchestrator/tests/test_variables.py`

- [ ] **Step 1: Write failing tests**

```python
# orchestrator/tests/test_variables.py
from backport_bench.variables import build_variable_dict
from backport_bench.config import BenchmarkConfig, ToolDefinition, ToolCommands


class TestBuildVariableDict:
    def test_orchestrator_variables(self):
        env = build_variable_dict(
            repo="owner/repo",
            orig_sha="aaa111",
            backport_sha="bbb222",
            run_key="aaa111-bbb222",
            project_path="/projects/owner__repo",
            source_branch="main",
            target_workspace="/projects/owner__repo/.worktrees/aaa111-bbb222",
            original_diff_path="/diffs/original.diff",
            pipeline_diff_path="/diffs/pipeline.diff",
            build_cmd="make",
            test_command="make test",
            repo_guidelines="PEP 8",
            tool=ToolDefinition(
                display_name="T",
                commands=ToolCommands(generate_diff="echo"),
            ),
            semantic_diff_model="claude-opus-4-6",
            guideline_check_model="claude-opus-4-6",
        )
        assert env["REPO"] == "owner/repo"
        assert env["ORIG_SHA"] == "aaa111"
        assert env["BACKPORT_SHA"] == "bbb222"
        assert env["RUN_KEY"] == "aaa111-bbb222"
        assert env["PROJECT_PATH"] == "/projects/owner__repo"
        assert env["SOURCE_BRANCH"] == "main"
        assert env["TARGET_WORKSPACE"] == "/projects/owner__repo/.worktrees/aaa111-bbb222"
        assert env["ORIGINAL_DIFF_PATH"] == "/diffs/original.diff"
        assert env["PIPELINE_DIFF_PATH"] == "/diffs/pipeline.diff"
        assert env["BUILD_CMD"] == "make"
        assert env["TEST_COMMAND"] == "make test"
        assert env["REPO_GUIDELINES"] == "PEP 8"

    def test_tool_config_variables(self):
        tool = ToolDefinition(
            display_name="T",
            model="claude-opus-4-6",
            config={"tool_location": "/opt/tool", "workdir": "/tmp"},
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="m", guideline_check_model="m",
        )
        assert env["CONFIG_MODEL"] == "claude-opus-4-6"
        assert env["CONFIG_TOOL_LOCATION"] == "/opt/tool"
        assert env["CONFIG_WORKDIR"] == "/tmp"

    def test_evaluation_model_variables(self):
        tool = ToolDefinition(
            display_name="T",
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="sd-model", guideline_check_model="gc-model",
        )
        assert env["SEMANTIC_DIFF_MODEL"] == "sd-model"
        assert env["GUIDELINE_CHECK_MODEL"] == "gc-model"

    def test_no_model_omits_config_model(self):
        tool = ToolDefinition(
            display_name="T",
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="m", guideline_check_model="m",
        )
        assert "CONFIG_MODEL" not in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_variables.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.variables'`

- [ ] **Step 3: Implement `variables.py`**

```python
# orchestrator/backport_bench/variables.py
import os

from backport_bench.config import ToolDefinition


def build_variable_dict(
    *,
    repo: str,
    orig_sha: str,
    backport_sha: str,
    run_key: str,
    project_path: str,
    source_branch: str,
    target_workspace: str,
    original_diff_path: str,
    pipeline_diff_path: str,
    build_cmd: str,
    test_command: str,
    repo_guidelines: str,
    tool: ToolDefinition,
    semantic_diff_model: str,
    guideline_check_model: str,
) -> dict[str, str]:
    env = dict(os.environ)

    env["REPO"] = repo
    env["ORIG_SHA"] = orig_sha
    env["BACKPORT_SHA"] = backport_sha
    env["RUN_KEY"] = run_key
    env["PROJECT_PATH"] = project_path
    env["SOURCE_BRANCH"] = source_branch
    env["TARGET_WORKSPACE"] = target_workspace
    env["ORIGINAL_DIFF_PATH"] = original_diff_path
    env["PIPELINE_DIFF_PATH"] = pipeline_diff_path
    env["BUILD_CMD"] = build_cmd
    env["TEST_COMMAND"] = test_command
    env["REPO_GUIDELINES"] = repo_guidelines

    if tool.model is not None:
        env["CONFIG_MODEL"] = tool.model
    for key, value in tool.config.items():
        env[f"CONFIG_{key.upper()}"] = value

    env["SEMANTIC_DIFF_MODEL"] = semantic_diff_model
    env["GUIDELINE_CHECK_MODEL"] = guideline_check_model

    return env
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_variables.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/variables.py orchestrator/tests/test_variables.py
git commit -m "feat: add environment variable builder for subprocess commands"
```

---

### Task 8: Git Operations (`git_ops.py`)

**Files:**
- Create: `orchestrator/backport_bench/git_ops.py`
- Create: `orchestrator/tests/test_git_ops.py`

- [ ] **Step 1: Write failing tests for git operations**

These tests create real temporary git repos to test against.

```python
# orchestrator/tests/test_git_ops.py
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

    # Initial commit on main
    (work / "file.txt").write_text("initial")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "initial"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )

    # Original fix commit
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

    # Create release branch from initial commit
    subprocess.run(["git", "-C", str(work), "branch", "release-1.0", "HEAD~1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "release-1.0"], check=True, capture_output=True)

    # Backport commit on release branch
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_git_ops.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.git_ops'`

- [ ] **Step 3: Implement `git_ops.py`**

```python
# orchestrator/backport_bench/git_ops.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_git_ops.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/git_ops.py orchestrator/tests/test_git_ops.py
git commit -m "feat: add git operations — clone, branch, worktree, diff, cleanup"
```

---

### Task 9: Result Storage (`results.py`)

**Files:**
- Create: `orchestrator/backport_bench/results.py`
- Create: `orchestrator/tests/test_results.py`

- [ ] **Step 1: Write failing tests for RunResult and storage**

```python
# orchestrator/tests/test_results.py
import json
from pathlib import Path

import pytest

from backport_bench.results import RunResult, save_result, load_result, has_result, aggregate_results


@pytest.fixture
def sample_run_result():
    return RunResult(
        tool_display_name="Test Tool / Default",
        tool_key="test-tool",
        repo="owner/repo",
        original_commit="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
        backport_commit="bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
        classification="Easy",
        semantic_equivalence="PASS",
        semantic_difference_reason=None,
        guideline_adherence="PASS",
        guideline_reason=None,
        test_success="SKIPPED",
        error_message=None,
        diff_lines=0,
        time_seconds=45.2,
        llm_calls=3,
        cost_usd=0.74,
        input_tokens=200000,
        output_tokens=4800,
        timestamp="2026-06-26T14:30:00Z",
    )


class TestRunResult:
    def test_to_dict(self, sample_run_result):
        d = sample_run_result.to_dict()
        assert d["tool_key"] == "test-tool"
        assert d["semantic_equivalence"] == "PASS"
        assert d["timestamp"] == "2026-06-26T14:30:00Z"

    def test_from_dict(self, sample_run_result):
        d = sample_run_result.to_dict()
        restored = RunResult.from_dict(d)
        assert restored.tool_key == sample_run_result.tool_key
        assert restored.cost_usd == sample_run_result.cost_usd

    def test_filename(self, sample_run_result):
        name = sample_run_result.filename()
        assert name == "test-tool__owner__repo__aaaa1111__bbbb2222.json"


class TestSaveAndLoadResult:
    def test_roundtrip(self, tmp_results_dir, sample_run_result):
        save_result(sample_run_result, tmp_results_dir)
        expected_path = tmp_results_dir / sample_run_result.filename()
        assert expected_path.exists()
        loaded = load_result(expected_path)
        assert loaded.tool_key == sample_run_result.tool_key
        assert loaded.cost_usd == sample_run_result.cost_usd


class TestHasResult:
    def test_returns_false_when_missing(self, tmp_results_dir):
        assert has_result("tool", "o/r", "aaa", "bbb", tmp_results_dir) is False

    def test_returns_true_when_present(self, tmp_results_dir, sample_run_result):
        save_result(sample_run_result, tmp_results_dir)
        assert has_result(
            "test-tool", "owner/repo",
            "aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
            "bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
            tmp_results_dir,
        ) is True


class TestAggregateResults:
    def test_creates_aggregated_files(self, tmp_results_dir, sample_run_result):
        save_result(sample_run_result, tmp_results_dir)
        aggregate_results(tmp_results_dir)
        agg_dir = tmp_results_dir / "aggregated"
        files = list(agg_dir.glob("*.json"))
        assert len(files) >= 1

    def test_aggregated_format(self, tmp_results_dir, sample_run_result):
        save_result(sample_run_result, tmp_results_dir)
        aggregate_results(tmp_results_dir)
        agg_dir = tmp_results_dir / "aggregated"
        files = list(agg_dir.glob("*.json"))
        with open(files[0]) as f:
            data = json.load(f)
        assert "benchmark" in data
        assert "tool" in data
        assert "metrics" in data
        assert "score" in data["metrics"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_results.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.results'`

- [ ] **Step 3: Implement `results.py`**

```python
# orchestrator/backport_bench/results.py
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict


@dataclass
class RunResult:
    tool_display_name: str
    tool_key: str
    repo: str
    original_commit: str
    backport_commit: str
    classification: str
    semantic_equivalence: str | None
    semantic_difference_reason: str | None
    guideline_adherence: str | None
    guideline_reason: str | None
    test_success: str | None
    error_message: str | None
    diff_lines: int | None
    time_seconds: float | None
    llm_calls: int | None
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(**d)

    def filename(self) -> str:
        owner, repo = self.repo.split("/", 1)
        orig_short = self.original_commit[:8]
        back_short = self.backport_commit[:8]
        return f"{self.tool_key}__{owner}__{repo}__{orig_short}__{back_short}.json"


def save_result(result: RunResult, results_dir: Path) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / result.filename()
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    return path


def load_result(path: Path) -> RunResult:
    with open(path) as f:
        return RunResult.from_dict(json.load(f))


def has_result(
    tool_key: str, repo: str, original_commit: str, backport_commit: str,
    results_dir: Path,
) -> bool:
    owner, repo_name = repo.split("/", 1)
    orig_short = original_commit[:8]
    back_short = backport_commit[:8]
    filename = f"{tool_key}__{owner}__{repo_name}__{orig_short}__{back_short}.json"
    return (Path(results_dir) / filename).exists()


def _safe_mean(values: list) -> float:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return 0.0
    return sum(filtered) / len(filtered)


def aggregate_results(results_dir: Path) -> None:
    results_dir = Path(results_dir)
    agg_dir = results_dir / "aggregated"
    agg_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for path in results_dir.glob("*.json"):
        if path.parent.name == "aggregated":
            continue
        results.append(load_result(path))

    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[(r.tool_display_name, r.repo)].append(r)

    for (tool_name, repo), runs in grouped.items():
        n_tasks = len(runs)
        n_errors = sum(1 for r in runs if r.error_message is not None)
        n_pass = sum(1 for r in runs if r.semantic_equivalence == "PASS")
        score = n_pass / n_tasks if n_tasks > 0 else 0.0

        agg = {
            "benchmark": {
                "name": f"backportbench-{repo.replace('/', '-')}",
                "repo": repo,
                "num_tasks": n_tasks,
                "url": f"https://github.com/{repo}",
            },
            "tool": {
                "display_name": tool_name,
                "is_oss": True,
                "url": "",
            },
            "metrics": {
                "score": round(score, 4),
                "n_tasks": n_tasks,
                "n_errors": n_errors,
                "n_input_tokens": sum(r.input_tokens or 0 for r in runs),
                "n_output_tokens": sum(r.output_tokens or 0 for r in runs),
                "n_total_tokens": sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in runs),
                "total_time_seconds": sum(r.time_seconds or 0 for r in runs),
                "cost_usd": sum(r.cost_usd or 0 for r in runs),
                "mean_input_tokens_per_task": round(_safe_mean([r.input_tokens for r in runs])),
                "mean_output_tokens_per_task": round(_safe_mean([r.output_tokens for r in runs])),
                "mean_cost_usd_per_task": round(_safe_mean([r.cost_usd for r in runs]), 2),
                "mean_time_seconds_per_task": round(_safe_mean([r.time_seconds for r in runs]), 1),
            },
        }

        safe_tool = tool_name.replace("/", "-").replace(" ", "_").lower()
        safe_repo = repo.replace("/", "-")
        filename = f"{safe_tool}__{safe_repo}.json"
        with open(agg_dir / filename, "w") as f:
            json.dump(agg, f, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_results.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/results.py orchestrator/tests/test_results.py
git commit -m "feat: add result storage, resume check, and aggregation"
```

---

### Task 10: Evaluator (`evaluator.py`)

**Files:**
- Create: `orchestrator/backport_bench/evaluator.py`
- Create: `orchestrator/tests/test_evaluator.py`

- [ ] **Step 1: Write failing tests for JSON parsing and evaluation**

```python
# orchestrator/tests/test_evaluator.py
import json
import pytest

from backport_bench.evaluator import (
    parse_json_output,
    run_semantic_diff,
    run_guideline_check,
    compute_diff_lines,
)


class TestParseJsonOutput:
    def test_clean_json(self):
        result = parse_json_output('{"equivalent": true}')
        assert result == {"equivalent": True}

    def test_json_with_preamble(self):
        raw = 'Here is the result:\n{"equivalent": false, "reason": "missing retry"}\nDone.'
        result = parse_json_output(raw)
        assert result["equivalent"] is False
        assert result["reason"] == "missing retry"

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"adheres": true}\n```'
        result = parse_json_output(raw)
        assert result["adheres"] is True

    def test_nested_braces(self):
        raw = '{"key": {"nested": 1}}'
        result = parse_json_output(raw)
        assert result["key"]["nested"] == 1

    def test_no_json_returns_none(self):
        result = parse_json_output("no json here")
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_json_output("")
        assert result is None


class TestRunSemanticDiff:
    def test_pass_result(self):
        equiv, reason = run_semantic_diff('{"equivalent": true}')
        assert equiv == "PASS"
        assert reason is None

    def test_fail_result(self):
        equiv, reason = run_semantic_diff('{"equivalent": false, "reason": "missing logic"}')
        assert equiv == "FAIL"
        assert reason == "missing logic"

    def test_unparseable_returns_none(self):
        equiv, reason = run_semantic_diff("garbage output")
        assert equiv is None
        assert reason is not None


class TestRunGuidelineCheck:
    def test_pass_result(self):
        adherence, reason = run_guideline_check('{"adheres": true}')
        assert adherence == "PASS"
        assert reason is None

    def test_fail_result(self):
        adherence, reason = run_guideline_check('{"adheres": false, "reason": "no DCO sign-off"}')
        assert adherence == "FAIL"
        assert reason == "no DCO sign-off"

    def test_unparseable_returns_none(self):
        adherence, reason = run_guideline_check("garbage")
        assert adherence is None
        assert reason is not None


class TestComputeDiffLines:
    def test_identical_diffs(self, tmp_path):
        orig = tmp_path / "original.diff"
        pipe = tmp_path / "pipeline.diff"
        content = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"
        orig.write_text(content)
        pipe.write_text(content)
        assert compute_diff_lines(orig, pipe) == 0

    def test_different_diffs(self, tmp_path):
        orig = tmp_path / "original.diff"
        pipe = tmp_path / "pipeline.diff"
        orig.write_text("--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n")
        pipe.write_text("--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+different\n")
        assert compute_diff_lines(orig, pipe) > 0

    def test_missing_pipeline_diff(self, tmp_path):
        orig = tmp_path / "original.diff"
        orig.write_text("content")
        pipe = tmp_path / "pipeline.diff"
        lines = compute_diff_lines(orig, pipe)
        assert lines > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.evaluator'`

- [ ] **Step 3: Implement `evaluator.py`**

```python
# orchestrator/backport_bench/evaluator.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_evaluator.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/evaluator.py orchestrator/tests/test_evaluator.py
git commit -m "feat: add evaluator — JSON parsing, semantic diff, guideline check, diff lines"
```

---

### Task 11: Run Orchestration (`runner.py`)

**Files:**
- Create: `orchestrator/backport_bench/runner.py`
- Create: `orchestrator/tests/test_runner.py`

- [ ] **Step 1: Write failing tests for the runner pipeline**

```python
# orchestrator/tests/test_runner.py
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backport_bench.config import (
    BenchmarkConfig,
    GuidelineCheckConfig,
    SemanticDiffConfig,
    ToolCommands,
    ToolDefinition,
)
from backport_bench.dataset import BackportEntry
from backport_bench.results import RunResult
from backport_bench.runner import execute_run, run_command


class TestRunCommand:
    def test_successful_command(self, tmp_path):
        returncode, stdout, stderr = run_command("echo hello", cwd=tmp_path, env=os.environ.copy(), timeout=10)
        assert returncode == 0
        assert "hello" in stdout

    def test_failed_command(self, tmp_path):
        returncode, stdout, stderr = run_command("exit 1", cwd=tmp_path, env=os.environ.copy(), timeout=10)
        assert returncode != 0

    def test_timeout(self, tmp_path):
        returncode, stdout, stderr = run_command("sleep 10", cwd=tmp_path, env=os.environ.copy(), timeout=1)
        assert returncode == -1
        assert "timeout" in stderr.lower() or "Timeout" in stderr


class TestExecuteRun:
    @pytest.fixture
    def entry(self):
        return BackportEntry(
            repo="owner/repo",
            original_commit="a" * 40,
            backport_commit="b" * 40,
            classification="Easy",
            similarity=1.0,
            file_overlap=1.0,
            size_ratio=1.0,
            orig_files=1,
            back_files=1,
        )

    @pytest.fixture
    def tool(self):
        return ToolDefinition(
            display_name="Test Tool",
            commands=ToolCommands(generate_diff="echo 'diff' > ${PIPELINE_DIFF_PATH}"),
        )

    @pytest.fixture
    def config(self):
        return BenchmarkConfig(
            semantic_diff=SemanticDiffConfig(model="m", command='echo \'{"equivalent": true}\''),
            guideline_check=GuidelineCheckConfig(model="m", command='echo \'{"adheres": true}\''),
            default_tool="test-tool",
            timeout=30,
            verify_tests=False,
            tools={},
        )

    @patch("backport_bench.runner.clone_or_fetch")
    @patch("backport_bench.runner.find_source_branch")
    @patch("backport_bench.runner.setup_target_branch")
    @patch("backport_bench.runner.create_worktree")
    @patch("backport_bench.runner.extract_diff")
    @patch("backport_bench.runner.cleanup")
    def test_successful_run(
        self, mock_cleanup, mock_extract, mock_worktree, mock_setup_target,
        mock_find_branch, mock_clone, entry, tool, config, tmp_path,
    ):
        mock_clone.return_value = tmp_path / "project"
        (tmp_path / "project").mkdir()
        mock_find_branch.return_value = "origin/main"
        mock_extract.return_value = "--- a/f\n+++ b/f\n-old\n+new\n"
        mock_worktree.side_effect = lambda pp, branch, wt: wt.mkdir(parents=True, exist_ok=True)

        result = execute_run(
            entry=entry,
            tool_key="test-tool",
            tool=tool,
            config=config,
            projects_dir=tmp_path / "projects",
            results_dir=tmp_path / "results",
            diffs_dir=tmp_path / "diffs",
            repos_metadata={},
        )

        assert isinstance(result, RunResult)
        assert result.error_message is None or result.semantic_equivalence is not None
        mock_cleanup.assert_called_once()

    @patch("backport_bench.runner.clone_or_fetch")
    @patch("backport_bench.runner.cleanup")
    def test_clone_failure_records_error(
        self, mock_cleanup, mock_clone, entry, tool, config, tmp_path,
    ):
        mock_clone.side_effect = RuntimeError("clone failed")

        result = execute_run(
            entry=entry,
            tool_key="test-tool",
            tool=tool,
            config=config,
            projects_dir=tmp_path / "projects",
            results_dir=tmp_path / "results",
            diffs_dir=tmp_path / "diffs",
            repos_metadata={},
        )

        assert isinstance(result, RunResult)
        assert result.error_message is not None
        assert "clone failed" in result.error_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.runner'`

- [ ] **Step 3: Implement `runner.py`**

```python
# orchestrator/backport_bench/runner.py
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from backport_bench.config import BenchmarkConfig, ToolDefinition
from backport_bench.dataset import BackportEntry, RepoMetadata
from backport_bench.evaluator import compute_diff_lines, parse_json_output, run_guideline_check, run_semantic_diff
from backport_bench.git_ops import cleanup, clone_or_fetch, create_worktree, extract_diff, find_source_branch, setup_target_branch
from backport_bench.results import RunResult, save_result
from backport_bench.variables import build_variable_dict


def run_command(
    command: str, *, cwd: Path, env: dict, timeout: int,
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd, env=env,
            timeout=timeout, capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s"


def execute_run(
    *,
    entry: BackportEntry,
    tool_key: str,
    tool: ToolDefinition,
    config: BenchmarkConfig,
    projects_dir: Path,
    results_dir: Path,
    diffs_dir: Path,
    repos_metadata: dict[str, RepoMetadata],
) -> RunResult:
    start_time = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    repo_owner, repo_name = entry.repo.split("/", 1)
    dir_name = f"{repo_owner}__{repo_name}"
    run_key = f"{entry.original_commit[:8]}-{entry.backport_commit[:8]}"
    project_path = None

    def _make_error_result(error_msg: str) -> RunResult:
        elapsed = time.monotonic() - start_time
        return RunResult(
            tool_display_name=tool.display_name,
            tool_key=tool_key,
            repo=entry.repo,
            original_commit=entry.original_commit,
            backport_commit=entry.backport_commit,
            classification=entry.classification,
            semantic_equivalence=None,
            semantic_difference_reason=None,
            guideline_adherence=None,
            guideline_reason=None,
            test_success=None,
            error_message=error_msg,
            diff_lines=None,
            time_seconds=round(elapsed, 1),
            llm_calls=None,
            cost_usd=None,
            input_tokens=None,
            output_tokens=None,
            timestamp=timestamp,
        )

    try:
        repo_url = f"https://github.com/{entry.repo}.git"
        project_path = clone_or_fetch(repo_url, projects_dir, dir_name)

        source_branch = find_source_branch(project_path, entry.original_commit)
        setup_target_branch(project_path, entry.backport_commit)

        wt_path = project_path / ".worktrees" / run_key
        create_worktree(project_path, "target", wt_path)

        original_diff = extract_diff(project_path, entry.backport_commit)

        diff_tool_dir = Path(diffs_dir) / tool_key / f"{entry.original_commit[:8]}__{entry.backport_commit[:8]}"
        diff_tool_dir.mkdir(parents=True, exist_ok=True)
        orig_diff_path = diff_tool_dir / "original.diff"
        pipe_diff_path = diff_tool_dir / "pipeline.diff"
        orig_diff_path.write_text(original_diff)

        repo_meta = repos_metadata.get(entry.repo)
        build_cmd = repo_meta.build if repo_meta else ""
        test_command = repo_meta.test if repo_meta else ""
        repo_guidelines = repo_meta.guidelines if repo_meta else ""

        env = build_variable_dict(
            repo=entry.repo,
            orig_sha=entry.original_commit,
            backport_sha=entry.backport_commit,
            run_key=run_key,
            project_path=str(project_path),
            source_branch=source_branch,
            target_workspace=str(wt_path),
            original_diff_path=str(orig_diff_path),
            pipeline_diff_path=str(pipe_diff_path),
            build_cmd=build_cmd,
            test_command=test_command,
            repo_guidelines=repo_guidelines,
            tool=tool,
            semantic_diff_model=config.semantic_diff.model,
            guideline_check_model=config.guideline_check.model,
        )

        if tool.commands.setup:
            rc, stdout, stderr = run_command(tool.commands.setup, cwd=wt_path, env=env, timeout=config.timeout)
            if rc != 0:
                return _make_error_result(f"Setup failed (exit {rc}): {stderr[:500]}")

        rc, stdout, stderr = run_command(tool.commands.generate_diff, cwd=wt_path, env=env, timeout=config.timeout)
        if rc == -1:
            return _make_error_result(f"Timeout after {config.timeout}s")
        if rc != 0:
            return _make_error_result(f"generate_diff failed (exit {rc}): {stderr[:500]}")

        sem_rc, sem_stdout, _ = run_command(config.semantic_diff.command, cwd=project_path, env=env, timeout=config.timeout)
        semantic_equivalence, semantic_reason = run_semantic_diff(sem_stdout)

        guideline_adherence = None
        guideline_reason = None
        if repo_guidelines:
            gl_rc, gl_stdout, _ = run_command(config.guideline_check.command, cwd=project_path, env=env, timeout=config.timeout)
            guideline_adherence, guideline_reason = run_guideline_check(gl_stdout)

        test_success = "SKIPPED"

        diff_lines = compute_diff_lines(orig_diff_path, pipe_diff_path)

        llm_calls = None
        cost_usd = None
        input_tokens = None
        output_tokens = None
        tool_time = None

        if tool.commands.get_stats:
            stats_rc, stats_stdout, _ = run_command(tool.commands.get_stats, cwd=wt_path, env=env, timeout=30)
            if stats_rc == 0:
                stats = parse_json_output(stats_stdout)
                if stats:
                    tool_time = stats.get("time")
                    llm_calls = stats.get("llm_calls")
                    cost_usd = stats.get("cost")
                    input_tokens = stats.get("input_tokens")
                    output_tokens = stats.get("output_tokens")

        elapsed = time.monotonic() - start_time

        return RunResult(
            tool_display_name=tool.display_name,
            tool_key=tool_key,
            repo=entry.repo,
            original_commit=entry.original_commit,
            backport_commit=entry.backport_commit,
            classification=entry.classification,
            semantic_equivalence=semantic_equivalence,
            semantic_difference_reason=semantic_reason,
            guideline_adherence=guideline_adherence,
            guideline_reason=guideline_reason,
            test_success=test_success,
            error_message=None,
            diff_lines=diff_lines,
            time_seconds=tool_time if tool_time else round(elapsed, 1),
            llm_calls=llm_calls,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=timestamp,
        )

    except Exception as e:
        return _make_error_result(str(e))

    finally:
        if project_path:
            cleanup(project_path, run_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_runner.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/runner.py orchestrator/tests/test_runner.py
git commit -m "feat: add run orchestration pipeline with timeout and error handling"
```

---

### Task 12: CLI Interface (`cli.py`)

**Files:**
- Create: `orchestrator/backport_bench/cli.py`
- Create: `orchestrator/tests/test_cli.py`

- [ ] **Step 1: Write failing tests using Click's `CliRunner`**

```python
# orchestrator/tests/test_cli.py
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from backport_bench.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCliHelp:
    def test_main_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "backport-bench" in result.output or "Usage" in result.output

    def test_run_help(self, runner):
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--tool" in result.output
        assert "--repo" in result.output
        assert "--classification" in result.output
        assert "--limit" in result.output

    def test_results_help(self, runner):
        result = runner.invoke(cli, ["results", "--help"])
        assert result.exit_code == 0

    def test_leaderboard_help(self, runner):
        result = runner.invoke(cli, ["leaderboard", "--help"])
        assert result.exit_code == 0

    def test_add_backport_help(self, runner):
        result = runner.invoke(cli, ["add-backport", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--original" in result.output
        assert "--backport" in result.output


class TestCliRun:
    def test_missing_config_file(self, runner, tmp_path):
        result = runner.invoke(cli, ["--config", str(tmp_path / "missing.yaml"), "run"])
        assert result.exit_code != 0

    @patch("backport_bench.cli.load_config")
    @patch("backport_bench.cli.load_dataset")
    @patch("backport_bench.cli.execute_run")
    def test_run_skips_existing_results(
        self, mock_execute, mock_load_ds, mock_load_cfg, runner, sample_config_path, sample_csv_path, tmp_results_dir,
    ):
        from backport_bench.config import BenchmarkConfig
        from backport_bench.dataset import BackportEntry

        mock_load_cfg.return_value = BenchmarkConfig(
            semantic_diff={"model": "m", "command": "c"},
            guideline_check={"model": "m", "command": "c"},
            default_tool="test-tool",
            tools={"test-tool": {"display_name": "T", "commands": {"generate_diff": "echo"}}},
        )
        mock_load_ds.return_value = [
            BackportEntry(
                repo="o/r", original_commit="a" * 40, backport_commit="b" * 40,
                classification="Easy", similarity=1.0, file_overlap=1.0,
                size_ratio=1.0, orig_files=1, back_files=1,
            ),
        ]

        existing = tmp_results_dir / "test-tool__o__r__aaaaaaaa__bbbbbbbb.json"
        existing.write_text("{}")

        result = runner.invoke(cli, [
            "--config", str(sample_config_path),
            "run", "--tool", "test-tool",
        ])
        mock_execute.assert_not_called()


class TestCliResults:
    def test_results_with_no_files(self, runner, sample_config_path, tmp_path):
        result = runner.invoke(cli, [
            "--config", str(sample_config_path),
            "results",
        ])
        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backport_bench.cli'`

- [ ] **Step 3: Implement `cli.py`**

```python
# orchestrator/backport_bench/cli.py
from pathlib import Path

import click

from backport_bench.config import load_config
from backport_bench.dataset import (
    BackportEntry,
    filter_dataset,
    load_dataset,
    parse_repos_md,
)
from backport_bench.results import (
    RunResult,
    aggregate_results,
    has_result,
    load_result,
    save_result,
)
from backport_bench.runner import execute_run


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to YAML config file.")
@click.pass_context
def cli(ctx, config):
    """backport-bench: Benchmark orchestrator for automated backporting tools."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config)
    ctx.obj["root"] = _project_root()


@cli.command()
@click.option("--tool", help="Tool key from config. Uses default_tool if omitted.")
@click.option("--repo", help="Filter to a specific repo.")
@click.option("--classification", type=click.Choice(["Easy", "Medium", "Hard"]))
@click.option("--original", help="Filter by original commit SHA.")
@click.option("--backport", help="Filter by backport commit SHA.")
@click.option("--limit", type=int, help="Max entries to run.")
@click.pass_context
def run(ctx, tool, repo, classification, original, backport, limit):
    """Run benchmark against the dataset."""
    config = load_config(ctx.obj["config_path"])
    root = ctx.obj["root"]

    tool_key = tool or config.default_tool
    if tool_key not in config.tools:
        raise click.ClickException(f"Tool '{tool_key}' not found in config.")
    tool_def = config.tools[tool_key]

    dataset = load_dataset(root / "backports.csv")
    entries = filter_dataset(
        dataset, repo=repo, classification=classification,
        original=original, backport=backport, limit=limit,
    )

    if not entries:
        click.echo("No matching entries found.")
        return

    results_dir = root / "results"
    projects_dir = root / "projects"
    diffs_dir = root / "diffs"
    projects_dir.mkdir(exist_ok=True)
    results_dir.mkdir(exist_ok=True)

    repos_metadata = parse_repos_md(root / "repos.md")

    total = len(entries)
    passed = failed = errors = skipped = 0

    for i, entry in enumerate(entries, 1):
        if has_result(tool_key, entry.repo, entry.original_commit, entry.backport_commit, results_dir):
            skipped += 1
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  SKIPPED (exists)")
            continue

        result = execute_run(
            entry=entry, tool_key=tool_key, tool=tool_def, config=config,
            projects_dir=projects_dir, results_dir=results_dir,
            diffs_dir=diffs_dir, repos_metadata=repos_metadata,
        )
        save_result(result, results_dir)

        if result.error_message:
            errors += 1
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  ERROR  ({result.error_message[:60]})")
        elif result.semantic_equivalence == "PASS":
            passed += 1
            cost_str = f"${result.cost_usd:.2f}" if result.cost_usd else ""
            time_str = f"{result.time_seconds:.1f}s" if result.time_seconds else ""
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  PASS  {time_str}  {cost_str}")
        else:
            failed += 1
            reason = result.semantic_difference_reason or ""
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  FAIL  ({reason[:60]})")

    click.echo(f"\nTotal: {total}  Passed: {passed}  Failed: {failed}  Errors: {errors}  Skipped: {skipped}")


@cli.command()
@click.option("--tool", help="Filter by tool key.")
@click.option("--repo", help="Filter by repo.")
@click.option("--classification", type=click.Choice(["Easy", "Medium", "Hard"]))
@click.pass_context
def results(ctx, tool, repo, classification):
    """Display results."""
    root = ctx.obj["root"]
    results_dir = root / "results"
    if not results_dir.exists():
        click.echo("No results found.")
        return

    all_results = []
    for path in results_dir.glob("*.json"):
        if path.parent.name == "aggregated":
            continue
        try:
            all_results.append(load_result(path))
        except Exception:
            continue

    if tool:
        all_results = [r for r in all_results if r.tool_key == tool]
    if repo:
        all_results = [r for r in all_results if r.repo == repo]
    if classification:
        all_results = [r for r in all_results if r.classification == classification]

    if not all_results:
        click.echo("No matching results.")
        return

    click.echo(f"{'Repo':<30} {'Orig':>8} {'Back':>8} {'Class':>6} {'Equiv':>6} {'Guide':>6} {'Cost':>8} {'Time':>8}")
    click.echo("-" * 90)
    for r in all_results:
        cost = f"${r.cost_usd:.2f}" if r.cost_usd else ""
        time_s = f"{r.time_seconds:.1f}s" if r.time_seconds else ""
        click.echo(
            f"{r.repo:<30} {r.original_commit[:8]:>8} {r.backport_commit[:8]:>8} "
            f"{r.classification:>6} {(r.semantic_equivalence or 'N/A'):>6} "
            f"{(r.guideline_adherence or 'N/A'):>6} {cost:>8} {time_s:>8}"
        )


@cli.command()
@click.pass_context
def leaderboard(ctx):
    """Aggregate results and display leaderboard summary."""
    root = ctx.obj["root"]
    results_dir = root / "results"
    aggregate_results(results_dir)
    click.echo("Aggregated results written to results/aggregated/")


@cli.command("add-backport")
@click.option("--repo", required=True, help="Repository (owner/name).")
@click.option("--original", required=True, help="Original commit SHA.")
@click.option("--backport", required=True, help="Backport commit SHA.")
@click.option("--add-repo/--no-add-repo", default=True, help="Auto-detect and add repo metadata.")
@click.pass_context
def add_backport(ctx, repo, original, backport, add_repo):
    """Add a new backport entry to the dataset."""
    click.echo(f"Adding backport: {repo} {original[:8]} → {backport[:8]}")
    click.echo("(add-backport implementation requires git repo access — see Task 13)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_cli.py -v`
Expected: All tests PASS (help tests and basic structure)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/backport_bench/cli.py orchestrator/tests/test_cli.py
git commit -m "feat: add Click CLI with run, results, leaderboard, add-backport subcommands"
```

---

## Phase 2: add-backport and Dataset Write-Back (Task 13)

### Task 13: `add-backport` Full Implementation

**Files:**
- Modify: `orchestrator/backport_bench/dataset.py`
- Modify: `orchestrator/backport_bench/cli.py`
- Modify: `orchestrator/tests/test_dataset.py`

- [ ] **Step 1: Write failing tests for `append_backport` and `append_repo_metadata`**

Append to `orchestrator/tests/test_dataset.py`:

```python
from backport_bench.dataset import append_backport, validate_commit_reachable


class TestAppendBackport:
    def test_appends_to_csv(self, sample_csv_path):
        entry = BackportEntry(
            repo="new/repo",
            original_commit="x" * 40,
            backport_commit="y" * 40,
            classification="Easy",
            similarity=0.95,
            file_overlap=0.90,
            size_ratio=0.98,
            orig_files=2,
            back_files=2,
        )
        append_backport(entry, sample_csv_path)
        reloaded = load_dataset(sample_csv_path)
        assert len(reloaded) == 4
        assert reloaded[-1].repo == "new/repo"

    def test_preserves_existing_entries(self, sample_csv_path):
        original = load_dataset(sample_csv_path)
        entry = BackportEntry(
            repo="new/repo",
            original_commit="x" * 40,
            backport_commit="y" * 40,
            classification="Hard",
            similarity=0.20,
            file_overlap=0.30,
            size_ratio=0.40,
            orig_files=1,
            back_files=1,
        )
        append_backport(entry, sample_csv_path)
        reloaded = load_dataset(sample_csv_path)
        assert len(reloaded) == len(original) + 1
        for i, orig in enumerate(original):
            assert reloaded[i].repo == orig.repo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_dataset.py::TestAppendBackport -v`
Expected: FAIL — `ImportError: cannot import name 'append_backport'`

- [ ] **Step 3: Implement `append_backport` in `dataset.py`**

Add to `orchestrator/backport_bench/dataset.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_dataset.py -v`
Expected: All tests PASS

- [ ] **Step 5: Update `cli.py` `add_backport` command with full implementation**

Replace the placeholder `add_backport` function body in `cli.py`:

```python
@cli.command("add-backport")
@click.option("--repo", required=True, help="Repository (owner/name).")
@click.option("--original", required=True, help="Original commit SHA.")
@click.option("--backport", required=True, help="Backport commit SHA.")
@click.option("--add-repo/--no-add-repo", default=True, help="Auto-detect and add repo metadata.")
@click.pass_context
def add_backport(ctx, repo, original, backport, add_repo):
    """Add a new backport entry to the dataset."""
    from backport_bench.git_ops import clone_or_fetch, extract_diff
    from backport_bench.dataset import (
        append_backport,
        classify_backport,
        compute_metrics,
        validate_commit_reachable,
    )

    root = ctx.obj["root"]
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)

    owner, name = repo.split("/", 1)
    dir_name = f"{owner}__{name}"
    repo_url = f"https://github.com/{repo}.git"

    click.echo(f"Cloning/fetching {repo}...")
    project_path = clone_or_fetch(repo_url, projects_dir, dir_name)

    if not validate_commit_reachable(project_path, original):
        raise click.ClickException(f"Original commit {original} is not reachable from any remote branch.")

    click.echo("Extracting diffs...")
    orig_diff = extract_diff(project_path, original)
    back_diff = extract_diff(project_path, backport)

    metrics = compute_metrics(orig_diff, back_diff)
    classification = classify_backport(
        similarity=metrics["similarity"],
        file_overlap=metrics["file_overlap"],
    )

    click.echo(f"Classification: {classification}")
    click.echo(f"  similarity={metrics['similarity']:.2f}, file_overlap={metrics['file_overlap']:.2f}, "
               f"size_ratio={metrics['size_ratio']:.2f}, orig_files={metrics['orig_files']}, back_files={metrics['back_files']}")

    entry = BackportEntry(
        repo=repo,
        original_commit=original,
        backport_commit=backport,
        classification=classification,
        **metrics,
    )
    append_backport(entry, root / "backports.csv")
    click.echo(f"Appended to backports.csv")
```

- [ ] **Step 6: Run all tests**

Run: `cd orchestrator && pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add orchestrator/backport_bench/dataset.py orchestrator/backport_bench/cli.py orchestrator/tests/test_dataset.py
git commit -m "feat: implement add-backport with classification, metrics, and CSV append"
```

---

## Phase 3: Leaderboard App (Tasks 14–15)

### Task 14: Leaderboard Scaffolding and Data Loading

**Files:**
- Create: `leaderboard/pyproject.toml`
- Create: `leaderboard/data_loader.py`
- Create: `leaderboard/about.md`
- Create: `leaderboard/tests/__init__.py`
- Create: `leaderboard/tests/conftest.py`
- Create: `leaderboard/tests/test_data_loader.py`

- [ ] **Step 1: Create `leaderboard/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "backport-bench-leaderboard"
version = "0.1.0"
description = "Gradio leaderboard app for Backport Agent benchmarks"
requires-python = ">=3.12"
dependencies = [
    "gradio>=4.0",
    "pandas>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `leaderboard/about.md`**

```markdown
# About the Backport Agent Leaderboard

This leaderboard evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects.

## How It Works

1. Each tool is given an original commit and a target branch
2. The tool produces a candidate backport diff
3. The diff is compared to the known-good backport for semantic equivalence
4. Results are aggregated by tool and benchmark subset

## Metrics

- **Score**: Percentage of backports where the tool produced a semantically equivalent diff
- **Avg Cost Per Task**: Mean LLM API cost in USD per backport
- **Avg Seconds Per Task**: Mean wall-clock time per backport
- **Avg Input/Output Tokens**: Mean token usage per backport

## Submitting Results

Results are stored as JSON files. Contact the maintainers to submit benchmark results for a new tool.
```

- [ ] **Step 3: Create test fixtures**

```python
# leaderboard/tests/__init__.py
```

```python
# leaderboard/tests/conftest.py
import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_aggregated_dir(tmp_path):
    agg_dir = tmp_path / "aggregated"
    agg_dir.mkdir()

    result_1 = {
        "benchmark": {"name": "backportbench-owner-repo-a", "repo": "owner/repo-a", "num_tasks": 10, "url": ""},
        "tool": {"display_name": "Tool A", "is_oss": True, "url": ""},
        "metrics": {
            "score": 0.80, "n_tasks": 10, "n_errors": 1,
            "n_input_tokens": 2000000, "n_output_tokens": 48000,
            "n_total_tokens": 2048000, "total_time_seconds": 1800,
            "cost_usd": 7.40, "mean_input_tokens_per_task": 200000,
            "mean_output_tokens_per_task": 4800, "mean_cost_usd_per_task": 0.74,
            "mean_time_seconds_per_task": 180.0,
        },
    }
    result_2 = {
        "benchmark": {"name": "backportbench-owner-repo-a", "repo": "owner/repo-a", "num_tasks": 10, "url": ""},
        "tool": {"display_name": "Tool B", "is_oss": False, "url": ""},
        "metrics": {
            "score": 0.60, "n_tasks": 10, "n_errors": 2,
            "n_input_tokens": 3000000, "n_output_tokens": 60000,
            "n_total_tokens": 3060000, "total_time_seconds": 2400,
            "cost_usd": 12.00, "mean_input_tokens_per_task": 300000,
            "mean_output_tokens_per_task": 6000, "mean_cost_usd_per_task": 1.20,
            "mean_time_seconds_per_task": 240.0,
        },
    }
    result_3 = {
        "benchmark": {"name": "backportbench-other-repo-b", "repo": "other/repo-b", "num_tasks": 5, "url": ""},
        "tool": {"display_name": "Tool A", "is_oss": True, "url": ""},
        "metrics": {
            "score": 0.60, "n_tasks": 5, "n_errors": 0,
            "n_input_tokens": 1000000, "n_output_tokens": 24000,
            "n_total_tokens": 1024000, "total_time_seconds": 900,
            "cost_usd": 3.70, "mean_input_tokens_per_task": 200000,
            "mean_output_tokens_per_task": 4800, "mean_cost_usd_per_task": 0.74,
            "mean_time_seconds_per_task": 180.0,
        },
    }

    (agg_dir / "tool_a__owner-repo-a.json").write_text(json.dumps(result_1))
    (agg_dir / "tool_b__owner-repo-a.json").write_text(json.dumps(result_2))
    (agg_dir / "tool_a__other-repo-b.json").write_text(json.dumps(result_3))

    return agg_dir
```

- [ ] **Step 4: Write failing tests for `data_loader.py`**

```python
# leaderboard/tests/test_data_loader.py
import pytest
import pandas as pd

from data_loader import load_results, build_leaderboard_df, build_runs_df


class TestLoadResults:
    def test_loads_all_files(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        assert len(results) == 3

    def test_result_structure(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        for r in results:
            assert "benchmark" in r
            assert "tool" in r
            assert "metrics" in r

    def test_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        results = load_results(empty_dir)
        assert results == []


class TestBuildLeaderboardDf:
    def test_one_row_per_tool(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_leaderboard_df(results)
        assert len(df) == 2

    def test_columns_include_avg_score(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_leaderboard_df(results)
        assert "Avg Score" in df.columns

    def test_sorted_by_avg_score_desc(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_leaderboard_df(results)
        scores = df["Avg Score"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_per_benchmark_columns(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_leaderboard_df(results)
        assert "owner/repo-a" in df.columns


class TestBuildRunsDf:
    def test_one_row_per_result(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_runs_df(results)
        assert len(df) == 3

    def test_expected_columns(self, sample_aggregated_dir):
        results = load_results(sample_aggregated_dir)
        df = build_runs_df(results)
        for col in ["Category", "Name", "Benchmark", "Score", "Avg Cost Per Task"]:
            assert col in df.columns
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd leaderboard && pip install -e ".[dev]" && pytest tests/test_data_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data_loader'`

- [ ] **Step 6: Implement `data_loader.py`**

```python
# leaderboard/data_loader.py
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


def load_results(results_dir: Path) -> list[dict]:
    results_dir = Path(results_dir)
    results = []
    for path in sorted(results_dir.glob("*.json")):
        with open(path) as f:
            results.append(json.load(f))
    return results


def build_leaderboard_df(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    tool_scores: dict[str, dict] = defaultdict(lambda: {"scores": {}, "is_oss": True})

    for r in results:
        name = r["tool"]["display_name"]
        benchmark = r["benchmark"]["repo"]
        score = r["metrics"]["score"]
        tool_scores[name]["scores"][benchmark] = score
        tool_scores[name]["is_oss"] = r["tool"].get("is_oss", True)

    rows = []
    for name, data in tool_scores.items():
        scores = data["scores"]
        avg = sum(scores.values()) / len(scores) if scores else 0
        row = {
            "Category": "Open Source" if data["is_oss"] else "Proprietary",
            "Name": name,
            "Avg Score": round(avg, 4),
        }
        row.update(scores)
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values("Avg Score", ascending=False).reset_index(drop=True)
    return df


def build_runs_df(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    rows = []
    for r in results:
        rows.append({
            "Category": "Open Source" if r["tool"].get("is_oss", True) else "Proprietary",
            "Name": r["tool"]["display_name"],
            "Benchmark": r["benchmark"]["repo"],
            "Score": r["metrics"]["score"],
            "Avg Cost Per Task": r["metrics"].get("mean_cost_usd_per_task", 0),
            "Avg Seconds Per Task": r["metrics"].get("mean_time_seconds_per_task", 0),
            "Avg Input Tokens Per Task": r["metrics"].get("mean_input_tokens_per_task", 0),
            "Avg Output Tokens Per Task": r["metrics"].get("mean_output_tokens_per_task", 0),
        })

    return pd.DataFrame(rows)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd leaderboard && pytest tests/test_data_loader.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add leaderboard/
git commit -m "feat: scaffold leaderboard package with data loader and tests"
```

---

### Task 15: Gradio App (`app.py`)

**Files:**
- Create: `leaderboard/app.py`
- Create: `leaderboard/tests/test_app.py`

- [ ] **Step 1: Write failing tests for app creation**

```python
# leaderboard/tests/test_app.py
import pytest

from app import create_app


class TestCreateApp:
    def test_returns_gradio_blocks(self, sample_aggregated_dir):
        app = create_app(results_dir=sample_aggregated_dir)
        assert app is not None
        assert hasattr(app, "launch")

    def test_creates_with_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        app = create_app(results_dir=empty)
        assert app is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd leaderboard && pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement `app.py`**

```python
# leaderboard/app.py
import os
from pathlib import Path

import gradio as gr

from data_loader import build_leaderboard_df, build_runs_df, load_results

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "aggregated"


def create_app(results_dir: Path | None = None) -> gr.Blocks:
    results_dir = Path(results_dir or DEFAULT_RESULTS_DIR)

    def load_data():
        results = load_results(results_dir)
        leaderboard_df = build_leaderboard_df(results)
        runs_df = build_runs_df(results)
        n_results = len(results)
        n_tools = leaderboard_df["Name"].nunique() if not leaderboard_df.empty else 0
        return leaderboard_df, runs_df, n_results, n_tools

    with gr.Blocks(title="Backport Agent Leaderboard") as app:
        gr.Markdown("# Backport Agent Leaderboard")

        leaderboard_df, runs_df, n_results, n_tools = load_data()

        gr.Markdown(
            f"**{n_results}** benchmark runs | **{n_tools}** tools"
        )

        with gr.Tabs():
            with gr.TabItem("Leaderboard"):
                search_box = gr.Textbox(label="Search by name", placeholder="Type to filter...")
                category_filter = gr.CheckboxGroup(
                    choices=["Open Source", "Proprietary"],
                    value=["Open Source", "Proprietary"],
                    label="Category",
                )
                leaderboard_table = gr.Dataframe(
                    value=leaderboard_df,
                    interactive=False,
                    wrap=True,
                )

            with gr.TabItem("Benchmark Runs"):
                default_cols = ["Category", "Name", "Benchmark", "Score", "Avg Cost Per Task"]
                all_cols = list(runs_df.columns) if not runs_df.empty else default_cols
                extra_cols = [c for c in all_cols if c not in default_cols]
                column_picker = gr.CheckboxGroup(
                    choices=extra_cols,
                    value=[],
                    label="Additional columns",
                )
                runs_table = gr.Dataframe(
                    value=runs_df[default_cols] if not runs_df.empty else runs_df,
                    interactive=False,
                    wrap=True,
                )

            with gr.TabItem("About"):
                about_path = Path(__file__).parent / "about.md"
                if about_path.exists():
                    gr.Markdown(about_path.read_text())
                else:
                    gr.Markdown("About content not available.")

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd leaderboard && pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add leaderboard/app.py leaderboard/tests/test_app.py
git commit -m "feat: add Gradio leaderboard app with tabs, filters, and auto-refresh"
```

---

## Phase 4: BDD Tests (Task 16)

### Task 16: BDD Feature Files and Step Definitions

**Files:**
- Create: `orchestrator/tests/bdd/features/run_benchmark.feature`
- Create: `orchestrator/tests/bdd/features/add_backport.feature`
- Create: `orchestrator/tests/bdd/features/resume.feature`
- Create: `orchestrator/tests/bdd/step_defs/test_run_benchmark.py`
- Create: `orchestrator/tests/bdd/step_defs/test_add_backport.py`
- Create: `orchestrator/tests/bdd/step_defs/test_resume.py`
- Create: `orchestrator/tests/bdd/conftest.py`

- [ ] **Step 1: Create BDD directory structure**

```bash
mkdir -p orchestrator/tests/bdd/features orchestrator/tests/bdd/step_defs
touch orchestrator/tests/bdd/__init__.py orchestrator/tests/bdd/step_defs/__init__.py
```

- [ ] **Step 2: Write feature file for benchmark run**

```gherkin
# orchestrator/tests/bdd/features/run_benchmark.feature
Feature: Run benchmark
  As a benchmark operator
  I want to run a backporting tool against the dataset
  So that I can evaluate its effectiveness

  Scenario: Successful benchmark run
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "test-tool" configured with a generate_diff command
    And a config file with the tool registered
    When I run the benchmark with tool "test-tool"
    Then a result file should be created
    And the result should have a non-null timestamp
    And the result should have tool_key "test-tool"

  Scenario: Tool timeout
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "slow-tool" with a generate_diff command that sleeps for 10 seconds
    And a config file with timeout set to 1 second
    When I run the benchmark with tool "slow-tool"
    Then the result should have an error message containing "Timeout"

  Scenario: Setup command failure
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "broken-tool" with a setup command that exits with code 1
    And a config file with the tool registered
    When I run the benchmark with tool "broken-tool"
    Then the result should have an error message containing "Setup failed"
```

- [ ] **Step 3: Write feature file for add-backport**

```gherkin
# orchestrator/tests/bdd/features/add_backport.feature
Feature: Add backport entry
  As a benchmark curator
  I want to add new backport entries to the dataset
  So that the benchmark covers more cases

  Scenario: Classification as Easy
    Given diffs with similarity 0.95 and file_overlap 0.90
    When I compute the classification
    Then the classification should be "Easy"

  Scenario: Classification as Medium
    Given diffs with similarity 0.75 and file_overlap 0.60
    When I compute the classification
    Then the classification should be "Medium"

  Scenario: Classification as Hard
    Given diffs with similarity 0.30 and file_overlap 0.30
    When I compute the classification
    Then the classification should be "Hard"

  Scenario: Append entry to CSV
    Given an existing dataset with 3 entries
    When I append a new backport entry
    Then the dataset should have 4 entries
    And the last entry should match the appended data
```

- [ ] **Step 4: Write feature file for resume**

```gherkin
# orchestrator/tests/bdd/features/resume.feature
Feature: Resume benchmark run
  As a benchmark operator
  I want to resume an interrupted benchmark
  So that I don't re-run entries that already have results

  Scenario: Skip entry with existing result
    Given a dataset with 2 backport entries
    And a result file already exists for the first entry
    When I run the benchmark
    Then only the second entry should be executed
    And the first entry should be reported as skipped
```

- [ ] **Step 5: Write BDD conftest**

```python
# orchestrator/tests/bdd/conftest.py
import csv
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, then, when

from backport_bench.config import BenchmarkConfig, ToolCommands, ToolDefinition
from backport_bench.dataset import BackportEntry


@pytest.fixture
def bdd_context():
    return {}
```

- [ ] **Step 6: Write step definitions for `run_benchmark`**

```python
# orchestrator/tests/bdd/step_defs/test_run_benchmark.py
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from backport_bench.config import (
    BenchmarkConfig,
    GuidelineCheckConfig,
    SemanticDiffConfig,
    ToolCommands,
    ToolDefinition,
)
from backport_bench.dataset import BackportEntry
from backport_bench.results import RunResult
from backport_bench.runner import execute_run


@scenario("../features/run_benchmark.feature", "Successful benchmark run")
def test_successful_run():
    pass


@scenario("../features/run_benchmark.feature", "Tool timeout")
def test_tool_timeout():
    pass


@scenario("../features/run_benchmark.feature", "Setup command failure")
def test_setup_failure():
    pass


@given(parsers.parse('a dataset with 1 "{classification}" backport entry for "{repo}"'))
def dataset_with_entry(bdd_context, classification, repo):
    bdd_context["entry"] = BackportEntry(
        repo=repo,
        original_commit="a" * 40,
        backport_commit="b" * 40,
        classification=classification,
        similarity=1.0,
        file_overlap=1.0,
        size_ratio=1.0,
        orig_files=1,
        back_files=1,
    )


@given(parsers.parse('a tool "{tool_key}" configured with a generate_diff command'))
def tool_with_generate_diff(bdd_context, tool_key):
    bdd_context["tool_key"] = tool_key
    bdd_context["tool"] = ToolDefinition(
        display_name=f"Test {tool_key}",
        commands=ToolCommands(generate_diff="echo 'mock diff' > ${PIPELINE_DIFF_PATH}"),
    )


@given(parsers.parse('a tool "{tool_key}" with a generate_diff command that sleeps for {seconds:d} seconds'))
def tool_with_sleep(bdd_context, tool_key, seconds):
    bdd_context["tool_key"] = tool_key
    bdd_context["tool"] = ToolDefinition(
        display_name=f"Test {tool_key}",
        commands=ToolCommands(generate_diff=f"sleep {seconds}"),
    )


@given(parsers.parse('a tool "{tool_key}" with a setup command that exits with code {code:d}'))
def tool_with_failing_setup(bdd_context, tool_key, code):
    bdd_context["tool_key"] = tool_key
    bdd_context["tool"] = ToolDefinition(
        display_name=f"Test {tool_key}",
        commands=ToolCommands(
            setup=f"exit {code}",
            generate_diff="echo 'should not run'",
        ),
    )


@given("a config file with the tool registered")
def config_with_tool(bdd_context):
    bdd_context["config"] = BenchmarkConfig(
        semantic_diff=SemanticDiffConfig(model="m", command='echo \'{"equivalent": true}\''),
        guideline_check=GuidelineCheckConfig(model="m", command='echo \'{"adheres": true}\''),
        default_tool=bdd_context["tool_key"],
        timeout=30,
        verify_tests=False,
        tools={bdd_context["tool_key"]: bdd_context["tool"]},
    )


@given(parsers.parse("a config file with timeout set to {seconds:d} second"))
def config_with_timeout(bdd_context, seconds):
    bdd_context["config"] = BenchmarkConfig(
        semantic_diff=SemanticDiffConfig(model="m", command='echo \'{"equivalent": true}\''),
        guideline_check=GuidelineCheckConfig(model="m", command='echo \'{"adheres": true}\''),
        default_tool=bdd_context["tool_key"],
        timeout=seconds,
        verify_tests=False,
        tools={bdd_context["tool_key"]: bdd_context["tool"]},
    )


@when(parsers.parse('I run the benchmark with tool "{tool_key}"'))
def run_benchmark(bdd_context, tmp_path):
    with (
        patch("backport_bench.runner.clone_or_fetch") as mock_clone,
        patch("backport_bench.runner.find_source_branch") as mock_branch,
        patch("backport_bench.runner.setup_target_branch"),
        patch("backport_bench.runner.create_worktree") as mock_wt,
        patch("backport_bench.runner.extract_diff") as mock_extract,
        patch("backport_bench.runner.cleanup"),
    ):
        project = tmp_path / "project"
        project.mkdir()
        mock_clone.return_value = project
        mock_branch.return_value = "origin/main"
        mock_extract.return_value = "--- a/f\n+++ b/f\n-old\n+new\n"
        mock_wt.side_effect = lambda pp, branch, wt: wt.mkdir(parents=True, exist_ok=True)

        result = execute_run(
            entry=bdd_context["entry"],
            tool_key=bdd_context["tool_key"],
            tool=bdd_context["tool"],
            config=bdd_context["config"],
            projects_dir=tmp_path / "projects",
            results_dir=tmp_path / "results",
            diffs_dir=tmp_path / "diffs",
            repos_metadata={},
        )
        bdd_context["result"] = result


@then("a result file should be created")
def check_result_created(bdd_context):
    assert isinstance(bdd_context["result"], RunResult)


@then("the result should have a non-null timestamp")
def check_timestamp(bdd_context):
    assert bdd_context["result"].timestamp is not None


@then(parsers.parse('the result should have tool_key "{expected}"'))
def check_tool_key(bdd_context, expected):
    assert bdd_context["result"].tool_key == expected


@then(parsers.parse('the result should have an error message containing "{text}"'))
def check_error_message(bdd_context, text):
    assert bdd_context["result"].error_message is not None
    assert text.lower() in bdd_context["result"].error_message.lower()
```

- [ ] **Step 7: Write step definitions for `add_backport`**

```python
# orchestrator/tests/bdd/step_defs/test_add_backport.py
import csv
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from backport_bench.dataset import (
    BackportEntry,
    append_backport,
    classify_backport,
    load_dataset,
)


@scenario("../features/add_backport.feature", "Classification as Easy")
def test_classify_easy():
    pass


@scenario("../features/add_backport.feature", "Classification as Medium")
def test_classify_medium():
    pass


@scenario("../features/add_backport.feature", "Classification as Hard")
def test_classify_hard():
    pass


@scenario("../features/add_backport.feature", "Append entry to CSV")
def test_append_entry():
    pass


@given(parsers.parse("diffs with similarity {sim:f} and file_overlap {overlap:f}"))
def diffs_with_metrics(bdd_context, sim, overlap):
    bdd_context["similarity"] = sim
    bdd_context["file_overlap"] = overlap


@when("I compute the classification")
def compute_classification(bdd_context):
    bdd_context["classification"] = classify_backport(
        similarity=bdd_context["similarity"],
        file_overlap=bdd_context["file_overlap"],
    )


@then(parsers.parse('the classification should be "{expected}"'))
def check_classification(bdd_context, expected):
    assert bdd_context["classification"] == expected


@given(parsers.parse("an existing dataset with {count:d} entries"))
def existing_dataset(bdd_context, count, sample_csv_path):
    bdd_context["csv_path"] = sample_csv_path
    entries = load_dataset(sample_csv_path)
    assert len(entries) == count


@when("I append a new backport entry")
def append_entry(bdd_context):
    entry = BackportEntry(
        repo="new/repo",
        original_commit="x" * 40,
        backport_commit="y" * 40,
        classification="Easy",
        similarity=0.95,
        file_overlap=0.90,
        size_ratio=0.98,
        orig_files=2,
        back_files=2,
    )
    bdd_context["appended_entry"] = entry
    append_backport(entry, bdd_context["csv_path"])


@then(parsers.parse("the dataset should have {count:d} entries"))
def check_dataset_count(bdd_context, count):
    entries = load_dataset(bdd_context["csv_path"])
    assert len(entries) == count


@then("the last entry should match the appended data")
def check_last_entry(bdd_context):
    entries = load_dataset(bdd_context["csv_path"])
    last = entries[-1]
    expected = bdd_context["appended_entry"]
    assert last.repo == expected.repo
    assert last.original_commit == expected.original_commit
```

- [ ] **Step 8: Write step definitions for `resume`**

```python
# orchestrator/tests/bdd/step_defs/test_resume.py
from pathlib import Path
from unittest.mock import patch, call

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from backport_bench.config import (
    BenchmarkConfig,
    GuidelineCheckConfig,
    SemanticDiffConfig,
    ToolCommands,
    ToolDefinition,
)
from backport_bench.dataset import BackportEntry
from backport_bench.results import RunResult, has_result, save_result


@scenario("../features/resume.feature", "Skip entry with existing result")
def test_resume_skip():
    pass


@given("a dataset with 2 backport entries")
def dataset_with_two(bdd_context):
    bdd_context["entries"] = [
        BackportEntry(
            repo="owner/repo", original_commit="a" * 40, backport_commit="b" * 40,
            classification="Easy", similarity=1.0, file_overlap=1.0,
            size_ratio=1.0, orig_files=1, back_files=1,
        ),
        BackportEntry(
            repo="owner/repo", original_commit="c" * 40, backport_commit="d" * 40,
            classification="Medium", similarity=0.75, file_overlap=0.60,
            size_ratio=0.80, orig_files=2, back_files=2,
        ),
    ]


@given("a result file already exists for the first entry")
def existing_result(bdd_context, tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    bdd_context["results_dir"] = results_dir
    result = RunResult(
        tool_display_name="T", tool_key="tool",
        repo="owner/repo", original_commit="a" * 40, backport_commit="b" * 40,
        classification="Easy", semantic_equivalence="PASS",
        semantic_difference_reason=None, guideline_adherence=None,
        guideline_reason=None, test_success="SKIPPED",
        error_message=None, diff_lines=0, time_seconds=10.0,
        llm_calls=1, cost_usd=0.10, input_tokens=1000,
        output_tokens=100, timestamp="2026-06-26T00:00:00Z",
    )
    save_result(result, results_dir)


@when("I run the benchmark")
def run_with_resume(bdd_context, tmp_path):
    entries = bdd_context["entries"]
    results_dir = bdd_context["results_dir"]
    bdd_context["executed"] = []
    bdd_context["skipped"] = []

    for entry in entries:
        if has_result("tool", entry.repo, entry.original_commit, entry.backport_commit, results_dir):
            bdd_context["skipped"].append(entry)
        else:
            bdd_context["executed"].append(entry)


@then("only the second entry should be executed")
def check_only_second(bdd_context):
    assert len(bdd_context["executed"]) == 1
    assert bdd_context["executed"][0].original_commit == "c" * 40


@then("the first entry should be reported as skipped")
def check_first_skipped(bdd_context):
    assert len(bdd_context["skipped"]) == 1
    assert bdd_context["skipped"][0].original_commit == "a" * 40
```

- [ ] **Step 9: Run all BDD tests**

Run: `cd orchestrator && pytest tests/bdd/ -v`
Expected: All BDD tests PASS

- [ ] **Step 10: Commit**

```bash
git add orchestrator/tests/bdd/
git commit -m "feat: add BDD feature files and step definitions for run, add-backport, resume"
```

---

## Phase 5: Code Review and Documentation (Tasks 17–18)

### Task 17: Code Review Checkpoint

This is a manual review task, not a coding task.

- [ ] **Step 1: Run full test suite**

Run: `cd orchestrator && pytest -v --tb=short && cd ../leaderboard && pytest -v --tb=short`
Expected: All tests PASS in both packages

- [ ] **Step 2: Review checklist**

Verify each item:

- [ ] All Pydantic models match the design spec field names and types (Section 2)
- [ ] `BackportEntry` fields match the CSV column names (Section 3)
- [ ] Filter application order matches spec: repo → classification → SHA → limit (Section 3)
- [ ] Classification thresholds match spec: Easy ≥0.90/≥0.80, Medium ≥0.50 OR ≥0.50, Hard else (Section 3)
- [ ] Git operations use subprocess (no GitPython) per Decision #7
- [ ] Worktree path is `<project>/.worktrees/<run_key>` per Decision #8
- [ ] Target branch created at `backport_sha^` per Decision #9
- [ ] Result filename format is `<tool-key>__<owner>__<repo>__<orig-8>__<backport-8>.json` (Section 7)
- [ ] Aggregated JSON matches PRD's result data format (Section 7 / FR-6)
- [ ] CLI subcommands match spec: `run`, `results`, `leaderboard`, `add-backport` (Section 8)
- [ ] CLI flags match spec: `--tool`, `--repo`, `--classification`, `--original`, `--backport`, `--limit` (Section 8)
- [ ] Variable names match spec: `REPO`, `ORIG_SHA`, `BACKPORT_SHA`, etc. (Section 2)
- [ ] `CONFIG_` prefix applied to tool config keys (Section 2)
- [ ] JSON parser uses brace-matching extraction per Decision #14
- [ ] Resume check uses file existence per Decision #15
- [ ] Cleanup runs in `finally` block (Section 5)
- [ ] Error resilience: entire `execute_run` wrapped in try/except (Section 5)
- [ ] No `rich` or heavy terminal UI per Decision #20

- [ ] **Step 3: Run linting**

Run: `cd orchestrator && python -m py_compile backport_bench/cli.py && python -m py_compile backport_bench/config.py && python -m py_compile backport_bench/dataset.py && python -m py_compile backport_bench/evaluator.py && python -m py_compile backport_bench/git_ops.py && python -m py_compile backport_bench/results.py && python -m py_compile backport_bench/runner.py && python -m py_compile backport_bench/variables.py`
Expected: No syntax errors

- [ ] **Step 4: Document any issues found and fix them**

If issues are found, create targeted fix commits before proceeding.

---

### Task 18: Documentation

**Files:**
- Modify: `README.md`
- Create: `orchestrator/README.md`
- Create: `leaderboard/README.md`
- Create: `config.example.yaml`

- [ ] **Step 1: Create `config.example.yaml`**

```yaml
# Backport Bench — Example Configuration
# Copy to config.yaml and customize for your environment.

semantic_diff:
  model: "claude-opus-4-6"
  command: |
    claude -m ${SEMANTIC_DIFF_MODEL} -p "Compare @${ORIGINAL_DIFF_PATH} and @${PIPELINE_DIFF_PATH} and determine if they are semantically equivalent.
    Respond with a single JSON object and no other text:
    - If equivalent: {\"equivalent\": true}
    - If not equivalent: {\"equivalent\": false, \"reason\": \"<brief explanation>\"}"

guideline_check:
  model: "claude-opus-4-6"
  command: |
    claude -m ${GUIDELINE_CHECK_MODEL} -p "Review @${PIPELINE_DIFF_PATH} against the following contributing guidelines: ${REPO_GUIDELINES}
    Respond with a single JSON object and no other text:
    - If adheres: {\"adheres\": true}
    - If not adheres: {\"adheres\": false, \"reason\": \"<brief explanation>\"}"

default_tool: "my-tool"
timeout: 1800
verify_tests: false

tools:
  my-tool:
    display_name: "My Tool / Opus 4.6"
    model: "claude-opus-4-6"
    config:
      tool_location: "/path/to/my-tool"
    commands:
      setup: |
        echo "Setting up..."
      generate_diff: |
        echo "Running tool..." &&
        my-tool generate --config ${CONFIG_TOOL_LOCATION} \
          --repo ${REPO} --sha ${ORIG_SHA} \
          --workspace ${TARGET_WORKSPACE} \
          --output ${PIPELINE_DIFF_PATH}
      get_stats: |
        cat /tmp/my-tool-stats.json
```

- [ ] **Step 2: Update root `README.md` with quickstart**

Update `README.md` to include:
- Project overview (1 paragraph)
- Prerequisites (Python 3.12+)
- Installation commands for both packages
- Quick-start CLI usage (run, results, leaderboard, add-backport)
- Link to `config.example.yaml`
- Link to PRD and design spec

- [ ] **Step 3: Create `orchestrator/README.md`**

Contents:
- Package description
- Installation: `pip install -e ".[dev]"`
- CLI reference (all subcommands with flags)
- Config file reference (link to `config.example.yaml`)
- Running tests: `pytest -v`

- [ ] **Step 4: Create `leaderboard/README.md`**

Contents:
- Package description
- Installation: `pip install -e ".[dev]"`
- Running locally: `python app.py`
- Deployment options (HuggingFace Spaces, Docker)
- Running tests: `pytest -v`

- [ ] **Step 5: Commit**

```bash
git add README.md orchestrator/README.md leaderboard/README.md config.example.yaml
git commit -m "docs: add README files and example config"
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 — Orchestrator Core | 1–12 | Scaffolding, config, dataset, git ops, variables, evaluator, results, runner, CLI |
| 2 — Add-Backport | 13 | Full add-backport with classification and CSV write-back |
| 3 — Leaderboard | 14–15 | Data loader, Gradio app with tabs and filters |
| 4 — BDD Tests | 16 | Feature files and step definitions for key workflows |
| 5 — Review & Docs | 17–18 | Code review checkpoint, READMEs, example config |

**Total tasks:** 18
**Total test files:** 11 (8 unit test files, 3 BDD step definition files)
**Total feature files:** 3 (run_benchmark, add_backport, resume)
