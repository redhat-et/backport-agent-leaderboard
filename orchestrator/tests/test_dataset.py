import csv
from pathlib import Path

import pytest

from backport_bench.dataset import BackportEntry, load_dataset, parse_reason, filter_dataset, classify_backport, compute_metrics


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
        filtered = filter_dataset(entries, original="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111")
        assert len(filtered) == 1

    def test_filter_by_backport_sha(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, backport="dddd4444dddd4444dddd4444dddd4444dddd4444")
        assert len(filtered) == 1

    def test_filter_combined_original_and_backport(self, sample_csv_path):
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, original="aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111", backport="bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222")
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
        entries = load_dataset(sample_csv_path)
        filtered = filter_dataset(entries, repo="owner/repo-a", limit=1)
        assert len(filtered) == 1
        assert filtered[0].classification == "Easy"


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
