# How evaluation works

One case = one real backport. The pipeline under test must reproduce a human backporter's
result, and an independent verifier — not the pipeline's own self-report — decides the score.

## The loop

```
task image ──► agent (pipeline + model) runs in container ──► candidate patch
                                                              │
              verifier: fresh worktree at target ◄────────────┘
              apply candidate patch, run full build + complete test suite
                              │
              reward 1.0 (all green) / 0.0 (anything else)
```

1. Harbor builds the task image: a repo snapshot with `target` pinned just before the human
   backport, and the fix available on `source` (a commit, or an upstream patch against a
   vendored tree).
2. The agent adapter installs the pipeline inside the container and runs it against
   `/workspace/case.yaml` (bug description, branches, fix, build/test commands).
3. The pipeline works the repo and produces a candidate patch.
4. The verifier applies the candidate patch to a **fresh worktree** at `target` and runs the
   gates itself.
5. The reward lands in `jobs/<timestamp>/<task>__<id>/result.json`.

## Task anatomy

```
dataset/<task>/
├── environment/Dockerfile     # repo snapshot — leak-proof (below)
├── environment/case.yaml      # what the agent sees: bug description, branches, fix, gates
├── tests/test.sh              # verifier gates
├── solution/golden.patch      # the human backport diff (oracle only — never in the image)
├── solution/solve.sh          # oracle: apply golden to a fresh worktree
├── task.toml                  # timeouts, difficulty metadata
├── instruction.md             # task prompt
└── provenance.yaml            # (expat) pins & golden commits — kept outside the image
```

## What counts as success

- **Reward 1.0** — the candidate patch applies cleanly to a fresh `target` worktree, and the
  project's full build command **and complete test suite** pass. Nothing less.
- **Reward 0.0** — patch doesn't apply, build fails, any test fails, empty patch, crash, or
  timeout. No partial credit.
- **Full suite, always.** Gates are never module-scoped and tests are never excluded. If the
  container can't run the full suite, that's a task-container defect to fix — not a reason
  to scope the gates down.

## Leak-proofing

The agent must *solve* the backport, not *find* it:

- containers fetch only the commits a case needs (shallow, by SHA); the human backport — a
  child of `target` — is never fetched, and the origin remote is removed
- the golden patch lives outside the image
- `case.yaml` contains only what a real bug ticket would (see the minimal-prompt rule in
  [`README.md`](../dataset/README.md#prompt-policy))

## What is measured

| Metric | Source |
|---|---|
| reward (0/1) | `verifier/reward.txt` |
| wall time | `result.json` |
| model calls | pipeline run log |
| tokens, per phase | phase-tracker JSON (e.g. semantic triage vs cherry-pick vs verify) |
| route taken | verifier verdict (e.g. "downstream patch carries the fix") |

## Where results land

```
jobs/<timestamp>/<task>__<id>/
├── result.json                        # reward + metrics (harbor)
├── verifier/reward.txt                # 0 or 1
├── verifier/test-stdout.txt           # gate output (the pass/fail evidence)
├── trial.log, job.log                 # harbor-level logs
└── artifacts/workspace/amalgamator/runs/case_*/
    ├── run_log.txt                    # full pipeline log — every model call
    ├── candidate.patch                # the pipeline's output
    ├── dossier.md                     # per-case dossier
    └── semantic_triage.json, phase-tracker .json
```

Completed runs are curated into [`results/runs/`](../results/); `jobs/` itself is gitignored.
