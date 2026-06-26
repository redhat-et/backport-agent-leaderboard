import json
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict


@dataclass
class RunResult:
    tool_display_name: str
    tool_key: str
    repo: str
    original_commit: str
    backport_commit: str
    classification: str
    semantic_equivalence: str | None
    semantic_difference_reason: str | None
    guideline_adherence: str | None
    guideline_reason: str | None
    test_success: str | None
    error_message: str | None
    diff_lines: int | None
    time_seconds: float | None
    llm_calls: int | None
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(**d)

    def filename(self) -> str:
        owner, repo = self.repo.split("/", 1)
        orig_short = self.original_commit[:8]
        back_short = self.backport_commit[:8]
        return f"{self.tool_key}__{owner}__{repo}__{orig_short}__{back_short}.json"


def save_result(result: RunResult, results_dir: Path) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / result.filename()
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    return path


def load_result(path: Path) -> RunResult:
    with open(path) as f:
        return RunResult.from_dict(json.load(f))


def has_result(
    tool_key: str, repo: str, original_commit: str, backport_commit: str,
    results_dir: Path,
) -> bool:
    owner, repo_name = repo.split("/", 1)
    orig_short = original_commit[:8]
    back_short = backport_commit[:8]
    filename = f"{tool_key}__{owner}__{repo_name}__{orig_short}__{back_short}.json"
    return (Path(results_dir) / filename).exists()


def _safe_mean(values: list) -> float:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return 0.0
    return sum(filtered) / len(filtered)


def aggregate_results(results_dir: Path) -> None:
    results_dir = Path(results_dir)
    agg_dir = results_dir / "aggregated"
    agg_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for path in results_dir.glob("*.json"):
        if path.parent.name == "aggregated":
            continue
        results.append(load_result(path))

    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[(r.tool_display_name, r.repo)].append(r)

    for (tool_name, repo), runs in grouped.items():
        n_tasks = len(runs)
        n_errors = sum(1 for r in runs if r.error_message is not None)
        n_pass = sum(1 for r in runs if r.semantic_equivalence == "PASS")
        score = n_pass / n_tasks if n_tasks > 0 else 0.0

        agg = {
            "benchmark": {
                "name": f"backportbench-{repo.replace('/', '-')}",
                "repo": repo,
                "num_tasks": n_tasks,
                "url": f"https://github.com/{repo}",
            },
            "tool": {
                "display_name": tool_name,
                "is_oss": True,
                "url": "",
            },
            "metrics": {
                "score": round(score, 4),
                "n_tasks": n_tasks,
                "n_errors": n_errors,
                "n_input_tokens": sum(r.input_tokens or 0 for r in runs),
                "n_output_tokens": sum(r.output_tokens or 0 for r in runs),
                "n_total_tokens": sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in runs),
                "total_time_seconds": sum(r.time_seconds or 0 for r in runs),
                "cost_usd": sum(r.cost_usd or 0 for r in runs),
                "mean_input_tokens_per_task": round(_safe_mean([r.input_tokens for r in runs])),
                "mean_output_tokens_per_task": round(_safe_mean([r.output_tokens for r in runs])),
                "mean_cost_usd_per_task": round(_safe_mean([r.cost_usd for r in runs]), 2),
                "mean_time_seconds_per_task": round(_safe_mean([r.time_seconds for r in runs]), 1),
            },
        }

        safe_tool = tool_name.replace("/", "-").replace(" ", "_").lower()
        safe_repo = repo.replace("/", "-")
        filename = f"{safe_tool}__{safe_repo}.json"
        with open(agg_dir / filename, "w") as f:
            json.dump(agg, f, indent=2)
