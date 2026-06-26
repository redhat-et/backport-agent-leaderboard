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
