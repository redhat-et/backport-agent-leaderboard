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
