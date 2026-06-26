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
