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
