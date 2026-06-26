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
