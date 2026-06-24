# Backport Agent Leaderboard

A benchmarking platform that evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects. Tools are ranked by accuracy, cost, speed, and token efficiency on a hosted leaderboard.

## How It Works

1. **Dataset** — A CSV of known-good backports (repo, original commit SHA, backport commit SHA) serves as ground truth.
2. **Run** — The orchestrator checks out each repo, sets up branches, invokes the tool under test, and compares the generated diff against the known-good backport using semantic equivalence (not byte-identical matching).
3. **Leaderboard** — Results are aggregated into a ranked comparison, deployable as a Gradio app on Hugging Face Spaces.

## Quick Start

```bash
# Run benchmarks with a specific tool
./run --tool amalgamator-opus

# Run against a single repo or limit entries
./run --tool amalgamator-opus --repo line/armeria --limit 10

# Run a specific backport entry by commit SHAs
./run --tool amalgamator-opus --original <orig_sha> --backport <backport_sha>

# View results for a tool
./results --tool amalgamator-opus

# Display the leaderboard
./leaderboard

# Add a new backport entry to the dataset
./add-backport --repo owner/repo --original <sha> --backport <sha>
```

## Configuration

The system is driven by a single YAML config file that defines global settings and tool definitions.

```yaml
semantic_diff:
  model: "claude-opus-4-6"
  command: |
    claude -m ${SEMANTIC_DIFF_MODEL} -p "Compare @${ORIGINAL_DIFF_PATH} and @${PIPELINE_DIFF_PATH}..."

default_tool: "amalgamator-opus"
timeout: 1800

tools:
  amalgamator-opus:
    display_name: "Amalgamator / Opus 4.6"
    model: "claude-opus-4-6"
    config:
      tool_location: "/path/to/amalgamator"
    commands:
      setup: |
        # prepare config files, credentials, working state
      generate_diff: |
        # produce a diff and write it to ${PIPELINE_DIFF_PATH}
      get_stats: |
        # emit JSON metrics to stdout
```

## Adding a Tool

Every tool must satisfy a simple command contract — three shell commands the orchestrator calls during a run:

| Command | Required | Description |
|---|---|---|
| `setup` | No | Prepare config, credentials, or working state before generating a diff. |
| `generate_diff` | Yes | Run the backporting logic. Must write the resulting diff to `${PIPELINE_DIFF_PATH}`. |
| `get_stats` | No | Print a JSON object to stdout with run metrics. |

### Environment Variables

The orchestrator provides these variables to every command:

| Variable | Description |
|---|---|
| `${REPO}` | Repository identifier (e.g., `line/armeria`) |
| `${ORIG_SHA}` | SHA of the original fix commit |
| `${BACKPORT_SHA}` | SHA of the known-good backport commit |
| `${RUN_KEY}` | Unique key for this run (`{orig_sha}-{backport_sha}`) |
| `${PROJECT_PATH}` | Absolute path to the local project clone |
| `${SOURCE_BRANCH}` | Branch containing the original commit |
| `${TARGET_WORKSPACE}` | Path to the isolated worktree for the target branch |
| `${ORIGINAL_DIFF_PATH}` | Path to the known-good backport diff |
| `${PIPELINE_DIFF_PATH}` | Path where `generate_diff` must write its output |

Tool-specific `config` values are exposed as `${CONFIG_<KEY>}` (uppercased).

### Stats Output Schema

The `get_stats` command should print JSON to stdout:

```json
{
  "time": 180.5,
  "llm_calls": 3,
  "cost": 0.74,
  "input_tokens": 200000,
  "output_tokens": 4800
}
```

All fields are optional. Unknown fields are ignored.

## Leaderboard

The leaderboard is a hosted web app with two main views:

**Leaderboard tab** — One row per tool. Shows pass rate averaged across benchmark subsets, with per-benchmark columns.

**Benchmark Runs tab** — One row per individual run. Shows score, average cost, time, and token usage per task. Additional columns available via a column picker.

Both views support search, sorting, filtering by category (open-source / proprietary), and filtering by repository or language.

### Result Data Format

Each benchmark run is stored as a self-contained JSON file:

```json
{
  "benchmark": {
    "name": "backportbench-java",
    "repo": "owner/backportbench",
    "num_tasks": 250,
    "url": "https://..."
  },
  "tool": {
    "display_name": "Amalgamator / Opus 4.6",
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

The leaderboard reads all JSON files from a results directory and can be fully regenerated at any time.

## Design Principles

- **Tool-agnostic** — Any tool invocable from the shell can participate via the command contract.
- **Configuration-aware** — The same tool with different LLMs or settings appears as separate leaderboard entries, each identified by its `display_name`.
- **Reproducible** — Runs pin exact commit SHAs so results are comparable across machines.
- **Isolated** — Each run operates in its own worktree. Concurrent runs against the same repo don't interfere.
- **Resilient** — Individual run failures don't abort the batch. Runs can be resumed from where they left off.
- **Extensible** — Adding a new tool requires only defining its commands in the config file. No orchestrator or leaderboard changes needed.
