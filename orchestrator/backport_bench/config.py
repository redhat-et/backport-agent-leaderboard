from pathlib import Path

import yaml
from pydantic import BaseModel


class SemanticDiffConfig(BaseModel):
    model: str
    command: str


class GuidelineCheckConfig(BaseModel):
    model: str
    command: str


class ToolCommands(BaseModel):
    setup: str | None = None
    generate_diff: str
    get_stats: str | None = None


class ToolDefinition(BaseModel):
    display_name: str
    model: str | None = None
    config: dict[str, str] = {}
    commands: ToolCommands


class BenchmarkConfig(BaseModel):
    semantic_diff: SemanticDiffConfig
    guideline_check: GuidelineCheckConfig
    default_tool: str
    timeout: int = 1800
    verify_tests: bool = False
    tools: dict[str, ToolDefinition]


def load_config(path: Path) -> BenchmarkConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return BenchmarkConfig(**raw)
