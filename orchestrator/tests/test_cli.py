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


class TestCliResults:
    def test_results_with_no_files(self, runner, sample_config_path, tmp_path):
        result = runner.invoke(cli, [
            "--config", str(sample_config_path),
            "results",
        ])
        assert result.exit_code == 0
