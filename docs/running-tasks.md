# Running the benchmark, step by step

## Prerequisites

- macOS or Linux, Docker running
- [uv](https://docs.astral.sh/uv/)
- a GitHub token with read access to `redhat-et/amalgamator` (private): `gh auth login`
- an LLM API key — any OpenAI-compatible gateway or Anthropic endpoint

## 1. Install

```sh
git clone https://github.com/redhat-et/backport-agent-leaderboard.git
cd backport-agent-leaderboard
uv sync
```

## 2. Set credentials

```sh
export GITHUB_TOKEN=$(gh auth token)   # lets task containers clone amalgamator
```

## 3. Point at a model endpoint

`-m provider/model` selects the model; credentials come from standard env vars per provider
prefix — nothing else in the repo is model-specific:

| `-m` prefix | env vars |
|---|---|
| `openai/*` | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` for gateways) |
| `anthropic/*` | `ANTHROPIC_API_KEY` |

Worked example — **GLM via the EnMaaS gateway**:

```sh
export OPENAI_BASE_URL=https://api.enmaas.devshift.net/v1
export OPENAI_API_KEY=<key>
# then:  -m openai/rits/zai-org/glm-5-3
```

Swapping endpoints = change the env vars and `-m`. The same task, verifier, and scoring run
for every model.

## 4. Validate tasks with the oracle (no model, no tokens)

Every new or edited task should be oracle-checked first — it applies the golden patch and
runs the gates, proving the task container itself is green:

```sh
uv run harbor run -p ./dataset -i '<task-name>' -a oracle -e docker
# expect reward 1.0
```

## 5. Run tasks

```sh
# one task
uv run harbor run -p ./dataset -i 'expat-cve-2025-59375-c10s' \
    -m openai/rits/zai-org/glm-5-3 \
    -a amalgamator_tasks.amalgamator:Amalgamator \
    -e docker

# a family
uv run harbor run -p ./dataset -i 'expat-*' -m openai/<model> \
    -a amalgamator_tasks.amalgamator:Amalgamator -e docker

# the whole dataset, 2 tasks in parallel
uv run harbor run -p ./dataset -m openai/<model> \
    -a amalgamator_tasks.amalgamator:Amalgamator -e docker -n 2
```

> **`-a` needs a colon**: `module:Class` (`amalgamator_tasks.amalgamator:Amalgamator`),
> not the dot form.

## 6. Read results

```sh
ls jobs/<timestamp>/<task>__<id>/     # result.json, verifier/, artifacts/
uv run harbor view jobs               # rendered summary
```

Reward is in `result.json` (metrics) and `verifier/reward.txt` (0/1). The full log and the
candidate patch are under `artifacts/workspace/amalgamator/runs/case_*/target/`.

## 7. After editing any task file

```sh
cd dataset && uv run harbor sync       # refresh content digests in dataset.toml
```

Task edits without a re-sync are silently ignored.

## Practical notes

- **Timeouts** live in each `task.toml` (`[agent]`, `[verifier]`, `build_timeout_sec`).
  Rough costs: an expat run ≈ 2.5–5 h wall time and a few GB of disk; crate's full test
  suite alone is ~30 min.
- **Keep runs alive on macOS** (harbor dies with the terminal otherwise):

  ```sh
  nohup bash -c 'uv run harbor run … ' > /tmp/run.log 2>&1 &
  nohup caffeinate -i -w $! >/dev/null 2>&1 &
  ```

- **Disk**: harbor deletes task images after each run, but budget ~2 GB per concurrent task
  during a run.
