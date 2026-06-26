import pytest
import yaml

from backport_bench.config import (
    BenchmarkConfig,
    GuidelineCheckConfig,
    SemanticDiffConfig,
    ToolCommands,
    ToolDefinition,
    load_config,
)


class TestToolCommands:
    def test_generate_diff_required(self):
        tc = ToolCommands(generate_diff="echo hello")
        assert tc.generate_diff == "echo hello"
        assert tc.setup is None
        assert tc.get_stats is None

    def test_all_commands(self):
        tc = ToolCommands(
            setup="echo setup",
            generate_diff="echo diff",
            get_stats="echo stats",
        )
        assert tc.setup == "echo setup"
        assert tc.generate_diff == "echo diff"
        assert tc.get_stats == "echo stats"


class TestToolDefinition:
    def test_minimal(self):
        td = ToolDefinition(
            display_name="My Tool",
            commands=ToolCommands(generate_diff="echo diff"),
        )
        assert td.display_name == "My Tool"
        assert td.model is None
        assert td.config == {}

    def test_with_model_and_config(self):
        td = ToolDefinition(
            display_name="My Tool",
            model="claude-opus-4-6",
            config={"workdir": "/tmp", "tool_location": "/opt/tool"},
            commands=ToolCommands(generate_diff="echo diff"),
        )
        assert td.model == "claude-opus-4-6"
        assert td.config["workdir"] == "/tmp"
        assert td.config["tool_location"] == "/opt/tool"


class TestSemanticDiffConfig:
    def test_fields(self):
        sdc = SemanticDiffConfig(model="claude-opus-4-6", command="echo test")
        assert sdc.model == "claude-opus-4-6"
        assert sdc.command == "echo test"


class TestGuidelineCheckConfig:
    def test_fields(self):
        gcc = GuidelineCheckConfig(model="claude-opus-4-6", command="echo test")
        assert gcc.model == "claude-opus-4-6"
        assert gcc.command == "echo test"


class TestBenchmarkConfig:
    def test_defaults(self, sample_config_dict):
        config = BenchmarkConfig(**sample_config_dict)
        assert config.timeout == 60
        assert config.verify_tests is False
        assert config.default_tool == "test-tool"

    def test_tool_access(self, sample_config_dict):
        config = BenchmarkConfig(**sample_config_dict)
        tool = config.tools["test-tool"]
        assert tool.display_name == "Test Tool / Default"
        assert tool.model == "claude-opus-4-6"

    def test_default_timeout(self):
        minimal = {
            "semantic_diff": {"model": "m", "command": "c"},
            "guideline_check": {"model": "m", "command": "c"},
            "default_tool": "t",
            "tools": {
                "t": {
                    "display_name": "T",
                    "commands": {"generate_diff": "echo"},
                },
            },
        }
        config = BenchmarkConfig(**minimal)
        assert config.timeout == 1800
        assert config.verify_tests is False


class TestLoadConfig:
    def test_load_from_yaml(self, sample_config_path):
        config = load_config(sample_config_path)
        assert isinstance(config, BenchmarkConfig)
        assert config.default_tool == "test-tool"
        assert "test-tool" in config.tools

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: valid: yaml: {{{}}")
        with pytest.raises(Exception):
            load_config(bad)

    def test_missing_required_field_raises(self, tmp_path):
        incomplete = tmp_path / "incomplete.yaml"
        incomplete.write_text(yaml.dump({"timeout": 60}))
        with pytest.raises(Exception):
            load_config(incomplete)
