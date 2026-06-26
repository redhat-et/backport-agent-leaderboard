# Backport Agent Leaderboard - Product Requirements Document

## Overview

Backport Agent Leaderboard a benchmarking platform that evaluates the effectiveness of automated backporting tools. Given a curated dataset of known-good backports from open-source projects, the system runs each backporting tool against the same inputs and measures whether the tool produces a semantically equivalent diff. Results are aggregated into a leaderboard that ranks tools (and their configurations) by accuracy and efficiency.

## Problem Statement

Multiple tools and approaches exist for automating the backporting of commits across branches (e.g., cherry-pick assistants, LLM-based diff generators). There is no standardized way to compare their effectiveness. Teams evaluating these tools must run ad-hoc tests with no common baseline, making it difficult to know which tool, model, or configuration produces the best results.

## Goals

1. **Standardized evaluation** - Provide a reproducible benchmark suite for backporting tools using real-world commits from diverse open-source projects.
2. **Tool-agnostic** - Support plugging in any backporting tool via a common interface.
3. **Configuration-aware** - Treat the same tool configured with different LLMs (or other parameters) as distinct entries on the leaderboard.
4. **Leaderboard** - Produce a ranked comparison of tools across accuracy, cost, speed, and token efficiency.

## Core Concepts

### Backport Dataset

A curated set of known-good backports sourced from open-source repositories. Each entry consists of:

| Field | Description |
|---|---|
| `repo` | The source repository (e.g., `line/armeria`) |
| `original_commit` | The SHA of the original fix on the source branch |
| `backport_commit` | The SHA of the known-good backport on the target branch |
| `classification` | Complexity label (`Easy`, `Medium`, or `Hard`) based on how much the backport diff diverges from the original fix |
| `reason` | Semicolon-separated comparison metrics used to assign the classification (see below) |

The `reason` field records how the original and backport patches compare after normalization (metadata, context lines, and line numbers stripped). Metrics:

| Metric | Description |
|---|---|
| `similarity` | Sequence similarity ratio (0.00–1.00) between the normalized text of the original and backport patches. Higher values mean the changed content is nearly identical; lower values indicate substantial textual divergence. |
| `file_overlap` | File-set overlap ratio (0.00–1.00) between the two patches. Measures how many of the changed files appear in both diffs versus files changed in only one. Higher values mean the backport modified the same files as the original; lower values mean it touched a different set of files. |
| `size_ratio` | Relative size of the normalized patches (0.00–1.00), computed as the ratio of the smaller patch to the larger patch by changed-line count. Values near 1.00 mean similar scope; lower values mean one patch is substantially smaller than the other. |
| `orig_files` | Number of files modified in the original commit's patch. |
| `back_files` | Number of files modified in the backport commit's patch. |

The dataset spans multiple languages, project sizes, and diff complexities. Classification is computed by comparing normalized patches from the original and backport commits via sequence similarity and file-overlap metrics. It serves as ground truth: the backport commit's diff is the correct answer.

Each repository in the dataset is described in [`repos.md`](repos.md), which documents the toolchain, build/test commands, and contributing conventions needed to work with that project. Columns:

| Column | Description |
|---|---|
| `Repo` | Repository identifier (`owner/name`, matching the `repo` field in the dataset) |
| `Technology` | Primary languages and a brief summary of what the project does |
| `Prerequisites` | Required toolchain versions, system packages, and external services needed to build and test |
| `Build` | Command(s) to compile or build the project |
| `Test` | Command(s) to run the project's test suite |
| `Guidelines` | Contributing conventions, style guides, linting rules, and review requirements |

### Tool

A backporting tool is any system that, given an original commit and a target branch, produces a diff that applies the same logical change to the target branch. Examples: Amalgamator, Claude Code, Copilot, Graphite, custom scripts.

### Tool Configuration

A tool may be run with different settings that materially affect its output. The most common variable is the underlying LLM, but configurations may also differ by prompt strategy, context window usage, retry policy, or any tool-specific parameter.

Each tool definition includes a `display_name` that serves as its identity on the leaderboard. Different configurations of the same underlying tool are represented as separate tool definitions, each with its own `display_name`. For example:

- `Amalgamator - Opus 4.6`
- `Amalgamator - Sonnet 4.6`
- `Claude Code - Opus 4.6`
- `Claude Code - Opus 4.6 w/ superpowers`

The `display_name` is the sole identifier for a leaderboard entry. Two entries with the same `display_name` are the same entry; two entries with different `display_name` values are distinct, even if they use the same underlying tool.

### Run

A single execution of a tool configuration against one backport entry. A run produces:

| Output | Description |
|---|---|
| `semantic_equivalence` | `PASS` if the generated diff is semantically equivalent to the known-good backport; `FAIL` otherwise |
| `semantic_difference_reason` | When `semantic_equivalence = FAIL`, a brief explanation of why the generated diff is not semantically equivalent to the known-good backport; `null` otherwise |
| `guideline_adherence` | `PASS` if the generated diff adheres to the repository's contributing guidelines (see [`repos.md`](repos.md)); `FAIL` otherwise |
| `guideline_reason` | When `guideline_adherence = FAIL`, a brief explanation of which guideline(s) the generated diff violates; `null` otherwise |
| `test_success` | `PASS` if applying the generated diff introduces no new test failures; `FAIL` if it does; `SKIPPED` if `verify_tests` is `false` in the configuration |
| `error` | Error message if the run could not complete (setup failure, tool crash, timeout) |
| `diff_lines` | Number of lines differing between the generated and expected diffs (0 = exact match) |
| `time` | Wall-clock time in seconds |
| `llm_calls` | Number of LLM API calls made |
| `cost` | Total LLM API cost in USD
| `input tokens` | Total input tokens | |
| `tokens` | Total output tokens |
| `tokens` | Total tokens consumed |

### Leaderboard

An aggregated view that ranks entries by their performance across the full dataset (or a filtered subset). Primary ranking metric is **pass rate** (% of backports where `semantic_equivalence = PASS`). Secondary metrics include guideline_adherence rate, test_success_rate, median cost, median time, and median token usage.

## Functional Requirements

### FR-1: Command Contract

Every backporting tool must satisfy a command contract — a set of shell commands that the orchestrator invokes at each stage of a benchmark run. Tools define these commands in the configuration file (see FR-2). The contract is language- and runtime-agnostic; any tool that can be invoked from the shell can participate.

#### Commands

| Command | Required | Description |
|---|---|---|
| `setup` | No | Prepare any configuration files, credentials, or working state the tool requires before generating a diff. This is a pre-step — no diff output is expected. |
| `generate_diff` | Yes | Execute the tool's backporting logic. Must write the resulting diff to the path specified by `${PIPELINE_DIFF_PATH}`. This is the core operation under benchmark. |
| `get_stats` | No | Emit a JSON object to stdout containing structured metrics for the run. If omitted, the orchestrator records only pass/fail and wall-clock time. |

#### `get_stats` Output Schema

When provided, the `get_stats` command must print a single JSON object to stdout:

```json
{
  "time": 180.5,
  "llm_calls": 3,
  "cost": 0.74,
  "input_tokens": 200000,
  "output_tokens": 4800
}
```

| Field | Type | Description |
|---|---|---|
| `time` | float | Wall-clock seconds the tool spent generating the diff |
| `llm_calls` | int | Number of LLM API calls made |
| `cost` | float | Total LLM API cost in USD |
| `input_tokens` | int | Total input tokens consumed |
| `output_tokens` | int | Total output tokens consumed |

All fields are optional — the tool may emit a subset. Unknown fields are ignored.

#### Orchestrator-Provided Variables

The orchestrator sets the following environment variables before invoking each command:

| Variable | Description |
|---|---|
| `${REPO}` | Repository identifier (e.g., `line/armeria`) |
| `${ORIG_SHA}` | SHA of the original fix commit |
| `${BACKPORT_SHA}` | SHA of the known-good backport commit |
| `${RUN_KEY}` | Unique key for this run (`{orig_sha}-{backport_sha}`) |
| `${PROJECT_PATH}` | Absolute path to the local project clone |
| `${BUILD_CMD}` | Command to build the repo |
| `${TEST_COMMAND}` | Command to test the repo |
| `${REPO_GUIDELINES}` | Contributing conventions, style guides, linting rules, and review requirements for the repo |
| `${SOURCE_BRANCH}` | Branch containing the original commit |
| `${TARGET_WORKSPACE}` | Path to the isolated worktree for the branch that will contain the generated backport |
| `${ORIGINAL_DIFF_PATH}` | Path where the orchestrator writes the known-good backport diff (extracted from `${BACKPORT_SHA}`) |
| `${PIPELINE_DIFF_PATH}` | Path to the tool-generated diff (also where `generate_diff` must write its output) |

#### Exit Codes

All commands use exit code 0 for success. A non-zero exit code is treated as an error — the run is recorded with an error status and the orchestrator moves to the next backport entry.

### FR-2: Configuration File

The system is driven by a single YAML configuration file. This file defines global settings (semantic diff model, guideline check model, test verification, default tool) and one or more tool definitions. Each tool definition specifies the shell commands that satisfy the command contract (FR-1), a display name for the leaderboard, and any tool-specific parameters.

**Configuration file (YAML):**

```yaml
# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------
semantic_diff:
  model: "claude-opus-4-6"              # LLM used to judge semantic equivalence
  command: |                             # command to run for the equivalence check
    claude -m ${SEMANTIC_DIFF_MODEL} -p "Compare @${ORIGINAL_DIFF_PATH} and @${PIPELINE_DIFF_PATH} and determine if they are semantically equivalent.
    Respond with a single JSON object and no other text:
    - If equivalent: {\"equivalent\": true}
    - If not equivalent: {\"equivalent\": false, \"reason\": \"<brief explanation of the semantic difference>\"}"

guideline_check:
  model: "claude-opus-4-6"              # LLM used to judge guideline adherence
  command: |                             # command to run for the guideline check
    claude -m ${GUIDELINE_CHECK_MODEL} -p "Review @${PIPELINE_DIFF_PATH} against the following contributing guidelines: ${REPO_GUIDELINES}
    Respond with a single JSON object and no other text:
    - If adheres: {\"adheres\": true}
    - If not adheres: {\"adheres\": false, \"reason\": \"<brief explanation of the guideline violation>\"}"

default_tool: "amalgamator-opus"         # tool to use when --tool is not passed on CLI
timeout: 1800                            # max seconds a tool may run before the run is killed and recorded as an error
verify_tests: false                      # if true, run tests before/after diff and set test_success; if false, test_success is SKIPPED

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
tools:
  amalgamator-opus:
    display_name: "Amalgamator / Opus 4.6"  # name shown on the leaderboard
    model: "claude-opus-4-6"
    config:
      tool_location: "/path/to/amalgamator"
      workdir: "/tmp/amalgamator"
      config_file: "/tmp/amalgamator/${RUN_KEY}-config.yaml"

    commands:
      setup: |
        cat > ${CONFIG_CONFIG_FILE} <<EOF
        issue_id: "${RUN_KEY}"
        bug_description: "${ORIG_SHA}"
        repository:
          source_path: "${PROJECT_PATH}"
          workdir: "${CONFIG_WORKDIR}/${RUN_KEY}"
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
        python -m auto_bug_fix.run_bug_fix ${CONFIG_CONFIG_FILE} &&
        RUN_DIR=$(ls -d ${CONFIG_TOOL_LOCATION}/runs/${RUN_KEY}* | sort | tail -1) &&
        cp ${ORIGINAL_DIFF_PATH} "$RUN_DIR/original.diff" &&
        cp ${PIPELINE_DIFF_PATH} "$RUN_DIR/pipeline.diff"
      get_stats: |
        LOG=$(ls -d ${CONFIG_TOOL_LOCATION}/runs/${RUN_KEY}* | sort | tail -1)/run_log.txt
        echo $(grep -E '^TOTAL' "$LOG" | awk '{
          gsub(/s$/, "", $2); gsub(/,/, "", $4); gsub(/\$/, "", $5);
          printf "{\"time\": %s, \"llm_calls\": %s, \"cost\": %s, \"input_tokens\": %s}", $2, $3, $5, $4
        }')

  amalgamator-sonnet:
    display_name: "Amalgamator / Sonnet 4.6"
    model: "claude-sonnet-4-6"
    config:
      tool_location: "/path/to/amalgamator"
      workdir: "/tmp/amalgamator"
      config_file: "/tmp/amalgamator/${RUN_KEY}-config.yaml"

    commands:
      setup: |
        cat > ${CONFIG_CONFIG_FILE} <<EOF
        issue_id: "${RUN_KEY}"
        bug_description: "${ORIG_SHA}"
        repository:
          source_path: "${PROJECT_PATH}"
          workdir: "${CONFIG_WORKDIR}/${RUN_KEY}"
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
        python -m auto_bug_fix.run_bug_fix ${CONFIG_CONFIG_FILE} &&
        RUN_DIR=$(ls -d ${CONFIG_TOOL_LOCATION}/runs/${RUN_KEY}* | sort | tail -1) &&
        cp ${ORIGINAL_DIFF_PATH} "$RUN_DIR/original.diff" &&
        cp ${PIPELINE_DIFF_PATH} "$RUN_DIR/pipeline.diff"
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

#### Semantic Diff Output Schema

The `semantic_diff.command` must print a single JSON object to stdout. The orchestrator maps this to `semantic_equivalence` and `semantic_difference_reason`:

```json
{"equivalent": true}
```

```json
{"equivalent": false, "reason": "The generated diff adds a null check but misses the retry logic present in the known-good backport."}
```

| Field | Type | Description |
|---|---|---|
| `equivalent` | boolean | `true` if the diffs are semantically equivalent; `false` otherwise |
| `reason` | string | Required when `equivalent` is `false`. Brief explanation of the semantic difference. Ignored when `equivalent` is `true`. |

When `equivalent` is `true`, the orchestrator sets `semantic_equivalence = PASS` and `semantic_difference_reason = null`. When `equivalent` is `false`, it sets `semantic_equivalence = FAIL` and `semantic_difference_reason` to the value of `reason`.

#### Guideline Check Output Schema

The `guideline_check.command` must print a single JSON object to stdout. The orchestrator maps this to `guideline_adherence` and `guideline_reason`:

```json
{"adheres": true}
```

```json
{"adheres": false, "reason": "Commit message is missing the required DCO sign-off."}
```

| Field | Type | Description |
|---|---|---|
| `adheres` | boolean | `true` if the diff adheres to the repository's contributing guidelines; `false` otherwise |
| `reason` | string | Required when `adheres` is `false`. Brief explanation of the guideline violation. Ignored when `adheres` is `true`. |

When `adheres` is `true`, the orchestrator sets `guideline_adherence = PASS` and `guideline_reason = null`. When `adheres` is `false`, it sets `guideline_adherence = FAIL` and `guideline_reason` to the value of `reason`.

#### Test Verification

The global `verify_tests` setting controls whether the orchestrator checks that applying the generated diff does not introduce new test failures.

| Value | Behavior |
|---|---|
| `true` | Before diff generation, run `${TEST_COMMAND}` on the target branch and store the baseline results. After diff generation, apply the generated diff and run `${TEST_COMMAND}` again. Set `test_success` to `PASS` if no new test failures appear compared to the baseline; set `test_success` to `FAIL` otherwise. |
| `false` | Skip all test runs and set `test_success` to `SKIPPED`. |

The test command for each repository comes from [`repos.md`](repos.md) and is exposed to the orchestrator as `${TEST_COMMAND}`.

### FR-3: Backport Dataset Management

- The system must consume a dataset file (CSV or equivalent) with columns: `repo`, `original_commit`, `backport_commit`, `classification`, `reason`.
- The system must support adding new entries without disrupting existing results.
- The system must clone and cache project repositories locally (under `projects/`).

### FR-4: Run Orchestration

For each `(backport_entry, tool_config)` pair:

1. **Repository setup** - Check out the project, identify the source branch containing the original commit, create the target branch at the commit preceding the backport, and create a baseline tag (`target-before`).
2. **Known-good diff capture** - Extract the unified diff for the backport commit (`${BACKPORT_SHA}`) and write it to `${ORIGINAL_DIFF_PATH}`. This is the ground-truth patch the tool's output will be compared against.
3. **Baseline test run** *(when `verify_tests` is `true`)* - Run the repository's test command (`${TEST_COMMAND}`) on the target branch in `${TARGET_WORKSPACE}` and store the results as the baseline.
4. **Diff generation** - Invoke the tool plugin to produce a candidate diff and write it to `${PIPELINE_DIFF_PATH}`.
5. **Post-diff test run** *(when `verify_tests` is `true`)* - Apply the generated diff to `${TARGET_WORKSPACE}`, run `${TEST_COMMAND}` again, and compare the results to the baseline. Set `test_success` to `PASS` if no new test failures were introduced, or `FAIL` otherwise. When `verify_tests` is `false`, set `test_success` to `SKIPPED`.
6. **Equivalence check** - Compare the candidate diff against the known-good backport diff at `${ORIGINAL_DIFF_PATH}`. Semantic equivalence (not byte-identical) is the standard; the comparison should tolerate ordering differences, whitespace, and context-line variation. When the diffs are not equivalent, record a `semantic_difference_reason` explaining why.
7. **Guideline check** - Review the generated diff against the repository's contributing guidelines (from [`repos.md`](repos.md)). When the diff does not adhere, record a `guideline_reason` explaining why.
8. **Metrics collection** - Gather structured stats from the tool plugin.
9. **Result recording** - Write the outcome (pass/fail/error + metrics) to persistent storage.
10. **Cleanup** - Remove all temporary branches, tags, and worktrees to leave the repository in a clean state.

The orchestrator must be resilient to individual run failures (one error must not abort the entire batch) and must support resuming a batch from where it left off (skip entries that already have results).

### FR-5: Result Storage

- Results must be stored per `(display_name, repo, original_commit, backport_commit)`.
- The same backport entry may have results from multiple tool configurations.
- Results must be append-safe and support concurrent or sequential batch runs from different tool configs without overwriting each other.
- Generated diffs (`original.diff`, `pipeline.diff`) should be retained for debugging, organized by tool config and run key.

### FR-6: Leaderboard

The leaderboard is a hosted web application (modeled after the [Coding Agent Leaderboard](https://huggingface.co/spaces/taagarwa/coding-agent-leaderboard)) that provides interactive exploration of benchmark results.

#### Layout and Navigation

- **Header** - Displays summary stats: total results, number of distinct tools, number of distinct configurations, and number of backport entries evaluated.
- **Tabs**:
  - **Leaderboard** - Aggregated view: one row per `display_name`, with benchmark scores pivoted into columns.
  - **Benchmark Runs** - Detailed view: one row per individual run, showing per-run metrics.
  - **About** - Explains the benchmark methodology, how to read the table, and how to submit results.

#### Leaderboard Tab (Aggregated)

One row per `display_name`. Columns:

| Column | Description |
|---|---|
| Category | Icon indicating open-source vs. proprietary |
| Name | The tool's `display_name` (linked to tool URL) |
| Avg Score | Simple average of pass rates across all benchmark subsets |
| *Per-benchmark columns* | Pass rate for each benchmark subset (e.g., by repository or language), pivoted into separate columns |

Sorted by Avg Score descending by default. All columns sortable.

#### Benchmark Runs Tab (Detailed)

One row per individual benchmark run. Columns:

| Column | Description |
|---|---|
| Category | Open-source vs. proprietary indicator |
| Name | The tool's `display_name` (linked) |
| Benchmark | Which benchmark subset this run covers (linked) |
| Score | Pass rate as a percentage |
| Avg Cost Per Task (USD) | Mean cost per backport entry |
| Avg Seconds Per Task | Mean wall-clock time per backport entry |
| Avg Input Tokens Per Task | Mean input tokens per backport entry |
| Avg Output Tokens Per Task | Mean output tokens per backport entry |

Default columns shown: Category, Name, Benchmark, Score, Avg Cost Per Task. Additional columns selectable via a column picker.

#### Interactive Features

- **Search** - Free-text search across the Name column.
- **Column picker** - Users can show/hide columns to focus on metrics they care about.
- **Filters** (checkbox and slider):
  - **Category** - Filter by open-source vs. proprietary.
  - **Name** - Filter to specific tool entries.
  - **Repository / Language** - Filter by benchmark subset.
- **Sorting** - Click any column header to sort ascending/descending.
- **Linked entries** - Tool names and benchmark names link to external URLs (tool homepage, benchmark dataset).

#### Result Data Format

Each benchmark run is stored as a self-contained JSON file (one file per run) containing:

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
    "n_input_tokens": 50000000,
    "n_output_tokens": 1200000,
    "n_total_tokens": 51200000,
    "total_time_seconds": 45000,
    "cost_usd": 185.50,
    "mean_input_tokens_per_task": 200000,
    "mean_output_tokens_per_task": 4800,
    "mean_cost_usd_per_task": 0.74,
    "mean_time_seconds_per_task": 180
  }
}
```

The leaderboard reads all JSON files from a results directory and aggregates them into the two views. The leaderboard is a view over the data — it can be fully regenerated from the JSON files at any time.

#### Hosting

The leaderboard should be deployable as a Gradio app on Hugging Face Spaces, OpenShift, or equivalent platforms. It should auto-refresh periodically to pick up new results.

### FR-7: CLI Interface

The system must be operable from the command line:

| Command | Purpose |
|---|---|
| `run --tool <key>` | Execute a benchmark run for a tool (by config key) against the full dataset (or a subset via `--repo`, `--limit`, `--classification <Easy\|Medium\|Hard>`). Uses `default_tool` if `--tool` is omitted. |
| `results --tool <key>` | Display results for a specific tool entry |
| `leaderboard` | Display the leaderboard |
| `add-backport --repo <repo> --original <sha> --backport <sha>` | Add an entry to the dataset |

The `run` command supports filtering the dataset before execution:

| Flag | Description |
|---|---|
| `--repo <repo>` | Run only entries for the given repository (e.g., `line/armeria`) |
| `--limit <n>` | Run at most `n` entries from the filtered set |
| `--classification <Easy\|Medium\|Hard>` | Run only entries with the given complexity classification |
| `--original <sha>` | Run a single entry by original commit SHA |
| `--backport <sha>` | Run a single entry by backport commit SHA (used with `--original`) |

### FR-8: Display Name as Identity

Each tool definition's `display_name` is its identity across the system. When a tool is defined with a different `display_name`, the system must:

- Store results under that `display_name` (not overwrite results from other entries).
- Show the `display_name` as the entry's label on the leaderboard.
- Allow re-running a specific entry without affecting others.

## Non-Functional Requirements

### NFR-1: Reproducibility

Runs must be deterministic with respect to repository state. The system must pin the exact commit SHAs used for branching so that results are comparable across runs and machines.

### NFR-2: Isolation

Each run must operate in an isolated worktree or copy of the repository. Concurrent runs against the same project (from different tool configs) must not interfere with each other.

### NFR-3: Performance

The system must support running backports in parallel (configurable concurrency) to reduce total benchmark time. The bottleneck is LLM API latency, not local compute.

### NFR-4: Observability

- All runs must be logged (stdout/stderr captured per run).
- Errors must be recorded with enough context to diagnose whether the failure was in the tool, the benchmark harness, or the repository setup.

### NFR-5: Extensibility

Adding a new tool must require only:

1. Implementing the tool plugin interface.
2. Registering the tool with the orchestrator.

No changes to the orchestrator, result storage, or leaderboard logic should be needed.

## Data Model

```
BackportEntry
  repo: string
  original_commit: string (SHA)
  backport_commit: string (SHA)

ToolConfig
  display_name: string          (leaderboard identity)
  model: string | null
  config: dict                  (arbitrary tool-specific parameters)

RunResult
  backport_entry: BackportEntry
  tool_config: ToolConfig
  semantic_equivalence: PASS | FAIL | null
  semantic_difference_reason: string | null   # populated when semantic_equivalence = FAIL
  guideline_adherence: PASS | FAIL | null
  guideline_reason: string | null             # populated when guideline_adherence = FAIL
  test_success: PASS | FAIL | SKIPPED | null
  error_message: string | null
  diff_lines: int
  time_seconds: float
  llm_calls: int
  cost_usd: float
  tokens: int
  timestamp: datetime
```

