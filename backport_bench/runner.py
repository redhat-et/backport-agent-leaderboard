import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from backport_bench.config import BenchmarkConfig, ToolDefinition
from backport_bench.dataset import BackportEntry, RepoMetadata
from backport_bench.evaluator import compute_diff_lines, parse_json_output, run_guideline_check, run_semantic_diff
from backport_bench.git_ops import cleanup, clone_or_fetch, create_worktree, extract_diff, find_source_branch, setup_target_branch
from backport_bench.results import RunResult, save_result
from backport_bench.variables import build_variable_dict

logger = logging.getLogger(__name__)


def run_command(
    command: str, *, cwd: Path, env: dict, timeout: int, label: str = "",
) -> tuple[int, str, str]:
    logger.info("Running %s: %s", label or "command", command.strip()[:200])
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd, env=env,
            timeout=timeout, capture_output=True, text=True,
        )
        if result.stdout:
            logger.debug("%s stdout:\n%s", label, result.stdout)
        if result.stderr:
            logger.debug("%s stderr:\n%s", label, result.stderr)
        if result.returncode != 0:
            logger.warning("%s exited with code %d", label, result.returncode)
            if result.stderr:
                logger.warning("%s stderr: %s", label, result.stderr.strip()[:1000])
            if result.stdout:
                logger.warning("%s stdout: %s", label, result.stdout.strip()[:1000])
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after %ds", label, timeout)
        return -1, "", f"Timeout after {timeout}s"


def execute_run(
    *,
    entry: BackportEntry,
    tool_key: str,
    tool: ToolDefinition,
    config: BenchmarkConfig,
    projects_dir: Path,
    results_dir: Path,
    diffs_dir: Path,
    repos_metadata: dict[str, RepoMetadata],
) -> RunResult:
    start_time = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    repo_owner, repo_name = entry.repo.split("/", 1)
    dir_name = f"{repo_owner}__{repo_name}"
    run_key = f"{entry.original_commit[:8]}-{entry.backport_commit[:8]}"
    project_path = None

    def _make_error_result(error_msg: str) -> RunResult:
        elapsed = time.monotonic() - start_time
        return RunResult(
            tool_display_name=tool.display_name,
            tool_key=tool_key,
            repo=entry.repo,
            original_commit=entry.original_commit,
            backport_commit=entry.backport_commit,
            classification=entry.classification,
            semantic_equivalence=None,
            semantic_difference_reason=None,
            guideline_adherence=None,
            guideline_reason=None,
            test_success=None,
            error_message=error_msg,
            diff_lines=None,
            time_seconds=round(elapsed, 1),
            llm_calls=None,
            cost_usd=None,
            input_tokens=None,
            output_tokens=None,
            timestamp=timestamp,
        )

    try:
        logger.info("Starting run: %s %s → %s [%s]", entry.repo, entry.original_commit[:8], entry.backport_commit[:8], entry.classification)

        repo_url = f"https://github.com/{entry.repo}.git"
        project_path = clone_or_fetch(repo_url, projects_dir, dir_name)
        logger.info("Repo ready at %s", project_path)

        source_branch = find_source_branch(project_path, entry.original_commit)
        setup_target_branch(project_path, entry.backport_commit)
        logger.info("Branches: source=%s, target branch set up", source_branch)

        wt_path = project_path / ".worktrees" / run_key
        create_worktree(project_path, "target", wt_path)

        original_diff = extract_diff(project_path, entry.backport_commit)

        diff_tool_dir = Path(diffs_dir) / tool_key / f"{entry.original_commit[:8]}__{entry.backport_commit[:8]}"
        diff_tool_dir.mkdir(parents=True, exist_ok=True)
        orig_diff_path = diff_tool_dir / "original.diff"
        pipe_diff_path = diff_tool_dir / "pipeline.diff"
        orig_diff_path.write_text(original_diff)

        repo_meta = repos_metadata.get(entry.repo)
        build_cmd = repo_meta.build if repo_meta else ""
        test_command = repo_meta.test if repo_meta else ""
        repo_guidelines = repo_meta.guidelines if repo_meta else ""

        env = build_variable_dict(
            repo=entry.repo,
            orig_sha=entry.original_commit,
            backport_sha=entry.backport_commit,
            run_key=run_key,
            project_path=str(project_path),
            source_branch=source_branch,
            target_workspace=str(wt_path),
            original_diff_path=str(orig_diff_path),
            pipeline_diff_path=str(pipe_diff_path),
            build_cmd=build_cmd,
            test_command=test_command,
            repo_guidelines=repo_guidelines,
            tool=tool,
            semantic_diff_model=config.semantic_diff.model,
            guideline_check_model=config.guideline_check.model,
        )

        baseline_passed = False
        if config.verify_tests and test_command:
            logger.info("Running baseline tests")
            rc, _, _ = run_command(test_command, cwd=wt_path, env=env, timeout=config.timeout, label="baseline_tests")
            baseline_passed = (rc == 0)
            if not baseline_passed:
                logger.warning("Baseline tests failed (exit %d), skipping test verification", rc)

        if tool.commands.setup:
            rc, stdout, stderr = run_command(tool.commands.setup, cwd=wt_path, env=env, timeout=config.timeout, label="setup")
            if rc != 0:
                output = stderr.strip() or stdout.strip()
                return _make_error_result(f"Setup failed (exit {rc}): {output[:500]}")

        rc, stdout, stderr = run_command(tool.commands.generate_diff, cwd=wt_path, env=env, timeout=config.timeout, label="generate_diff")
        if rc == -1:
            return _make_error_result(f"Timeout after {config.timeout}s")
        if rc != 0:
            output = stderr.strip() or stdout.strip()
            return _make_error_result(f"generate_diff failed (exit {rc}): {output[:500]}")

        sem_rc, sem_stdout, _ = run_command(config.semantic_diff.command, cwd=project_path, env=env, timeout=config.timeout, label="semantic_diff")
        semantic_equivalence, semantic_reason = run_semantic_diff(sem_stdout)

        guideline_adherence = None
        guideline_reason = None
        if repo_guidelines:
            gl_rc, gl_stdout, _ = run_command(config.guideline_check.command, cwd=project_path, env=env, timeout=config.timeout, label="guideline_check")
            guideline_adherence, guideline_reason = run_guideline_check(gl_stdout)

        if config.verify_tests and test_command and baseline_passed:
            apply_rc, _, _ = run_command(
                f"git apply {pipe_diff_path}", cwd=wt_path, env=env, timeout=60, label="apply_diff",
            )
            if apply_rc != 0:
                test_success = "ERROR"
                logger.warning("Failed to apply pipeline diff for test verification")
            else:
                test_rc, _, _ = run_command(test_command, cwd=wt_path, env=env, timeout=config.timeout, label="verify_tests")
                test_success = "PASS" if test_rc == 0 else "FAIL"
        else:
            test_success = "SKIPPED"

        diff_lines = compute_diff_lines(orig_diff_path, pipe_diff_path)

        llm_calls = None
        cost_usd = None
        input_tokens = None
        output_tokens = None
        tool_time = None

        if tool.commands.get_stats:
            stats_rc, stats_stdout, _ = run_command(tool.commands.get_stats, cwd=wt_path, env=env, timeout=30, label="get_stats")
            if stats_rc == 0:
                stats = parse_json_output(stats_stdout)
                if stats:
                    tool_time = stats.get("time")
                    llm_calls = stats.get("llm_calls")
                    cost_usd = stats.get("cost")
                    input_tokens = stats.get("input_tokens")
                    output_tokens = stats.get("output_tokens")

        elapsed = time.monotonic() - start_time

        return RunResult(
            tool_display_name=tool.display_name,
            tool_key=tool_key,
            repo=entry.repo,
            original_commit=entry.original_commit,
            backport_commit=entry.backport_commit,
            classification=entry.classification,
            semantic_equivalence=semantic_equivalence,
            semantic_difference_reason=semantic_reason,
            guideline_adherence=guideline_adherence,
            guideline_reason=guideline_reason,
            test_success=test_success,
            error_message=None,
            diff_lines=diff_lines,
            time_seconds=tool_time if tool_time else round(elapsed, 1),
            llm_calls=llm_calls,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=timestamp,
        )

    except Exception as e:
        logger.exception("Unexpected error during run")
        return _make_error_result(str(e))

    finally:
        if project_path:
            cleanup(project_path, run_key)
