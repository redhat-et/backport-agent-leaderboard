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
