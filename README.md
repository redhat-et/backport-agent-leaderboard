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

See [config.example.yaml](config.example.yaml) for a complete reference.

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
