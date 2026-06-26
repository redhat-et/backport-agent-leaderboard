import os

from backport_bench.config import ToolDefinition


def build_variable_dict(
    *,
    repo: str,
    orig_sha: str,
    backport_sha: str,
    run_key: str,
    project_path: str,
    source_branch: str,
    target_workspace: str,
    original_diff_path: str,
    pipeline_diff_path: str,
    build_cmd: str,
    test_command: str,
    repo_guidelines: str,
    tool: ToolDefinition,
    semantic_diff_model: str,
    guideline_check_model: str,
) -> dict[str, str]:
    env = dict(os.environ)

    env["REPO"] = repo
    env["ORIG_SHA"] = orig_sha
    env["BACKPORT_SHA"] = backport_sha
    env["RUN_KEY"] = run_key
    env["PROJECT_PATH"] = project_path
    env["SOURCE_BRANCH"] = source_branch
    env["TARGET_WORKSPACE"] = target_workspace
    env["ORIGINAL_DIFF_PATH"] = original_diff_path
    env["PIPELINE_DIFF_PATH"] = pipeline_diff_path
    env["BUILD_CMD"] = build_cmd
    env["TEST_COMMAND"] = test_command
    env["REPO_GUIDELINES"] = repo_guidelines

    if tool.model is not None:
        env["CONFIG_MODEL"] = tool.model
    for key, value in tool.config.items():
        env[f"CONFIG_{key.upper()}"] = value

    env["SEMANTIC_DIFF_MODEL"] = semantic_diff_model
    env["GUIDELINE_CHECK_MODEL"] = guideline_check_model

    return env
