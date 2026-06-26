import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_aggregated_dir(tmp_path):
    agg_dir = tmp_path / "aggregated"
    agg_dir.mkdir()

    result_1 = {
        "benchmark": {"name": "backportbench-owner-repo-a", "repo": "owner/repo-a", "num_tasks": 10, "url": ""},
        "tool": {"display_name": "Tool A", "is_oss": True, "url": ""},
        "metrics": {
            "score": 0.80, "n_tasks": 10, "n_errors": 1,
            "n_input_tokens": 2000000, "n_output_tokens": 48000,
            "n_total_tokens": 2048000, "total_time_seconds": 1800,
            "cost_usd": 7.40, "mean_input_tokens_per_task": 200000,
            "mean_output_tokens_per_task": 4800, "mean_cost_usd_per_task": 0.74,
            "mean_time_seconds_per_task": 180.0,
        },
    }
    result_2 = {
        "benchmark": {"name": "backportbench-owner-repo-a", "repo": "owner/repo-a", "num_tasks": 10, "url": ""},
        "tool": {"display_name": "Tool B", "is_oss": False, "url": ""},
        "metrics": {
            "score": 0.60, "n_tasks": 10, "n_errors": 2,
            "n_input_tokens": 3000000, "n_output_tokens": 60000,
            "n_total_tokens": 3060000, "total_time_seconds": 2400,
            "cost_usd": 12.00, "mean_input_tokens_per_task": 300000,
            "mean_output_tokens_per_task": 6000, "mean_cost_usd_per_task": 1.20,
            "mean_time_seconds_per_task": 240.0,
        },
    }
    result_3 = {
        "benchmark": {"name": "backportbench-other-repo-b", "repo": "other/repo-b", "num_tasks": 5, "url": ""},
        "tool": {"display_name": "Tool A", "is_oss": True, "url": ""},
        "metrics": {
            "score": 0.60, "n_tasks": 5, "n_errors": 0,
            "n_input_tokens": 1000000, "n_output_tokens": 24000,
            "n_total_tokens": 1024000, "total_time_seconds": 900,
            "cost_usd": 3.70, "mean_input_tokens_per_task": 200000,
            "mean_output_tokens_per_task": 4800, "mean_cost_usd_per_task": 0.74,
            "mean_time_seconds_per_task": 180.0,
        },
    }

    (agg_dir / "tool_a__owner-repo-a.json").write_text(json.dumps(result_1))
    (agg_dir / "tool_b__owner-repo-a.json").write_text(json.dumps(result_2))
    (agg_dir / "tool_a__other-repo-b.json").write_text(json.dumps(result_3))

    return agg_dir
