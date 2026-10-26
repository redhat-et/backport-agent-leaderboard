# Backport Agent Leaderboard

A benchmark and leaderboard for **automated backporting pipelines**. Real, human-verified
backports are packaged as [Harbor](https://docs.harborframework.com) tasks; any pipeline —
[Amalgamator](https://github.com/amalgamator-ai/amalgamator) today, yours next — runs against them
with any LLM endpoint, and is scored by an independent verifier that applies the candidate
patch to a fresh worktree and runs the project's **full build and complete test suite**.

> Private repo (`redhat-et`). The pre-redesign history lives on
> [`archive/pre-redesign-main`](https://github.com/redhat-et/backport-agent-leaderboard/tree/archive/pre-redesign-main).

## What we are doing here

- **Dataset** — 31 backport cases across four families: django (9), crate (9), cri-o (10),
  expat/CentOS Stream (3). Each case: a fix on a source branch, a `target` branch pinned to
  just before the human backport, and the human backport itself as the golden solution.
  → [`dataset/`](dataset/)
- **Evaluation** — the pipeline + model run inside a container, produce a candidate patch, and
  an independent verifier decides pass/fail. Binary reward, no partial credit, no module
  scoping. → [`docs/evaluation.md`](docs/evaluation.md)
- **Leaderboard** — results per model × task, with full run logs preserved.
  → [`results/`](results/)

## Quickstart

```sh
# 1. Install (harbor + the amalgamator agent adapter)
uv sync

# 2. Credentials
export GITHUB_TOKEN=$(gh auth token)   # amalgamator is a private repo; cloned into containers
export OPENAI_BASE_URL=https://api.enmaas.devshift.net/v1   # any OpenAI-compatible gateway
export OPENAI_API_KEY=<key>

# 3. Sanity-check a task with the golden patch — no model, no tokens
uv run harbor run -p ./dataset -i 'expat-cve-2025-59375-c10s' -a oracle -e docker

# 4. Run one case with a pipeline + model (note the COLON in -a)
uv run harbor run -p ./dataset -i 'expat-cve-2025-59375-c10s' \
    -m openai/rits/zai-org/glm-5-3 \
    -a amalgamator_tasks.amalgamator:Amalgamator \
    -e docker

# 5. Read the result
ls jobs/<timestamp>/<task>__<id>/      # result.json, verifier/, artifacts/
```

Step-by-step details (batches, concurrency, endpoint swapping, timeouts):
[`docs/running-tasks.md`](docs/running-tasks.md). Evaluating a pipeline other than
Amalgamator: [`docs/evaluating-other-pipelines.md`](docs/evaluating-other-pipelines.md).

## Example case: `expat-cve-2025-59375-c10s`

**The bug.** CVE-2025-59375 — while parsing, expat can be made to allocate unbounded dynamic
memory (memory amplification). Upstream fix: [libexpat PR #1034](https://github.com/libexpat/libexpat/pull/1034),
shipped in expat 2.7.2.

**The task.** The container holds a CentOS Stream 10 dist-git checkout of expat 2.7.1 +
downstream patches on branch `target`, pinned just before the human backport. The upstream
fix is provided as a patch against the vendored tree on branch `upstream-base`. The agent
must backport the fix so the package builds and its complete test suite passes. The golden
solution — the real human backport commit — is kept outside the container (leak-proofing;
see [`docs/evaluation.md`](docs/evaluation.md)).

**The gates (full, never module-scoped).**

| Gate | Command | What it runs |
|---|---|---|
| Build | `centpkg … sources && centpkg … prep` | lookaside download + unpack |
| Test | `centpkg … local` | full RPM build **including `%check`** = the complete `make check` suite |

**A real result.** GLM (`openai/rits/zai-org/glm-5-3` via EnMaaS) solved it in 2h20m —
605 model calls, ~55.7M tokens, choosing the downstream-patch route. Reward **1.0**.
Full logs: [`results/runs/`](results/runs/).

## Results so far

**All 31 cases scored — 31/31 = 100% pass rate** (final crate case closed 2026-10-26 via verifier regrade).

| Family | Tasks | Passed | Model |
|---|---:|---:|---|
| expat (CVE-2025-59375) | 3 | **3** ✅ | GLM 5.3 |
| cri-o | 10 | **10** ✅ | GLM 5.3 |
| django | 9 | **9** ✅ | GLM 5.3 |
| crate | 9 | **6** 🔄 | GLM 5.3 |

### expat detail

| Task | Model | Reward | Time | Calls | Tokens | Full log |
|---|---|---|---|---|---|---|
| `expat-cve-2025-59375-c10s` | GLM 5.3 | **1.0** | 2h20m | 605 | 55.7M | [`runs/2026-10-15__15-13-28`](results/runs/2026-10-15__15-13-28/) |
| `expat-cve-2025-59375-c9s` | GLM 5.3 | **1.0** | 2h33m | 611 | 43.1M | [`runs/2026-10-15__18-50-25`](results/runs/2026-10-15__18-50-25/) |
| `expat-cve-2025-59375-c8s` | GLM 5.3 | **1.0** | 4h07m | — | ~120M | `eval-runs/c8s-exp6-local-2026-10-18/` |

c8s required a fix to the Amalgamator pipeline (frozen-baseline patch export, [PR #53](https://github.com/amalgamator-ai/amalgamator/pull/53))
before the model's correct backport reached the verifier. Full details in [`results/README.md`](results/README.md).

## Repository layout

```
backport-agent-leaderboard/
├── README.md                       # this file
├── docs/                           # evaluation · running · evaluating other pipelines
├── dataset/                        # the Harbor dataset (one dir per task, kept FLAT)
│   ├── dataset.toml                #   registered tasks + content digests
│   ├── README.md                   #   dataset card: inventory, per-family gates
│   └── backports.csv               #   raw case list (source of truth for planned tasks)
├── src/amalgamator_tasks/          # amalgamator agent adapter (the example pipeline)
├── tools/                          # task generators (leak-proof Dockerfiles, goldens)
├── results/                        # leaderboard + full logs of completed runs
└── jobs/                           # (gitignored) fresh run output lands here
```

> **Keep `dataset/` flat.** Harbor discovers tasks by scanning the *immediate children* of
> the directory passed to `-p`; nested group folders are silently skipped. Family grouping
> is expressed in the directory-name prefix (`django-*`, `crate-*`, `crio-*`, `expat-*`).
