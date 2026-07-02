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
│   ├── data_loader.py           # Result JSON → ConfigMap reading
│   ├── about.md                 # About tab content
│   └── tests/                   # Leaderboard test suite
│
├── results/                     # Per-run result JSON files
│   └── aggregated/              # Aggregated files for leaderboard
│
├── diffs/                       # Retained diffs for debugging
├── projects/                    # Cached repository clones
│
├── run.py                       # OpenShift job launcher + result collector
│                                #   reads any evals/<repo>/config.yaml
│
└── evals/                       # Containerized evaluation harness (OpenShift)
    ├── crate/                   # Java/Maven — reference implementation
    │   ├── Containerfile        # Pod image: JDK 24, Maven, Python, patch, git
    │   ├── config.yaml          # All tunable params (image, namespace, dataset)
    │   ├── README.md            # Step-by-step: build, push, run, collect
    │   └── scripts/
    │       └── generic_claude_backport.py
    ├── cri-o/                   # Go — same structure as crate/
    └── django/                  # Python — same structure as crate/
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

---

## OpenShift Containerized Evaluation

> **This is what this PR adds.** The `backport_bench/` CLI above runs benchmarks locally.
> The `evals/` harness runs them in parallel on OpenShift pods — useful for compiled
> languages (Java, Go) that are slow to build locally and benefit from parallelism.

Each pod clones the repo, runs **Raw Claude** or **Amalgamator**, applies the patch,
builds the code, runs the targeted tests, and saves results to OpenShift ConfigMaps.
A live Gradio leaderboard reads those ConfigMaps and auto-refreshes every 60 seconds.

### Repos evaluated

| Repo | Language | Eval config |
|------|----------|-------------|
| `crate/crate` | Java / Maven | [`evals/crate/`](evals/crate/) |
| `cri-o/cri-o` | Go | [`evals/cri-o/`](evals/cri-o/) |
| `django/django` | Python | [`evals/django/`](evals/django/) |

### Metrics captured

| Metric | Description |
|--------|-------------|
| **Apply Rate** | Did the agent's patch apply cleanly? |
| **Test Pass Rate** | Did the targeted test pass after patching? |
| **Semantic Equivalence** | Does the agent's patch match the ground-truth backport commit? |
| **Baseline Test** | Did the test pass *before* patching? (flags pre-existing failures) |
| **Cost / Tokens / Latency** | API spend and runtime per case |

### Prerequisites

- OpenShift cluster with `oc` CLI
- Podman (for building images — use `--platform linux/amd64` on Apple Silicon)
- Python 3.10+ with `pyyaml`
- Vertex AI credentials for Claude API access

### Step 1 — One-time cluster setup

```bash
oc new-project backport-agent-leaderboard
oc apply -f infra/rbac.yaml

# Vertex AI credentials
oc create secret generic gcloud-adc \
  --from-file=application_default_credentials.json=$HOME/.config/gcloud/application_default_credentials.json

# Raw Claude script (shared by all repos)
oc create configmap raw-claude-script \
  --from-file=generic_claude_backport.py=evals/crate/scripts/generic_claude_backport.py

# Amalgamator pipeline source (tar from your local Amalgamator clone)
tar czf /tmp/amalgamator.tar.gz \
  -C /path/to/amalgamator auto_bug_fix/ auto_code_gen/ common/ pyproject.toml uv.lock
oc create configmap amalgamator-src --from-file=amalgamator.tar.gz=/tmp/amalgamator.tar.gz
```

See [`infra/README.md`](infra/README.md) for full details.

### Step 2 — Build and push images

```bash
# Build for each repo (adjust registry to yours)
podman build --platform linux/amd64 -t quay.io/<org>/crate-eval:latest \
  -f evals/crate/Containerfile evals/crate/ && podman push quay.io/<org>/crate-eval:latest

podman build --platform linux/amd64 -t quay.io/<org>/crio-eval:latest \
  -f evals/cri-o/Containerfile evals/cri-o/ && podman push quay.io/<org>/crio-eval:latest

podman build --platform linux/amd64 -t quay.io/<org>/django-eval:latest \
  -f evals/django/Containerfile evals/django/ && podman push quay.io/<org>/django-eval:latest
```

Update `image:` and `vertex_project:` in each `evals/<repo>/config.yaml`.

### Step 3 — Run

```bash
# Launch all jobs for all repos (runs in parallel on OpenShift)
python3 run.py --config evals/crate/config.yaml
python3 run.py --config evals/cri-o/config.yaml
python3 run.py --config evals/django/config.yaml

# Watch pods
oc get pods -n backport-agent-leaderboard

# Collect results when done (~30 min raw-claude, ~90 min amalgamator)
python3 run.py --config evals/crate/config.yaml --collect
```

### Step 4 — Leaderboard

```bash
# Deploy to OpenShift (reads ConfigMaps live, auto-refreshes every 60 s)
podman build --platform linux/amd64 -t quay.io/<org>/backport-leaderboard:latest \
  -f infra/leaderboard/Containerfile .
podman push quay.io/<org>/backport-leaderboard:latest
oc apply -f infra/leaderboard/leaderboard.yaml
oc get route backport-leaderboard   # public URL
```

See [`evals/crate/README.md`](evals/crate/README.md) for the full reference walkthrough
and [`infra/README.md`](infra/README.md) for one-time cluster setup details.
