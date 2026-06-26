from backport_bench.variables import build_variable_dict
from backport_bench.config import BenchmarkConfig, ToolDefinition, ToolCommands


class TestBuildVariableDict:
    def test_orchestrator_variables(self):
        env = build_variable_dict(
            repo="owner/repo",
            orig_sha="aaa111",
            backport_sha="bbb222",
            run_key="aaa111-bbb222",
            project_path="/projects/owner__repo",
            source_branch="main",
            target_workspace="/projects/owner__repo/.worktrees/aaa111-bbb222",
            original_diff_path="/diffs/original.diff",
            pipeline_diff_path="/diffs/pipeline.diff",
            build_cmd="make",
            test_command="make test",
            repo_guidelines="PEP 8",
            tool=ToolDefinition(
                display_name="T",
                commands=ToolCommands(generate_diff="echo"),
            ),
            semantic_diff_model="claude-opus-4-6",
            guideline_check_model="claude-opus-4-6",
        )
        assert env["REPO"] == "owner/repo"
        assert env["ORIG_SHA"] == "aaa111"
        assert env["BACKPORT_SHA"] == "bbb222"
        assert env["RUN_KEY"] == "aaa111-bbb222"
        assert env["PROJECT_PATH"] == "/projects/owner__repo"
        assert env["SOURCE_BRANCH"] == "main"
        assert env["TARGET_WORKSPACE"] == "/projects/owner__repo/.worktrees/aaa111-bbb222"
        assert env["ORIGINAL_DIFF_PATH"] == "/diffs/original.diff"
        assert env["PIPELINE_DIFF_PATH"] == "/diffs/pipeline.diff"
        assert env["BUILD_CMD"] == "make"
        assert env["TEST_COMMAND"] == "make test"
        assert env["REPO_GUIDELINES"] == "PEP 8"

    def test_tool_config_variables(self):
        tool = ToolDefinition(
            display_name="T",
            model="claude-opus-4-6",
            config={"tool_location": "/opt/tool", "workdir": "/tmp"},
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="m", guideline_check_model="m",
        )
        assert env["CONFIG_MODEL"] == "claude-opus-4-6"
        assert env["CONFIG_TOOL_LOCATION"] == "/opt/tool"
        assert env["CONFIG_WORKDIR"] == "/tmp"

    def test_evaluation_model_variables(self):
        tool = ToolDefinition(
            display_name="T",
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="sd-model", guideline_check_model="gc-model",
        )
        assert env["SEMANTIC_DIFF_MODEL"] == "sd-model"
        assert env["GUIDELINE_CHECK_MODEL"] == "gc-model"

    def test_no_model_omits_config_model(self):
        tool = ToolDefinition(
            display_name="T",
            commands=ToolCommands(generate_diff="echo"),
        )
        env = build_variable_dict(
            repo="o/r", orig_sha="a", backport_sha="b", run_key="a-b",
            project_path="/p", source_branch="main", target_workspace="/w",
            original_diff_path="/o.diff", pipeline_diff_path="/p.diff",
            build_cmd="", test_command="", repo_guidelines="",
            tool=tool, semantic_diff_model="m", guideline_check_model="m",
        )
        assert "CONFIG_MODEL" not in env
