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
