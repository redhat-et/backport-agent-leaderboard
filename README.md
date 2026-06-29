# Backport Agent Leaderboard

A benchmarking platform that evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects. Tools are ranked by accuracy, cost, speed, and token efficiency on a hosted leaderboard.

## Overview

Backport Agent Leaderboard consists of two components:

- **backport_bench/** — CLI tool that runs benchmarks, evaluates semantic equivalence, and stores results
- **leaderboard/** — Standalone Gradio web app that visualizes benchmark results

The system uses a curated dataset of 36 verified backports from 4 open-source projects, classified by complexity (Easy, Medium, Hard).

## Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git
- Access to Claude API (for semantic diff evaluation and guideline checking)

## Installation

```bash
# Install core orchestrator + dev tools
uv sync --extra dev

# Also install the leaderboard app
uv sync --extra dev --extra leaderboard
```

## Quick Start

### 1. Configure your environment

Copy the example configuration and customize it:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your tool definitions and settings
```

See [config.example.yaml](config.example.yaml) for a complete reference. Here is an annotated example:

```yaml
# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------
semantic_diff:
  model: "claude-opus-4-6"
  command: |
    claude --model ${SEMANTIC_DIFF_MODEL} -p "Compare @${ORIGINAL_DIFF_PATH} and @${PIPELINE_DIFF_PATH} and determine if they are semantically equivalent.
    Respond with a single JSON object and no other text:
    - If equivalent: {\"equivalent\": true}
    - If not equivalent: {\"equivalent\": false, \"reason\": \"<brief explanation>\"}"

guideline_check:
  model: "claude-opus-4-6"
  command: |
    claude --model ${GUIDELINE_CHECK_MODEL} -p "Review @${PIPELINE_DIFF_PATH} against the following contributing guidelines: ${REPO_GUIDELINES}
    Respond with a single JSON object and no other text:
    - If adheres: {\"adheres\": true}
    - If not adheres: {\"adheres\": false, \"reason\": \"<brief explanation>\"}"

default_tool: "amalgamator-opus"
timeout: 50000
verify_tests: true

tools:
  amalgamator-opus-with-build-test:
    display_name: "Amalgamator / Opus 4.6 with build and test"  
    model: "claude-opus-4-6"
    config:
      tool_location: "/Users/ricmitch/Code/bug-fix/amalgamator"
      workdir: "/tmp/amalgamator"
      config_file: "/tmp/amalgamator"

    commands:
      setup: |
        mkdir -p ${CONFIG_WORKDIR}
        cat > ${CONFIG_WORKDIR}/${RUN_KEY}-config.yaml <<EOF
        issue_id: "${RUN_KEY}"
        bug_description: "${ORIG_SHA}"
        output:
          directory: ${CONFIG_WORKDIR}/
        repository:
          source_path: "${PROJECT_PATH}"
          workdir: "${CONFIG_WORKDIR}/"
        branches:
          source: "${SOURCE_BRANCH}"
          target: "target"
        fix:
          commit: "${ORIG_SHA}"
        build:
          command: "${BUILD_CMD}"
          test_command: "${TEST_COMMAND}"
        model: "${CONFIG_MODEL}"
        EOF
      generate_diff: |
        cd ${CONFIG_TOOL_LOCATION} &&
        source .venv/bin/activate &&
        python -m auto_bug_fix.run_bug_fix ${CONFIG_CONFIG_FILE}/${RUN_KEY}-config.yaml &&
        cd ${CONFIG_WORKDIR}/${RUN_KEY} &&
        git diff ${BACKPORT_SHA}^..HEAD > ${PIPELINE_DIFF_PATH}
      get_stats: |
        LOG=$(ls -d ${CONFIG_TOOL_LOCATION}/runs/${RUN_KEY}* | sort | tail -1)/run_log.txt
        echo $(grep -E '^TOTAL' "$LOG" | awk '{
          gsub(/s$/, "", $2); gsub(/,/, "", $4); gsub(/\$/, "", $5);
          printf "{\"time\": %s, \"llm_calls\": %s, \"cost\": %s, \"input_tokens\": %s}", $2, $3, $5, $4
        }')

  amalgamator-opus:
    display_name: "Amalgamator / Opus 4.6 with build and test"  
    model: "claude-opus-4-6"
    config:
      tool_location: "/Users/ricmitch/Code/bug-fix/amalgamator"
      workdir: "/tmp/amalgamator"
      config_file: "/tmp/amalgamator"

    commands:
      setup: |
        mkdir -p ${CONFIG_WORKDIR}
        cat > ${CONFIG_WORKDIR}/${RUN_KEY}-config.yaml <<EOF
        issue_id: "${RUN_KEY}"
        bug_description: "${ORIG_SHA}"
        output:
          directory: ${CONFIG_WORKDIR}/
        repository:
          source_path: "${PROJECT_PATH}"
          workdir: "${CONFIG_WORKDIR}/"
        branches:
          source: "${SOURCE_BRANCH}"
          target: "target"
        fix:
          commit: "${ORIG_SHA}"
        build:
          command: ""
          test_command: ""
        model: "${CONFIG_MODEL}"
        EOF
      generate_diff: |
        cd ${CONFIG_TOOL_LOCATION} &&
        source .venv/bin/activate &&
        python -m auto_bug_fix.run_bug_fix ${CONFIG_CONFIG_FILE}/${RUN_KEY}-config.yaml &&
        cd ${CONFIG_WORKDIR}/${RUN_KEY} &&
        git diff ${BACKPORT_SHA}^..HEAD > ${PIPELINE_DIFF_PATH}
      get_stats: |
        LOG=$(ls -d ${CONFIG_TOOL_LOCATION}/runs/${RUN_KEY}* | sort | tail -1)/run_log.txt
        echo $(grep -E '^TOTAL' "$LOG" | awk '{
          gsub(/s$/, "", $2); gsub(/,/, "", $4); gsub(/\$/, "", $5);
          printf "{\"time\": %s, \"llm_calls\": %s, \"cost\": %s, \"input_tokens\": %s}", $2, $3, $5, $4
        }')

  claude-code:
    display_name: "Claude Code / default"
    model: "claude-opus-4-6"
    config: {}

    commands:
      generate_diff: |
        claude -p "You are an expert software engineer performing a git backport.
        TASK: Apply the fix commited with SHA ${ORIG_SHA} to the branch target.
        Instructions
        1. Understand what the original fix does (the intent, not just the syntax).
        2. Adapt the fix to the current code on target — context may differ between branches.
        3. Preserve the original intent: fix the same root cause, keep the same behaviour.
        4. Output ONLY a valid unified diff in git diff format in the file ${PIPELINE_DIFF_PATH}. Do not include any explanation or commentary — just the raw diff starting with diff --git.
        5. Write the following stats to the file /tmp/llm-stats.json in json format:
            - time (float):  Wall-clock seconds the tool spent generating the diff.
            - llm_calls (int): Number of LLM API calls made
            - cost (float): Total LLM API Cost in USD
            - input_tokens (int): Total input tokens consumed
            - output_tokens int Total output tokens consumed."
      get_stats: |
        cat /tmp/llm-stats.json
```

### 2. Run benchmarks

```bash
# Run benchmarks with the default tool (from config.yaml)
backport-bench run

# Run with a specific tool
backport-bench run --tool my-tool

# Run against a single repo or limit entries
backport-bench run --tool my-tool --repo line/armeria --limit 10

# Run only Easy backports
backport-bench run --tool my-tool --classification Easy

# Run a specific backport entry by commit SHAs
backport-bench run --tool my-tool --original <orig_sha> --backport <backport_sha>

# Re-run entries that already have results
backport-bench run --tool my-tool --force
```

### 3. View results

```bash
# View results for a specific tool
backport-bench results --tool my-tool

# Display the leaderboard (CLI view)
backport-bench leaderboard
```

### 4. Launch the web leaderboard

```bash
cd leaderboard
python app.py
```

The leaderboard will be available at http://localhost:7860

### 5. Add new backport entries

```bash
backport-bench add-backport --repo owner/repo --original <sha> --backport <sha>
```

This automatically:
- Validates the commits
- Computes complexity classification
- Detects repo metadata (build/test commands, guidelines)
- Appends the entry to backports.csv

## Documentation

- [PRD.md](PRD.md) — Product requirements and functional specifications
- [Design Spec](docs/superpowers/specs/2026-06-26-backport-bench-design.md) — Technical design and architecture
- [config.example.yaml](config.example.yaml) — Configuration file reference
- [leaderboard/README.md](leaderboard/README.md) — Leaderboard app documentation

## Project Structure

```
backport-agent-leaderboard/
├── pyproject.toml               # Single project configuration
├── config.example.yaml          # Configuration template
├── backports.csv                # Dataset of known-good backports
├── repos.md                     # Repository metadata (build/test/guidelines)
│
├── backport_bench/              # Core package (CLI + benchmark engine)
│   ├── cli.py                   # Click CLI entry point
│   ├── config.py                # YAML parsing + Pydantic models
│   ├── dataset.py               # CSV loading, filtering
│   ├── runner.py                # Single-run orchestration pipeline
│   ├── git_ops.py               # Git operations (clone, branch, diff)
│   ├── evaluator.py             # Semantic diff + guideline checking
│   ├── results.py               # Result storage
│   └── variables.py             # Environment variable building
│
├── tests/                       # Orchestrator test suite
│
├── leaderboard/                 # Standalone Gradio app
│   ├── app.py                   # Gradio app entry point
│   ├── data_loader.py           # Result JSON file reading
│   ├── about.md                 # About tab content
│   └── tests/                   # Leaderboard test suite
│
├── results/                     # Per-run result JSON files
│   └── aggregated/              # Aggregated files for leaderboard
│
├── diffs/                       # Retained diffs for debugging
└── projects/                    # Cached repository clones
```

## How It Works

### 1. Dataset

A curated set of 36 known-good backports from 4 open-source projects serves as ground truth. Each entry contains:

- Repository identifier
- Original commit SHA (the fix on the source branch)
- Backport commit SHA (the known-good backport on the target branch)
- Classification (Easy, Medium, Hard) based on complexity metrics

Classification is computed automatically by comparing normalized diffs:

| Complexity | Count | % | Description |
|---|---|---|---|
| **Easy** | 12 | 33.3% | Original and backport are nearly identical |
| **Medium** | 12 | 33.3% | Some adaptations needed (context differences, imports) |
| **Hard** | 12 | 33.3% | Significant divergence (different files, API changes) |

### 2. Run Pipeline

For each backport entry, the orchestrator:

1. Clones the repository and sets up branches
2. Extracts the known-good backport diff
3. Invokes the tool under test to generate a candidate diff
4. Evaluates semantic equivalence using an LLM judge
5. Checks guideline adherence (if repo has contributing guidelines)
6. Optionally verifies that applying the diff introduces no new test failures
7. Collects metrics (time, cost, tokens)
8. Stores the result as JSON

### 3. Leaderboard

Results are aggregated by tool and displayed in two views:

- **Leaderboard tab** — One row per tool, showing average pass rate across benchmarks
- **Benchmark Runs tab** — One row per individual run, with detailed metrics

The leaderboard is a Gradio web app that reads aggregated JSON result files and auto-refreshes to pick up new results.

## Adding a Tool

Every tool must satisfy a simple command contract — three shell commands that the orchestrator invokes:

| Command | Required | Description |
|---|---|---|
| `setup` | No | Prepare config, credentials, or working state |
| `generate_diff` | Yes | Run the backporting logic; write diff to `${PIPELINE_DIFF_PATH}` |
| `get_stats` | No | Print JSON metrics to stdout |

The orchestrator provides environment variables for all commands:

| Variable | Description |
|---|---|
| `${REPO}` | Repository identifier (e.g., `line/armeria`) |
| `${ORIG_SHA}` | SHA of the original fix commit |
| `${BACKPORT_SHA}` | SHA of the known-good backport |
| `${TARGET_WORKSPACE}` | Path to the isolated worktree for the target branch |
| `${PIPELINE_DIFF_PATH}` | Path where `generate_diff` must write output |
| `${ORIGINAL_DIFF_PATH}` | Path to the known-good backport diff |

Tool-specific `config` values are exposed as `${CONFIG_<KEY>}` (uppercased). See [config.example.yaml](config.example.yaml) for a complete example.

## Contributing

To add a new backport entry to the dataset:

```bash
backport-bench add-backport --repo owner/repo --original <sha> --backport <sha>
```

This will:
1. Validate both commits are reachable
2. Compute complexity classification
3. Auto-detect repo metadata (build/test commands, guidelines)
4. Append to backports.csv and repos.md

## License

See LICENSE file for details.
