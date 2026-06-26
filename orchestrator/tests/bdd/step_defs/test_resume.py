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
