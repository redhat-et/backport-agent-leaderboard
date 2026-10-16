# Evaluating a different backporting pipeline

The benchmark is pipeline-agnostic: the tasks, the verifier, and the scoring do not know or
care what runs inside the container. Amalgamator is one adapter; any backporting pipeline can
be evaluated the same way.

## The contract

A pipeline is evaluable here if it can:

1. **be installed inside a task container** — any language, from git, pip, a binary, whatever
   the image supports — and
2. **read `/workspace/case.yaml`** — bug description, source/target branches, the fix (commit
   or patch), build + test commands — **and produce changes on the `target` branch** of the
   repo at `/workspace/<repo>`.

Everything else (the repo snapshot, the gates, the golden, the reward) is provided by the
task.

## Write an adapter

A Harbor agent adapter implements `install()` and `run()`. The annotated example is
[`src/amalgamator_tasks/amalgamator.py`](../src/amalgamator_tasks/amalgamator.py):

- `install()` — clone your pipeline into the container (a host-side `GITHUB_TOKEN` is handed
  in via env for private repos; never log it)
- `run()` — write the model/endpoint from `-m` + env into your pipeline's config, then exec
  the pipeline against `/workspace/case.yaml`

Package your adapter (e.g. `src/your_pkg/…`), then run it exactly like amalgamator:

```sh
uv run harbor run -p ./dataset -i '<task>' -m openai/<model> \
    -a your_pkg.your_module:YourAgent -e docker
```

## What stays identical for every pipeline

- the task images and the leak-proofed repo snapshots
- the verifier gates: **full build + complete test suite**, applied to a fresh worktree
- the binary 0/1 reward, the metrics captured, and the leaderboard format

Comparing pipelines is the point: same tasks, same bar, same scoring.

## Adding tasks

[`tools/gen_crate_tasks.py`](../tools/gen_crate_tasks.py) generates a family of tasks from
`dataset/backports.csv` — leak-proof Dockerfiles (shallow by-SHA fetch of only the two
commits needed), golden = the real human backport diff, difficulty tiers from the CSV. Use
it as the template for new families. After generating: `cd dataset && uv run harbor sync`,
then oracle-validate each new task before spending model tokens.
