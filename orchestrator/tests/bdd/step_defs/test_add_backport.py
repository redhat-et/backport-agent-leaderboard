import csv
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from backport_bench.dataset import (
    BackportEntry,
    append_backport,
    classify_backport,
    load_dataset,
)


@scenario("../features/add_backport.feature", "Classification as Easy")
def test_classify_easy():
    pass


@scenario("../features/add_backport.feature", "Classification as Medium")
def test_classify_medium():
    pass


@scenario("../features/add_backport.feature", "Classification as Hard")
def test_classify_hard():
    pass


@scenario("../features/add_backport.feature", "Append entry to CSV")
def test_append_entry():
    pass


@given(parsers.parse("diffs with similarity {sim:f} and file_overlap {overlap:f}"))
def diffs_with_metrics(bdd_context, sim, overlap):
    bdd_context["similarity"] = sim
    bdd_context["file_overlap"] = overlap


@when("I compute the classification")
def compute_classification(bdd_context):
    bdd_context["classification"] = classify_backport(
        similarity=bdd_context["similarity"],
        file_overlap=bdd_context["file_overlap"],
    )


@then(parsers.parse('the classification should be "{expected}"'))
def check_classification(bdd_context, expected):
    assert bdd_context["classification"] == expected


@given(parsers.parse("an existing dataset with {count:d} entries"))
def existing_dataset(bdd_context, count, sample_csv_path):
    bdd_context["csv_path"] = sample_csv_path
    entries = load_dataset(sample_csv_path)
    assert len(entries) == count


@when("I append a new backport entry")
def append_entry(bdd_context):
    entry = BackportEntry(
        repo="new/repo",
        original_commit="x" * 40,
        backport_commit="y" * 40,
        classification="Easy",
        similarity=0.95,
        file_overlap=0.90,
        size_ratio=0.98,
        orig_files=2,
        back_files=2,
    )
    bdd_context["appended_entry"] = entry
    append_backport(entry, bdd_context["csv_path"])


@then(parsers.parse("the dataset should have {count:d} entries"))
def check_dataset_count(bdd_context, count):
    entries = load_dataset(bdd_context["csv_path"])
    assert len(entries) == count


@then("the last entry should match the appended data")
def check_last_entry(bdd_context):
    entries = load_dataset(bdd_context["csv_path"])
    last = entries[-1]
    expected = bdd_context["appended_entry"]
    assert last.repo == expected.repo
    assert last.original_commit == expected.original_commit
