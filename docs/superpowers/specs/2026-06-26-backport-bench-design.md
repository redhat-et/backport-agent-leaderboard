# Backport Agent Leaderboard — Design Spec

## Overview

This document describes the technical design for the Backport Agent Leaderboard, a benchmarking platform that evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects. The system consists of two independent packages: a Python CLI orchestrator that runs benchmarks and stores results, and a standalone Gradio leaderboard app that visualizes them.

Requirements are defined in [PRD.md](../../../PRD.md).

---

## 1. Project Structure

```
backport-agent-leaderboard/
├── PRD.md
├── README.md
├── repos.md
├── backports.csv
│
├── orchestrator/                    # CLI + benchmark engine
│   ├── pyproject.toml
│   ├── backport_bench/
│   │   ├── __init__.py
│   │   ├── cli.py                   # Click CLI entry point
│   │   ├── config.py                # YAML parsing + Pydantic models
│   │   ├── dataset.py               # CSV loading, filtering, add-backport
│   │   ├── runner.py                # Single-run orchestration pipeline
│   │   ├── git_ops.py               # Clone, branch, worktree, diff extraction
│   │   ├── evaluator.py             # Semantic diff + guideline check invocation
│   │   ├── results.py               # Result storage (read/write JSON)
│   │   └── variables.py             # Environment variable building for commands
│   └── tests/
│
├── leaderboard/                     # Standalone Gradio app
│   ├── pyproject.toml
│   ├── app.py                       # Gradio app entry point
│   ├── data_loader.py               # Read result JSON files
│   ├── about.md                     # Content for the About tab
│   └── requirements.txt
│
├── results/                         # Per-run result JSON files
│   ├── *.json
│   └── aggregated/                  # Aggregated files for the leaderboard
│       └── *.json
│
├── diffs/                           # Retained diffs for debugging
│   └── <tool-key>/
│       └── <orig-sha-short>__<backport-sha-short>/
│           ├── original.diff
│           └── pipeline.diff
│
└── projects/                        # Cached repo clones
    └── <owner>__<repo>/
```

---

## 2. Configuration System (`config.py`)

The YAML config file is parsed into Pydantic v2 models. Variable expansion happens at run-time, not parse-time.

### Pydantic Models

```python
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
```

### Variable Expansion (`variables.py`)

Commands reference variables like `${ORIG_SHA}` and `${CONFIG_TOOL_LOCATION}`. These are resolved by setting them as environment variables on the subprocess call, letting the shell resolve `${VAR}` natively.

The variable dict is built per-run by merging three sources:

1. **Orchestrator-provided variables** — `REPO`, `ORIG_SHA`, `BACKPORT_SHA`, `RUN_KEY`, `PROJECT_PATH`, `SOURCE_BRANCH`, `TARGET_WORKSPACE`, `ORIGINAL_DIFF_PATH`, `PIPELINE_DIFF_PATH`, `BUILD_CMD`, `TEST_COMMAND`, `REPO_GUIDELINES`
2. **Tool config variables** — the tool's `model` field becomes `CONFIG_MODEL`, and each key in `config:` is uppercased and prefixed with `CONFIG_`. E.g., `config.tool_location` becomes `CONFIG_TOOL_LOCATION`
3. **Evaluation model variables** — `SEMANTIC_DIFF_MODEL` (from `semantic_diff.model`) and `GUIDELINE_CHECK_MODEL` (from `guideline_check.model`)

---

## 3. Dataset Management (`dataset.py`)

### Data Model

```python
@dataclass
class BackportEntry:
    repo: str
    original_commit: str
    backport_commit: str
    classification: str  # "Easy", "Medium", "Hard"
    similarity: float       # 0.00–1.00, sequence similarity of normalized patches
    file_overlap: float     # 0.00–1.00, file-set overlap between patches
    size_ratio: float       # 0.00–1.00, smaller/larger patch by changed-line count
    orig_files: int         # files modified in the original commit
    back_files: int         # files modified in the backport commit
```

The CSV `reason` column (e.g., `"similarity=0.95; file_overlap=0.60; size_ratio=0.97; orig_files=5; back_files=3"`) is parsed into these five fields on load. When writing back to CSV (via `add-backport`), the fields are serialized back into the semicolon-delimited `reason` string to preserve the existing file format.

### Loading and Filtering

The CSV is loaded into a list of `BackportEntry`. CLI filters are applied in this order:

1. `--repo` — match `entry.repo`
2. `--classification` — match `entry.classification`
3. `--original` / `--backport` — match specific SHAs (AND'd when both present)
4. `--limit` — truncate the filtered list to N entries

### Adding Entries (`add-backport`)

1. Clone/fetch the repo if not already cached
2. Validate that the original commit is reachable from at least one branch (`git branch -r --contains <sha>`). Reject with a clear error if not.
3. If the repo is not in `repos.md` and `--add-repo` is set (default: `true`), detect repo metadata and append a new row:
   - **Technology** — detect from file extensions and any language metadata in the repo
   - **Prerequisites** — inspect build files (`pom.xml`, `go.mod`, `pyproject.toml`, `package.json`, etc.) for required toolchain versions
   - **Build** — a single shell command to build the project. Detect from common build files (`Makefile`, `mvnw`, `gradlew`, `cargo`, `bazel`, etc.)
   - **Test** — a single shell command to run the project's test suite. Detect from build files or CI configs (`.github/workflows/`, `Makefile`, `tox.ini`, etc.)
   - **Guidelines** — check for `CONTRIBUTING.md`, `CONTRIBUTING.rst`, `.editorconfig`, linter configs
   - Print the detected metadata for the user to review before writing
   - With `--no-add-repo`, the backport entry is still added to `backports.csv` — the repo just won't have build/test/guideline metadata
4. Extract normalized diffs for both commits
5. Compute metrics: `similarity`, `file_overlap`, `size_ratio`, `orig_files`, `back_files`
6. Assign classification:
   - **Easy**: similarity >= 0.90 AND file_overlap >= 0.80
   - **Medium**: similarity >= 0.50 OR file_overlap >= 0.50 (but not Easy)
   - **Hard**: everything else
7. Append the entry to `backports.csv`

### Repo Metadata Lookup

`repos.md` is parsed into a dict keyed by repo name. A simple markdown table parser extracts `Build`, `Test`, and `Guidelines` columns. Repos not in `repos.md` still work — their `BUILD_CMD`, `TEST_COMMAND`, and `REPO_GUIDELINES` variables are set to empty strings, and `guideline_check` is skipped.

---

## 4. Git Operations (`git_ops.py`)

All git operations use `subprocess.run` calling the `git` CLI directly.

### Operations

**`clone_or_fetch(repo, projects_dir)`** — If `projects/<owner>__<repo>` exists, run `git fetch --all`. Otherwise `git clone` from `https://github.com/<owner>/<repo>.git`. Returns the project path.

**`find_source_branch(project_path, original_sha)`** — Determines which branch contains the original commit:
1. Run `git branch -r --contains <sha>`
2. Filter out HEAD pointers, prefer `main`/`master`, then shortest name
3. Fall back to local branches if no remote match

**`setup_target_branch(project_path, backport_sha)`** — Creates the target branch at the commit before the backport:
1. `git rev-parse <backport_sha>^` to find the parent
2. `git branch target <parent_sha>`

**`create_worktree(project_path, branch, worktree_path)`** — `git worktree add <worktree_path> <branch>`. Worktree path is `<project_path>/.worktrees/<run_key>`.

**`extract_diff(project_path, commit_sha)`** — `git diff <sha>^..<sha>`. Returns the diff as a string.

**`cleanup(project_path, run_key)`** — Removes the worktree, deletes the `target` branch, removes any tags. Called in a `finally` block.

---

## 5. Run Orchestration (`runner.py`)

The core pipeline. `execute_run(entry, tool, config)` returns a `RunResult`.

### Pipeline Steps

```
1.  clone_or_fetch()
2.  find_source_branch()
3.  setup_target_branch()
4.  create_worktree()
5.  extract_diff() → write to ORIGINAL_DIFF_PATH
6.  [if verify_tests] run baseline tests
7.  build_variable_dict()
8.  [if setup command defined] run setup command
9.  run generate_diff command (with timeout)
10. [if verify_tests] apply diff, run tests, compare to baseline
11. run semantic_diff command → parse JSON
12. run guideline_check command → parse JSON
13. [if get_stats defined] run get_stats → parse JSON
14. record result
15. cleanup (always, via finally)
```

### Command Execution

All commands are run via `subprocess.run(command, shell=True, env=env_dict, cwd=cwd, timeout=..., capture_output=True)`. The `cwd` for tool commands (`setup`, `generate_diff`, `get_stats`) is `TARGET_WORKSPACE` (the worktree). The `cwd` for evaluation commands (`semantic_diff`, `guideline_check`) is the project root. The variable dict is passed as environment variables — the shell resolves `${VAR}` natively.

### Timeout

`subprocess.run(..., timeout=config.timeout)` raises `TimeoutExpired`. Caught and recorded as an error result with `error_message = "Timeout after {n}s"`.

### Error Resilience

The entire `execute_run` function is wrapped in try/except. Any exception is caught and recorded as a `RunResult` with `error_message` populated. The batch loop continues to the next entry.

If the setup command exits non-zero, the run is recorded as an error and skips to cleanup.

### Resume Support

Before executing a run, check if `results/` already contains a result file for this `(tool_key, repo, original_commit, backport_commit)` tuple. If yes, skip. Makes `run` idempotent and resumable.

### RunResult

```python
@dataclass
class RunResult:
    tool_display_name: str
    tool_key: str
    repo: str
    original_commit: str
    backport_commit: str
    classification: str
    semantic_equivalence: str | None      # "PASS", "FAIL", None
    semantic_difference_reason: str | None
    guideline_adherence: str | None       # "PASS", "FAIL", None
    guideline_reason: str | None
    test_success: str | None              # "PASS", "FAIL", "SKIPPED", None
    error_message: str | None
    diff_lines: int | None
    time_seconds: float | None
    llm_calls: int | None
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    timestamp: str                        # ISO 8601
```

---

## 6. Evaluator (`evaluator.py`)

### Semantic Diff

`run_semantic_diff(config, env_dict)` → `(equivalence: str, reason: str | None)`

1. Run the `semantic_diff.command` via subprocess with the env dict
2. Parse stdout as JSON: `{"equivalent": true}` or `{"equivalent": false, "reason": "..."}`
3. Return `("PASS", None)` or `("FAIL", reason)`

### Guideline Check

`run_guideline_check(config, env_dict)` → `(adherence: str, reason: str | None)`

Same pattern. Parses `{"adheres": true}` or `{"adheres": false, "reason": "..."}`.

If the repo has no entry in `repos.md` or the Guidelines column is empty, skip and set `guideline_adherence = None`.

### Diff Line Count

`compute_diff_lines(original_diff_path, pipeline_diff_path)` → `int`

Uses `difflib.unified_diff` on normalized content (strip metadata headers, context line numbers). Counts delta lines. Returns 0 for exact match.

### JSON Parsing Resilience

LLM output can be noisy. The parser:
1. Strips leading/trailing whitespace
2. Extracts the first `{...}` block via brace-matching if non-JSON content surrounds it
3. Runs `json.loads`
4. On failure, records `None` result with `error_message = "Failed to parse output: <raw stdout>"`

---

## 7. Result Storage (`results.py`)

### Per-Run Files

Filename: `results/<tool-key>__<repo-owner>__<repo-name>__<orig-sha-8>__<backport-sha-8>.json`

Example: `results/amalgamator-opus__crate__crate__a2f572fc__c0d5e58e.json`

```json
{
  "tool_display_name": "Amalgamator / Opus 4.6",
  "tool_key": "amalgamator-opus",
  "repo": "crate/crate",
  "original_commit": "a2f572fc480380b3c2d17fd3b5e436e759723c19",
  "backport_commit": "c0d5e58eb817a0ed54aab1d9e52c68ae4ac7f73e",
  "classification": "Medium",
  "semantic_equivalence": "PASS",
  "semantic_difference_reason": null,
  "guideline_adherence": "PASS",
  "guideline_reason": null,
  "test_success": "SKIPPED",
  "error_message": null,
  "diff_lines": 0,
  "time_seconds": 180.5,
  "llm_calls": 3,
  "cost_usd": 0.74,
  "input_tokens": 200000,
  "output_tokens": 4800,
  "timestamp": "2026-06-26T14:30:00Z"
}
```

### Diff Retention

After each run, copy diffs to `diffs/<tool-key>/<orig-sha-8>__<backport-sha-8>/original.diff` and `pipeline.diff`.

### Aggregation

`aggregate_results(results_dir)` reads all per-run JSON files, groups by `tool_display_name` and benchmark subset (repo), computes aggregate metrics (score, mean cost, mean time, mean tokens), and writes one aggregated JSON file per `(tool_display_name, benchmark)` to `results/aggregated/`. These aggregated files follow the PRD's result data format and are what the leaderboard app reads.

### Resume Check

`has_result(tool_key, repo, original_commit, backport_commit)` — checks if the result file exists. Returns `bool`.

---

## 8. CLI Interface (`cli.py`)

Click-based CLI. Entry point: `backport-bench` (console script in `pyproject.toml`).

**Global option:** `--config` / `-c` — path to YAML config. Defaults to `config.yaml`.

### Subcommands

```
backport-bench run [--tool KEY] [--repo REPO] [--classification EASY|MEDIUM|HARD]
                   [--original SHA] [--backport SHA] [--limit N]
```

Loads config, filters dataset, iterates entries sequentially. Checks resume before each run. Prints one-line summaries:

```
[1/36] crate/crate a2f572fc → c0d5e58e  PASS  180.5s  $0.74
[2/36] crate/crate 3247cc6e → 1974dab1  FAIL  95.2s   $0.31  (missing retry logic)
[3/36] crate/crate 4f42b38d → c08290cc  ERROR          (timeout after 1800s)
```

Batch summary at the end: total, passed, failed, errors, skipped.

```
backport-bench results [--tool KEY] [--repo REPO] [--classification EASY|MEDIUM|HARD]
```

Reads result files, filters, prints an aligned table: repo, SHA (short), classification, equivalence, guideline adherence, cost, time.

```
backport-bench leaderboard
```

Runs `aggregate_results`, prints a summary table to stdout. CLI-only view — the Gradio app is separate.

```
backport-bench add-backport --repo REPO --original SHA --backport SHA [--add-repo/--no-add-repo]
```

Clones/fetches repo, validates branch reachability, computes classification, appends to `backports.csv`. If the repo is not in `repos.md`, `--add-repo` (default: `true`) auto-detects repo metadata and appends it. Pass `--no-add-repo` to skip.

---

## 9. Leaderboard App (`leaderboard/`)

Standalone Gradio app. No dependency on the orchestrator package.

### Data Loading (`data_loader.py`)

- `load_results(results_dir)` — scans `results/aggregated/*.json`, returns list of dicts
- `build_leaderboard_df(results)` — groups by `tool.display_name`, computes avg score, pivots per-benchmark scores into columns. Returns pandas DataFrame.
- `build_runs_df(results)` — one row per result file with columns: Category, Name, Benchmark, Score, Avg Cost Per Task, Avg Seconds Per Task, Avg Input Tokens Per Task, Avg Output Tokens Per Task. Returns pandas DataFrame.

### App Layout (`app.py`)

**Header:** Summary stats — total results, distinct tools, distinct configurations, entries evaluated.

**Leaderboard tab:**
- Sortable Gradio `Dataframe`
- Columns: Category (icon), Name (linked), Avg Score, one column per benchmark (repo)
- Default sort: Avg Score descending
- Search box on Name column
- Checkbox filter for Category (open-source / proprietary)

**Benchmark Runs tab:**
- Sortable Gradio `Dataframe`
- Default columns: Category, Name, Benchmark, Score, Avg Cost Per Task
- Column picker (`CheckboxGroup`) to toggle additional columns
- Same search and category filters

**About tab:**
- Gradio `Markdown` component
- Content loaded from `leaderboard/about.md`

### Auto-Refresh

Reloads data every 5 minutes (configurable) using Gradio's `every` parameter on a timer event.

### Deployment

`pyproject.toml` defines dependencies: `gradio`, `pandas`. Deployable via Dockerfile or HuggingFace Spaces metadata. The `results/aggregated/` directory is mounted, synced from git, or populated by CI.

---

## 10. Decisions Log

All design decisions made during the brainstorming process, with rationale.

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Python** for the orchestrator and CLI | Natural fit: Gradio leaderboard is Python, PyYAML for config, Click for CLI, subprocess for shell commands. Single language across the entire system. |
| 2 | **Sequential execution** first, no parallelism | The bottleneck is LLM API latency per tool, and running the same tool concurrently risks rate limits. Parallel support can be added later via `--concurrency` flag without architectural changes. |
| 3 | **Separate packages** for orchestrator and leaderboard | Leaderboard deploys independently (e.g., HuggingFace Spaces). It reads aggregated JSON files and has no code dependency on the orchestrator. |
| 4 | **Click** for CLI framework | Mature, composable subcommands, widely used in the Python ecosystem. Preferred over Typer (less mature) and argparse (more boilerplate). |
| 5 | **Pydantic v2** for config validation | Strong typing, clear error messages, and automatic validation on load. Catches config errors early rather than at run-time. |
| 6 | **Shell environment variables** for variable expansion | Commands are shell scripts — letting the shell resolve `${VAR}` natively is natural and avoids double-expansion bugs from Python-side string replacement. |
| 7 | **No GitPython** — subprocess calls to `git` | Simpler, more predictable, avoids a heavy dependency. Matches how tool commands themselves work (shell-based). |
| 8 | **Git worktrees** over full clones for isolation | Faster setup, shared object store, lower disk usage. Each run gets its own worktree under `<project>/.worktrees/<run_key>`. |
| 9 | **Parent-of-backport** as target branch base | `git rev-parse <backport_sha>^` gives exactly the state the target branch was in when the real backport was authored. |
| 10 | **Source branch detection is best-effort** | Uses `git branch -r --contains <sha>` with heuristics (prefer main/master, then shortest name). Complex branching may fail; failures surface as run errors. |
| 11 | **Branch reachability validation** on `add-backport` | `git branch -r --contains <original_sha>` rejects orphaned or force-pushed commits before they enter the dataset. |
| 12 | **Repos not in `repos.md`** still work | `BUILD_CMD`, `TEST_COMMAND`, `REPO_GUIDELINES` default to empty strings. Guideline check is skipped. This allows the dataset to grow without requiring immediate `repos.md` updates. |
| 13 | **8-character short SHAs** in filenames | Enough for uniqueness within a run set. Keeps filenames readable while remaining collision-resistant. |
| 14 | **Brace-matching JSON extraction** from LLM output | LLMs may emit preamble/postamble around JSON. The parser extracts the first `{...}` block rather than requiring clean stdout. Parsing failures are recorded as errors, not crashes. |
| 15 | **Resume by file existence** | Before each run, check if the result file already exists. If yes, skip. Simple, no state database needed, makes `run` idempotent. |
| 16 | **Aggregation as a separate step** | Per-run files are the source of truth. Aggregated files are derived and regenerated on demand. The leaderboard never reads per-run files directly. |
| 17 | **Setup command failure aborts the run** | If the tool's setup command exits non-zero, skip `generate_diff` and record as an error. No point running the tool if its prerequisites failed. |
| 18 | **Gradio auto-refresh at 5-minute intervals** | Picks up new results without restarting the app. Configurable for different deployment environments. |
| 19 | **`owner__repo`** naming for project clones | Double underscore avoids conflicts with repo names that contain single underscores or hyphens. |
| 20 | **No `rich` or heavy terminal UI dependency** | CLI output uses simple aligned columns. Keeps dependencies minimal and output parseable. |
