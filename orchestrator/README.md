# Backport Bench — Orchestrator Package

The orchestrator package provides the CLI tool and benchmark engine for running backport evaluations. It manages the full pipeline: repository setup, tool invocation, semantic equivalence checking, and result storage.

## Installation

Install in development mode:

```bash
pip install -e ".[dev]"
```

This installs the `backport-bench` CLI command and all dependencies.

## CLI Reference

### Global Options

- `--config`, `-c` — Path to YAML config file (default: `config.yaml`)

### Commands

#### `backport-bench run`

Execute benchmark runs against the dataset.

```bash
# Run with default tool (from config.yaml)
backport-bench run

# Run with a specific tool
backport-bench run --tool my-tool

# Filter by repository
backport-bench run --tool my-tool --repo line/armeria

# Filter by classification
backport-bench run --tool my-tool --classification Easy

# Limit number of runs
backport-bench run --tool my-tool --limit 10

# Run a specific backport entry
backport-bench run --tool my-tool --original <orig_sha> --backport <backport_sha>
```

Options:
- `--tool TOOL_KEY` — Tool configuration key from config.yaml
- `--repo REPO` — Filter to specific repository (e.g., `line/armeria`)
- `--classification {Easy,Medium,Complex}` — Filter by complexity
- `--original SHA` — Run specific entry by original commit SHA
- `--backport SHA` — Run specific entry by backport commit SHA (requires `--original`)
- `--limit N` — Run at most N entries

The command is idempotent — it skips entries that already have results, allowing interrupted runs to be resumed.

#### `backport-bench results`

Display results for completed runs.

```bash
# Show all results for a tool
backport-bench results --tool my-tool

# Filter by repository
backport-bench results --tool my-tool --repo line/armeria

# Filter by classification
backport-bench results --tool my-tool --classification Easy
```

Options:
- `--tool TOOL_KEY` — Tool configuration key
- `--repo REPO` — Filter to specific repository
- `--classification {Easy,Medium,Complex}` — Filter by complexity

Output is an aligned table showing:
- Repository
- Original/backport commit SHAs (short)
- Classification
- Semantic equivalence (PASS/FAIL)
- Guideline adherence (PASS/FAIL)
- Cost (USD)
- Time (seconds)

#### `backport-bench leaderboard`

Display aggregated leaderboard view (CLI version).

```bash
backport-bench leaderboard
```

Aggregates all results by tool and shows:
- Tool display name
- Average pass rate
- Average cost per task
- Average time per task
- Total runs

For the interactive web version, see [leaderboard/README.md](../leaderboard/README.md).

#### `backport-bench add-backport`

Add a new backport entry to the dataset.

```bash
backport-bench add-backport --repo owner/repo --original <sha> --backport <sha>
```

Options:
- `--repo REPO` — Repository identifier (e.g., `line/armeria`)
- `--original SHA` — SHA of the original fix commit
- `--backport SHA` — SHA of the backport commit
- `--add-repo` / `--no-add-repo` — Auto-detect and add repo metadata to repos.md (default: `--add-repo`)

The command:
1. Validates both commits are reachable from branches
2. Extracts and normalizes both diffs
3. Computes complexity metrics (similarity, file_overlap, size_ratio)
4. Assigns classification (Easy, Medium, Complex)
5. Appends the entry to backports.csv
6. If the repo is not in repos.md, auto-detects metadata and appends it

## Configuration File

The orchestrator is configured via a YAML file (default: `config.yaml` in project root). See [config.example.yaml](../config.example.yaml) for a complete reference.

### Structure

```yaml
semantic_diff:
  model: "claude-opus-4-6"
  command: |
    # Shell command to invoke semantic equivalence check
    # Must output JSON: {"equivalent": true} or {"equivalent": false, "reason": "..."}

guideline_check:
  model: "claude-opus-4-6"
  command: |
    # Shell command to check guideline adherence
    # Must output JSON: {"adheres": true} or {"adheres": false, "reason": "..."}

default_tool: "my-tool"
timeout: 1800
verify_tests: false

tools:
  my-tool:
    display_name: "My Tool / Opus 4.6"
    model: "claude-opus-4-6"
    config:
      tool_location: "/path/to/tool"
    commands:
      setup: |
        # Optional: prepare config, credentials
      generate_diff: |
        # Required: generate diff, write to ${PIPELINE_DIFF_PATH}
      get_stats: |
        # Optional: emit JSON metrics to stdout
```

### Environment Variables

The orchestrator provides these variables to all commands:

| Variable | Description |
|---|---|
| `REPO` | Repository identifier (e.g., `line/armeria`) |
| `ORIG_SHA` | SHA of the original fix commit |
| `BACKPORT_SHA` | SHA of the known-good backport commit |
| `RUN_KEY` | Unique key for this run (`{orig_sha}-{backport_sha}`) |
| `PROJECT_PATH` | Absolute path to the local project clone |
| `SOURCE_BRANCH` | Branch containing the original commit |
| `TARGET_WORKSPACE` | Path to the isolated worktree for the target branch |
| `ORIGINAL_DIFF_PATH` | Path to the known-good backport diff |
| `PIPELINE_DIFF_PATH` | Path where `generate_diff` must write output |
| `BUILD_CMD` | Build command for the repo (from repos.md) |
| `TEST_COMMAND` | Test command for the repo (from repos.md) |
| `REPO_GUIDELINES` | Contributing guidelines for the repo (from repos.md) |
| `SEMANTIC_DIFF_MODEL` | Model for semantic diff (from config) |
| `GUIDELINE_CHECK_MODEL` | Model for guideline check (from config) |

Tool-specific `config` fields are exposed as `CONFIG_<KEY>` (uppercased). For example, `config.tool_location` becomes `CONFIG_TOOL_LOCATION`.

## Running Tests

The package includes a BDD test suite using pytest-bdd:

```bash
# Run all tests
pytest -v

# Run tests for a specific feature
pytest tests/features/run_command.feature -v

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests only
pytest tests/integration/ -v
```

## Result Storage

Results are stored in two locations:

### Per-Run Results

`results/<tool-key>__<repo-owner>__<repo-name>__<orig-sha-8>__<backport-sha-8>.json`

Each file contains:
- Tool metadata (display_name, key)
- Backport entry metadata (repo, commits, classification)
- Evaluation results (semantic_equivalence, guideline_adherence, test_success)
- Metrics (time, cost, tokens, llm_calls)
- Error message (if run failed)
- Timestamp

### Aggregated Results

`results/aggregated/<tool-key>__<benchmark>.json`

Aggregated files follow the format expected by the leaderboard app:

```json
{
  "benchmark": {
    "name": "backportbench-java",
    "repo": "owner/repo",
    "num_tasks": 250,
    "url": "https://..."
  },
  "tool": {
    "display_name": "My Tool / Opus 4.6",
    "is_oss": true,
    "url": "https://..."
  },
  "metrics": {
    "score": 0.72,
    "n_tasks": 250,
    "n_errors": 3,
    "cost_usd": 185.50,
    "mean_cost_usd_per_task": 0.74,
    "mean_time_seconds_per_task": 180,
    "mean_input_tokens_per_task": 200000,
    "mean_output_tokens_per_task": 4800
  }
}
```

### Diffs

Diffs are retained for debugging:

`diffs/<tool-key>/<orig-sha-8>__<backport-sha-8>/original.diff`
`diffs/<tool-key>/<orig-sha-8>__<backport-sha-8>/pipeline.diff`

## Architecture

The orchestrator is organized into modules:

- **cli.py** — Click CLI entry point, subcommands, argument parsing
- **config.py** — YAML parsing, Pydantic models, validation
- **dataset.py** — CSV loading, filtering, classification computation
- **runner.py** — Core run pipeline, orchestrates all steps
- **git_ops.py** — Git operations (clone, fetch, branch, diff extraction)
- **evaluator.py** — Semantic diff and guideline checks, JSON parsing
- **results.py** — Result storage, aggregation, resume checks
- **variables.py** — Environment variable building for commands

## Design Principles

- **Tool-agnostic** — Any tool invocable from a shell can participate
- **Isolated** — Each run operates in its own git worktree
- **Resumable** — Interrupted runs can be resumed; completed runs are skipped
- **Extensible** — Adding a tool requires only a config entry, no code changes

## See Also

- [Project README](../README.md) — Overview and quick start
- [PRD](../PRD.md) — Product requirements
- [Design Spec](../docs/superpowers/specs/2026-06-26-backport-bench-design.md) — Technical design
- [config.example.yaml](../config.example.yaml) — Configuration reference
- [Leaderboard README](../leaderboard/README.md) — Web app documentation
