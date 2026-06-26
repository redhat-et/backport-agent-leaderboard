import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


def load_results(results_dir: Path) -> list[dict]:
    results_dir = Path(results_dir)
    results = []
    for path in sorted(results_dir.glob("*.json")):
        with open(path) as f:
            results.append(json.load(f))
    return results


def build_leaderboard_df(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    tool_scores: dict[str, dict] = defaultdict(lambda: {"scores": {}, "is_oss": True})

    for r in results:
        name = r["tool"]["display_name"]
        benchmark = r["benchmark"]["repo"]
        score = r["metrics"]["score"]
        tool_scores[name]["scores"][benchmark] = score
        tool_scores[name]["is_oss"] = r["tool"].get("is_oss", True)

    rows = []
    for name, data in tool_scores.items():
        scores = data["scores"]
        avg = sum(scores.values()) / len(scores) if scores else 0
        row = {
            "Category": "Open Source" if data["is_oss"] else "Proprietary",
            "Name": name,
            "Avg Score": round(avg, 4),
        }
        row.update(scores)
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values("Avg Score", ascending=False).reset_index(drop=True)
    return df


def build_runs_df(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    rows = []
    for r in results:
        rows.append({
            "Category": "Open Source" if r["tool"].get("is_oss", True) else "Proprietary",
            "Name": r["tool"]["display_name"],
            "Benchmark": r["benchmark"]["repo"],
            "Score": r["metrics"]["score"],
            "Avg Cost Per Task": r["metrics"].get("mean_cost_usd_per_task", 0),
            "Avg Seconds Per Task": r["metrics"].get("mean_time_seconds_per_task", 0),
            "Avg Input Tokens Per Task": r["metrics"].get("mean_input_tokens_per_task", 0),
            "Avg Output Tokens Per Task": r["metrics"].get("mean_output_tokens_per_task", 0),
        })

    return pd.DataFrame(rows)
