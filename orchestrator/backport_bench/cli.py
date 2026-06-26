from pathlib import Path

import click

from backport_bench.config import load_config
from backport_bench.dataset import (
    BackportEntry,
    filter_dataset,
    load_dataset,
    parse_repos_md,
)
from backport_bench.results import (
    RunResult,
    aggregate_results,
    has_result,
    load_result,
    save_result,
)
from backport_bench.runner import execute_run


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to YAML config file.")
@click.pass_context
def cli(ctx, config):
    """backport-bench: Benchmark orchestrator for automated backporting tools."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config)
    ctx.obj["root"] = _project_root()


@cli.command()
@click.option("--tool", help="Tool key from config. Uses default_tool if omitted.")
@click.option("--repo", help="Filter to a specific repo.")
@click.option("--classification", type=click.Choice(["Easy", "Medium", "Hard"]))
@click.option("--original", help="Filter by original commit SHA.")
@click.option("--backport", help="Filter by backport commit SHA.")
@click.option("--limit", type=int, help="Max entries to run.")
@click.pass_context
def run(ctx, tool, repo, classification, original, backport, limit):
    """Run benchmark against the dataset."""
    config = load_config(ctx.obj["config_path"])
    root = ctx.obj["root"]

    tool_key = tool or config.default_tool
    if tool_key not in config.tools:
        raise click.ClickException(f"Tool '{tool_key}' not found in config.")
    tool_def = config.tools[tool_key]

    dataset = load_dataset(root / "backports.csv")
    entries = filter_dataset(
        dataset, repo=repo, classification=classification,
        original=original, backport=backport, limit=limit,
    )

    if not entries:
        click.echo("No matching entries found.")
        return

    results_dir = root / "results"
    projects_dir = root / "projects"
    diffs_dir = root / "diffs"
    projects_dir.mkdir(exist_ok=True)
    results_dir.mkdir(exist_ok=True)

    repos_metadata = parse_repos_md(root / "repos.md")

    total = len(entries)
    passed = failed = errors = skipped = 0

    for i, entry in enumerate(entries, 1):
        if has_result(tool_key, entry.repo, entry.original_commit, entry.backport_commit, results_dir):
            skipped += 1
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  SKIPPED (exists)")
            continue

        result = execute_run(
            entry=entry, tool_key=tool_key, tool=tool_def, config=config,
            projects_dir=projects_dir, results_dir=results_dir,
            diffs_dir=diffs_dir, repos_metadata=repos_metadata,
        )
        save_result(result, results_dir)

        if result.error_message:
            errors += 1
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  ERROR  ({result.error_message[:60]})")
        elif result.semantic_equivalence == "PASS":
            passed += 1
            cost_str = f"${result.cost_usd:.2f}" if result.cost_usd else ""
            time_str = f"{result.time_seconds:.1f}s" if result.time_seconds else ""
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  PASS  {time_str}  {cost_str}")
        else:
            failed += 1
            reason = result.semantic_difference_reason or ""
            click.echo(f"[{i}/{total}] {entry.repo} {entry.original_commit[:8]} → {entry.backport_commit[:8]}  FAIL  ({reason[:60]})")

    click.echo(f"\nTotal: {total}  Passed: {passed}  Failed: {failed}  Errors: {errors}  Skipped: {skipped}")


@cli.command()
@click.option("--tool", help="Filter by tool key.")
@click.option("--repo", help="Filter by repo.")
@click.option("--classification", type=click.Choice(["Easy", "Medium", "Hard"]))
@click.pass_context
def results(ctx, tool, repo, classification):
    """Display results."""
    root = ctx.obj["root"]
    results_dir = root / "results"
    if not results_dir.exists():
        click.echo("No results found.")
        return

    all_results = []
    for path in results_dir.glob("*.json"):
        if path.parent.name == "aggregated":
            continue
        try:
            all_results.append(load_result(path))
        except Exception:
            continue

    if tool:
        all_results = [r for r in all_results if r.tool_key == tool]
    if repo:
        all_results = [r for r in all_results if r.repo == repo]
    if classification:
        all_results = [r for r in all_results if r.classification == classification]

    if not all_results:
        click.echo("No matching results.")
        return

    click.echo(f"{'Repo':<30} {'Orig':>8} {'Back':>8} {'Class':>6} {'Equiv':>6} {'Guide':>6} {'Cost':>8} {'Time':>8}")
    click.echo("-" * 90)
    for r in all_results:
        cost = f"${r.cost_usd:.2f}" if r.cost_usd else ""
        time_s = f"{r.time_seconds:.1f}s" if r.time_seconds else ""
        click.echo(
            f"{r.repo:<30} {r.original_commit[:8]:>8} {r.backport_commit[:8]:>8} "
            f"{r.classification:>6} {(r.semantic_equivalence or 'N/A'):>6} "
            f"{(r.guideline_adherence or 'N/A'):>6} {cost:>8} {time_s:>8}"
        )


@cli.command()
@click.pass_context
def leaderboard(ctx):
    """Aggregate results and display leaderboard summary."""
    root = ctx.obj["root"]
    results_dir = root / "results"
    aggregate_results(results_dir)
    click.echo("Aggregated results written to results/aggregated/")


@cli.command("add-backport")
@click.option("--repo", required=True, help="Repository (owner/name).")
@click.option("--original", required=True, help="Original commit SHA.")
@click.option("--backport", required=True, help="Backport commit SHA.")
@click.option("--add-repo/--no-add-repo", default=True, help="Auto-detect and add repo metadata.")
@click.pass_context
def add_backport(ctx, repo, original, backport, add_repo):
    """Add a new backport entry to the dataset."""
    from backport_bench.git_ops import clone_or_fetch, extract_diff
    from backport_bench.dataset import (
        append_backport,
        classify_backport,
        compute_metrics,
        validate_commit_reachable,
    )

    root = ctx.obj["root"]
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)

    owner, name = repo.split("/", 1)
    dir_name = f"{owner}__{name}"
    repo_url = f"https://github.com/{repo}.git"

    click.echo(f"Cloning/fetching {repo}...")
    project_path = clone_or_fetch(repo_url, projects_dir, dir_name)

    if not validate_commit_reachable(project_path, original):
        raise click.ClickException(f"Original commit {original} is not reachable from any remote branch.")

    click.echo("Extracting diffs...")
    orig_diff = extract_diff(project_path, original)
    back_diff = extract_diff(project_path, backport)

    metrics = compute_metrics(orig_diff, back_diff)
    classification = classify_backport(
        similarity=metrics["similarity"],
        file_overlap=metrics["file_overlap"],
    )

    click.echo(f"Classification: {classification}")
    click.echo(f"  similarity={metrics['similarity']:.2f}, file_overlap={metrics['file_overlap']:.2f}, "
               f"size_ratio={metrics['size_ratio']:.2f}, orig_files={metrics['orig_files']}, back_files={metrics['back_files']}")

    entry = BackportEntry(
        repo=repo,
        original_commit=original,
        backport_commit=backport,
        classification=classification,
        **metrics,
    )
    append_backport(entry, root / "backports.csv")
    click.echo(f"Appended to backports.csv")
